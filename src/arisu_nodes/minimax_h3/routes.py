"""Resource browsing, bounded probes, and range-capable original/proxy playback."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import threading
from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, Optional

import folder_paths
from aiohttp import web

from ..common.core import browse_directory, contained_path, image_content_type, is_animated_image, relative_path
from ..common.paths import image_roots, select_root
from .core import Resource
from .media import StaleResource, UnsupportedMedia, metadata, source_path
from .proxies import ProxyBusy, ProxyJob, ProxyManager

logger = logging.getLogger(__name__)
HEADERS = {"X-Content-Type-Options": "nosniff"}
_PROBE_GUARD = threading.BoundedSemaphore(2)


def roots() -> Dict[str, str]:
    """Resolve the shared administrator-owned root snapshot."""
    return image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory())


def candidate(path: str) -> bool:
    """Preserve image policy and use ComfyUI's stock media candidate filter."""
    return bool(image_content_type(path) or folder_paths.filter_files_content_types([path], ["video", "audio"]))


def resource(query: Any) -> Resource:
    """Parse only relative browser locations, never physical base directories."""
    root, path = query.get("root", "input"), relative_path(query.get("path", ""))
    if not isinstance(root, str) or not candidate(path):
        raise UnsupportedMedia("unsupported resource type")
    return Resource("request", "image" if image_content_type(path) else "video", root, path)


async def bounded(function: Callable[..., Any], *args: Any) -> Any:
    """Retain admission until the actual blocking work finishes after cancellation."""
    if not _PROBE_GUARD.acquire(blocking=False):
        raise ProxyBusy("resource workers are busy")

    def work() -> Any:
        try:
            return function(*args)
        finally:
            _PROBE_GUARD.release()

    task = asyncio.create_task(asyncio.to_thread(work))

    def observed(done: asyncio.Task[Any]):
        if not done.cancelled():
            done.exception()

    task.add_done_callback(observed)
    return await asyncio.shield(task)


def listing(root: str, path: str, tree: bool) -> Dict[str, Any]:
    """List contained candidates, with the same roots/ancestors as image Browse."""
    allowed = roots()
    base = select_root(allowed, root)
    absolute = contained_path(base, path, allow_empty=True)
    result = browse_directory(absolute, base, tree)
    files = []
    for name in sorted(os.listdir(absolute), key=str.casefold):
        relative = "/".join(part for part in (result.path, name) if part)
        try:
            full = source_path(allowed, root, relative)
            if not candidate(name) or (image_content_type(name) and is_animated_image(full)):
                continue
            files.append(name)
        except (OSError, ValueError):
            continue
    return {
        "root": root,
        "path": result.path,
        "parent": result.parent,
        "dirs": list(result.dirs),
        "files": files,
        "kinds": {name: "image" if image_content_type(name) else "media" for name in files},
        "ancestors": [{"path": level.path, "dirs": list(level.dirs)} for level in result.ancestors],
        "roots": [{"id": key, "label": key} for key in allowed],
    }


class ProxyResponse(web.FileResponse):
    """Pin a ready proxy until FileResponse has finished streaming its ranges."""

    def __init__(self, manager: ProxyManager, handle: str, job: ProxyJob):
        self.manager, self.handle, self.job = manager, handle, job
        job.streams += 1
        super().__init__(job.path, headers={**HEADERS, "Content-Type": "video/webm" if job.item.kind == "video" else "audio/webm"})

    async def prepare(self, request: web.Request) -> Any:
        try:
            self.manager.get(self.handle)
            return await super().prepare(request)
        finally:
            self.job.streams -= 1


