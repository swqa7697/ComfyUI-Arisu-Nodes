"""HTTP regression for explicit Workbench actions and preparation admission."""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.arisu_nodes.minimax_h3 import workbench_routes
from src.arisu_nodes.minimax_h3.workbench import Workbench

pytestmark = pytest.mark.comfyui


def test_workbench_routes_reject_untrusted_requests_and_queue_only_preparation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = Workbench(tmp_path / "user", tmp_path / "cache")
    real_status = owner.agents.status
    status = {"docker": True, "agents": {"codex": {"ready": True, "selection": {"model": "test", "effort": "medium"}}}}
    monkeypatch.setattr(owner.agents, "status", lambda *args: status)
    queued = []
    server = SimpleNamespace(routes=web.RouteTableDef(), number=0, prompt_queue=SimpleNamespace(put=queued.append), app=None)

    async def validate(identifier, graph, targets):
        assert set(graph) == {"w"} and targets == ["w"]
        assert graph["w"]["inputs"]["prepare_job"] in owner.jobs
        return True, None, targets, {}

    monkeypatch.setattr(workbench_routes.execution, "validate_prompt", validate)

    def execute(job):
        job.state = "complete"
        job.draft = "review me"
        owner.agents.guard.release()

    monkeypatch.setattr(owner, "execute", execute)
    workbench_routes.register_routes(server, owner)

    async def scenario():
        application = web.Application()
        application.add_routes(server.routes)
        async with TestClient(TestServer(application)) as client:
            response = await client.get("/arisu/workbench/status")
            assert response.status == 200
            assert (await response.json())["skills"] == [
                {"id": "bundled:no-ref", "name": "no-ref", "source": "bundled"},
                {"id": "bundled:with-ref", "name": "with-ref", "source": "bundled"},
            ]
            owner.agents.begin_logs("codex", "login")
            owner.agents.log("https://example.test/device CODE")
            response = await client.get("/arisu/workbench/logs")
            page = await response.json()
            assert page["lines"] == ["https://example.test/device CODE"] and response.headers["Cache-Control"] == "no-store"
            response = await client.get("/arisu/workbench/logs", params={"session": page["session"], "cursor": str(page["cursor"])})
            assert not (await response.json())["lines"]
            for cursor in ("-1", "bad"):
                response = await client.get("/arisu/workbench/logs", params={"cursor": cursor})
                assert response.status == 400
            for headers, data, code in (
                ({"Content-Type": "text/plain"}, "{}", 415),
                ({"Content-Type": "application/json", "Origin": "https://foreign.invalid"}, "{}", 403),
                ({"Content-Type": "application/json"}, "{", 400),
                ({"Content-Type": "application/json"}, " " * (1024 * 1024 + 1), 413),
            ):
                response = await client.post("/arisu/workbench/action", data=data, headers=headers)
                assert response.status == code
            response = await client.post("/arisu/workbench/action", json={"agent": "codex", "action": "shell"})
            assert response.status == 400
            response = await client.post("/arisu/workbench/action", json={"agent": "codex", "action": "remove"})
            assert response.status == 400
            graph = {
                "w": {"class_type": "ArisuMiniMaxH3PromptWorkbench", "inputs": {"finalized_prompt": "keep"}},
                "s": {"class_type": "KSampler", "inputs": {"x": ["w", 0]}},
            }
            # A readiness probe must delay the first click, not reject it as busy.
            entered, finish = threading.Event(), threading.Event()

            def inspect_agent(*args: Any) -> Dict[str, Any]:
                entered.set()
                assert finish.wait(5)
                return {
                    "authenticated": True,
                    "policy_ready": True,
                    "policy_revision": 6,
                    "models": [{"id": "test", "efforts": ["medium"]}],
                }

            with monkeypatch.context() as local:
                local.setattr(owner.agents, "status", real_status)
                local.setattr(shutil, "which", lambda name: "/test/docker")
                local.setattr(
                    owner.agents,
                    "command",
                    lambda args, **kwargs: (
                        json.dumps([{"Config": {"Labels": {"org.arisu.workbench.policy": "6"}}}])
                        if args[:2] == ["image", "inspect"]
                        else "linux"
                    ),
                )
                local.setattr(owner.agents, "owned", lambda *args: True)
                local.setattr(owner.agents, "invoke", inspect_agent)
                owner.agents._status = status
                probe = asyncio.create_task(client.get("/arisu/workbench/status"))
                assert await asyncio.to_thread(entered.wait, 2)
                request = asyncio.create_task(
                    client.post("/arisu/workbench/generate", json={"node_id": "w", "workflow": "tab", "prompt": graph, "options": {}})
                )
                try:
                    await asyncio.sleep(0.05)
                    assert not request.done(), "generation rejected an in-progress readiness probe"
                finally:
                    finish.set()
                    await probe
                    response = await request
            assert response.status == 202
            identifier = (await response.json())["id"]
            assert len(queued) == 1 and set(queued[0][2]) == {"w"}
            await asyncio.sleep(0.01)
            response = await client.get("/arisu/workbench/jobs/" + identifier)
            assert (await response.json())["draft"] == "review me"
            # Real operations still refuse concurrent generation immediately.
            owner.agents.guard.acquire()
            try:
                response = await client.post(
                    "/arisu/workbench/generate", json={"node_id": "w", "workflow": "other", "prompt": graph, "options": {}}
                )
                assert response.status == 409 and len(queued) == 1
            finally:
                owner.agents.guard.release()
            response = await client.post("/arisu/workbench/release", json={"workflow": "tab"})
            assert response.status == 200
            response = await client.get("/arisu/workbench/jobs/" + identifier)
            assert response.status == 404

        # Cancellation during a threaded reservation must still hand its guard to cleanup.
        entered, finish = threading.Event(), threading.Event()
        create = owner.create

        def delayed_create(*args):
            job = create(*args)
            entered.set()
            finish.wait(2)
            return job

        async def direct_body(value):
            return value

        monkeypatch.setattr(owner, "create", delayed_create)
        monkeypatch.setattr(workbench_routes, "body", direct_body)
        handler = next(route.handler for route in server.routes if route.path == "/arisu/workbench/generate")
        request = asyncio.create_task(handler({"node_id": "w", "workflow": "cancelled-tab", "prompt": graph, "options": {}}))
        assert await asyncio.to_thread(entered.wait, 2)
        request.cancel()
        await asyncio.sleep(0)
        assert owner.agents.guard.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        await asyncio.sleep(0.02)
        assert not owner.agents.guard.locked()
        assert any(job.workflow == "cancelled-tab" and job.cancelled.is_set() for job in owner.jobs.values())

    asyncio.run(scenario())
