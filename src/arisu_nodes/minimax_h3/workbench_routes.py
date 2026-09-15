"""Same-origin Workbench actions; GPU preparation uses ComfyUI's existing queue."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict
from urllib.parse import urlsplit

import execution
from aiohttp import web

from .agent_docker import AgentBusy
from .core import preparation_graph
from .workbench import Workbench, skill_catalog

logger = logging.getLogger(__name__)
MAX_BODY = 1024 * 1024


async def body(request: web.Request) -> Dict[str, Any]:
    """Require same-origin JSON and count streamed request bytes."""
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        raise web.HTTPForbidden(text="Cross-origin Workbench requests are refused")
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        raise web.HTTPForbidden(text="Cross-origin Workbench requests are refused")
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="JSON required")
    content = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        content.extend(chunk)
        if len(content) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(content))
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def register_routes(server: Any, owner: Workbench):
    """Register bounded actions without exposing Docker's general command surface."""
    routes = server.routes
    tasks = set()

    async def reap():
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(owner.reap)

    async def startup(app: web.Application):
        app["arisu_workbench_reaper"] = asyncio.create_task(reap())

    async def cleanup(app: web.Application):
        task = app.get("arisu_workbench_reaper")
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(owner.close)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if getattr(server, "app", None) is not None:
        server.app.on_startup.append(startup)
        server.app.on_cleanup.append(cleanup)

    def spawn(function: Any, *args: Any):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        tasks.add(task)

        def completed(done: asyncio.Task):
            tasks.discard(done)
            if not done.cancelled() and done.exception():
                logger.error("Workbench background operation failed", exc_info=done.exception())

        task.add_done_callback(completed)

    @routes.get("/arisu/workbench/status")
    async def status(request: web.Request) -> web.Response:
        value = await asyncio.to_thread(owner.agents.status)
        value["skills"] = [
            {"id": key, "name": key.split(":", 1)[1], "source": key.split(":", 1)[0]} for key in skill_catalog(owner.directory)
        ]
        return web.json_response(value)

    @routes.get("/arisu/workbench/logs")
    async def logs(request: web.Request) -> web.Response:
        try:
            cursor = int(request.query.get("cursor", "0"))
            if cursor < 0:
                raise ValueError("negative cursor")
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid log cursor") from None
        return web.json_response(
            owner.agents.read_logs(request.query.get("session", ""), cursor, request.query.get("job", "")),
            headers={"Cache-Control": "no-store"},
        )

    @routes.post("/arisu/workbench/action")
    async def action(request: web.Request) -> web.Response:
        try:
            value = await body(request)
            agent, operation = value.get("agent"), value.get("action")
            owner.agents.image(agent)
            if operation == "configure":
                await asyncio.to_thread(owner.agents.configure, agent, value.get("model"), value.get("effort"))
            else:
                if operation not in ("build", "update", "login", "logout", "remove"):
                    raise ValueError("unsupported agent action")
                if operation == "remove" and value.get("confirm") is not True:
                    raise ValueError("confirm complete removal")
                if not owner.agents.guard.acquire(blocking=False):
                    raise AgentBusy("Workbench is busy")
                spawn(owner.agents.manage, agent, operation, True)
            return web.json_response({"accepted": True})
        except AgentBusy as error:
            return web.json_response({"error": str(error)}, status=409)
        except (ValueError, TypeError) as error:
            return web.json_response({"error": str(error)}, status=400)
        except web.HTTPException:
            raise
        except Exception:
            logger.exception("Workbench settings failed")
            return web.json_response({"error": "Agent settings failed; see server logs."}, status=500)

    @routes.post("/arisu/workbench/generate")
    async def generate(request: web.Request) -> web.Response:
        job = None
        reservation = None
        started = False
        try:
            value = await body(request)
            node_id = value.get("node_id")
            workflow = value.get("workflow")
            if not isinstance(node_id, str) or not isinstance(workflow, str) or not 1 <= len(workflow) <= 160:
                raise ValueError("invalid workflow identity")
            graph = preparation_graph(value.get("prompt"), node_id)
            reservation = asyncio.create_task(asyncio.to_thread(owner.create, node_id, workflow, value.get("options"), graph))
            job = await asyncio.shield(reservation)
            prompt_id = str(uuid.uuid4())
            valid = await execution.validate_prompt(prompt_id, graph, [node_id])
            if not valid[0]:
                raise ValueError("preparation inputs are invalid; check the connected loaders")
            number = server.number
            server.number += 1
            queue = server.prompt_queue
            server.prompt_queue.put((number, prompt_id, graph, {"client_id": value.get("client_id")}, [node_id], {}))

            def preparation_finished() -> bool:
                if job.cancelled.is_set():
                    queue.delete_queue_item(lambda entry: entry[1] == prompt_id)
                running, pending = queue.get_current_queue()
                return not any(entry[1] == prompt_id for entry in running + pending)

            job.queue_finished = preparation_finished
            spawn(owner.execute, job)
            started = True
            return web.json_response({"id": job.id, "prompt_id": prompt_id}, status=202)
        except asyncio.CancelledError:
            # A disconnected request cannot abandon a reservation still running in a thread.
            if job is None and reservation is not None:
                try:
                    job = await reservation
                except Exception:
                    logger.exception("Cancelled Workbench reservation failed")
            if job is not None and not started:
                job.cancelled.set()
                spawn(owner.execute, job)
            raise
        except AgentBusy as error:
            return web.json_response({"error": str(error)}, status=409)
        except web.HTTPException:
            raise
        except Exception as error:
            if job:
                job.error = "Preparation could not be queued."
                job.prepared.set()
                spawn(owner.execute, job)
            if isinstance(error, (ValueError, TypeError, KeyError)):
                return web.json_response({"error": str(error)}, status=400)
            logger.exception("Workbench generation request failed")
            return web.json_response({"error": "Unable to prepare prompt generation."}, status=500)

    @routes.get("/arisu/workbench/jobs/{identifier}")
    async def job_status(request: web.Request) -> web.Response:
        try:
            return web.json_response(owner.get(request.match_info["identifier"]).public())
        except ValueError:
            raise web.HTTPNotFound() from None

    @routes.post("/arisu/workbench/release")
    async def release(request: web.Request) -> web.Response:
        try:
            value = await body(request)
            if "id" in value:
                owner.get(value["id"]).cancelled.set()
            elif isinstance(value.get("workflow"), str) and 1 <= len(value["workflow"]) <= 160:
                owner.release(value["workflow"])
            else:
                raise ValueError("workflow or job ID required")
            return web.json_response({"released": True})
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "Invalid release request"}, status=400)