def register_routes(routes: web.RouteTableDef, app: Optional[web.Application] = None):
    """Register separate media routes, leaving existing image routes unchanged."""
    manager: Optional[ProxyManager] = None

    def proxies() -> ProxyManager:
        nonlocal manager
        if manager is None:
            manager = ProxyManager(roots(), folder_paths.get_temp_directory())
        return manager

    async def cleanup(application: web.Application):
        if manager:
            await manager.close()

    if app is not None:
        app.on_cleanup.append(cleanup)

    def route(method: str, path: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        def decorate(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            async def guarded(request: web.Request) -> web.StreamResponse:
                try:
                    return await handler(request)
                except web.HTTPException:
                    raise
                except (KeyError, FileNotFoundError, NotADirectoryError):
                    status, error = 404, "resource not found"
                except StaleResource:
                    status, error = 409, "source changed; rerun or reselect the resource"
                except UnsupportedMedia:
                    status, error = 415, "unsupported, external, or incomplete media"
                except ProxyBusy:
                    status, error = 429, "resource work is busy; retry shortly"
                except PermissionError:
                    status, error = 403, "resource cannot be read"
                except (ValueError, TypeError, UnicodeError):
                    logger.warning("invalid resource request", exc_info=True)
                    status, error = 400, "invalid resource location or selection"
                except Exception:
                    logger.exception("resource request failed")
                    status, error = 500, "resource request failed; see the server log"
                return web.json_response({"error": error}, status=status, headers=HEADERS)

            routes.route(method, "/arisu/resources" + path)(guarded)
            return handler

        return decorate

    @route("GET", "/browse")
    async def browse(request: web.Request) -> web.Response:
        data = await bounded(
            listing,
            request.query.get("root", "input"),
            relative_path(request.query.get("path", ""), True),
            request.query.get("tree", "1") != "0",
        )
        return web.json_response(data, headers=HEADERS)

    @route("GET", "/metadata")
    async def probe(request: web.Request) -> web.Response:
        info = await bounded(metadata, roots(), resource(request.query))
        return web.json_response(info, headers=HEADERS)

    @route("GET", "/view")
    async def view(request: web.Request) -> web.StreamResponse:
        item = resource(request.query)
        # Images remain verbatim streams. Media must additionally be finite and self-contained.
        if item.kind != "image":
            await bounded(metadata, roots(), item)
        path = await bounded(source_path, roots(), item.root, item.path)
        mime = image_content_type(item.path) or mimetypes.guess_type(item.path, strict=False)[0] or "application/octet-stream"
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": mime})

    @route("POST", "/proxy")
    async def create(request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        if request.content_length and request.content_length > 1024 * 1024:
            raise web.HTTPRequestEntityTooLarge(max_size=1024 * 1024, actual_size=request.content_length)
        body = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise web.HTTPRequestEntityTooLarge(max_size=1024 * 1024, actual_size=len(body))
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {"root", "path", "revision"} or not isinstance(data["revision"], str):
            raise ValueError("invalid proxy request")
        item = replace(resource(data), revision=data["revision"])
        info = await bounded(metadata, roots(), item)
        if info["kind"] == "image":
            raise UnsupportedMedia("images do not need playback proxies")
        item = replace(item, kind=info["kind"])
        handle = await proxies().start(item, info["duration"])
        return web.json_response({"id": handle}, status=202, headers=HEADERS)

    @route("GET", "/proxy/{id}")
    async def status(request: web.Request) -> web.Response:
        handle = request.match_info["id"]
        job = await bounded(proxies().get, handle)
        return web.json_response(
            {
                "state": job.state,
                "progress": job.progress,
                "error": job.error,
                "url": f"/arisu/resources/proxy/{handle}/view" if job.state == "ready" else None,
            },
            headers=HEADERS,
        )

    @route("GET", "/proxy/{id}/view")
    async def playback(request: web.Request) -> web.StreamResponse:
        handle = request.match_info["id"]
        job = await bounded(proxies().get, handle)
        if job.state != "ready":
            raise web.HTTPConflict(text="playback is not ready")
        return ProxyResponse(proxies(), handle, job)

    @route("DELETE", "/proxy/{id}")
    async def release(request: web.Request) -> web.Response:
        await proxies().release(request.match_info["id"])
        return web.json_response({"released": True}, headers=HEADERS)
