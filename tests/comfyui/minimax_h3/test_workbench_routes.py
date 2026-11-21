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
from PIL import Image

from src.arisu_nodes.minimax_h3 import workbench_routes
from src.arisu_nodes.minimax_h3.workbench import Workbench
from tests.support.media import make_audio

pytestmark = pytest.mark.comfyui


def test_workbench_routes_reject_untrusted_requests_and_queue_only_preparation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = Workbench(tmp_path / "user", tmp_path / "cache")
    real_status = owner.agents.status
    status = {"docker": True, "agents": {"codex": {"ready": True, "selection": {"model": "test", "effort": "medium"}}}}
    monkeypatch.setattr(owner.agents, "status", lambda *args: status)
    queued = []
    server = SimpleNamespace(routes=web.RouteTableDef(), number=0, prompt_queue=SimpleNamespace(put=queued.append), app=None)

    async def validate(identifier, graph, targets):
        assert set(graph) == {"w", "l", "v"} and targets == ["w"]
        assert graph["w"]["inputs"]["prepare_job"] in owner.jobs
        return True, None, targets, {}

    monkeypatch.setattr(workbench_routes.execution, "validate_prompt", validate)

    def execute(job):
        job.state = "complete"
        job.draft = "review me"
        owner.agents.guard.release()

    real_execute = owner.execute
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
                    "policy_revision": 7,
                    "models": [{"id": "test", "efforts": ["medium"]}],
                }

            with monkeypatch.context() as local:
                local.setattr(owner.agents, "status", real_status)
                local.setattr(shutil, "which", lambda name: "/test/docker")
                local.setattr(
                    owner.agents,
                    "command",
                    lambda args, **kwargs: (
                        json.dumps([{"Config": {"Labels": {"org.arisu.workbench.policy": "7"}}}])
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
            assert not queued and (await response.json())["prompt_id"] is None
            await asyncio.sleep(0.01)
            response = await client.get("/arisu/workbench/jobs/" + identifier)
            assert (await response.json())["draft"] == "review me"
            # Cross the whole Director HTTP/CPU/attachment/review path, replacing only the provider.
            # The planning call returns both prompts. Refinement returns one draft and preserves the neighbor.
            root = tmp_path / "media"
            root.mkdir()
            Image.new("RGB", (20, 16), "red").save(root / "prop.png")
            make_audio(root / "sound.wav")
            custom = owner.directory / "skills" / "handwritten"
            custom.mkdir(parents=True)
            (custom / "SKILL.md").write_text("Write in short sentences.")
            document = {
                "version": 1,
                "film": {
                    "brief": "# Find the red box\n\nKeep  **this**  formatting.",
                    "requirements": ["Open the box"],
                    "triggers": "brass lock",
                    "continuity": "Morning light.",
                },
                "assets": [{"id": "box", "kind": "image", "root": "input", "path": "prop.png", "muted": False, "note": "The brass lock"}],
                "segments": [],
                "selected": "",
            }
            document["assets"].append(
                {"id": "chime", "kind": "audio", "root": "input", "path": "sound.wav", "muted": False, "clip": {"start": 0, "end": 1}}
            )
            segments = [
                {
                    "id": "arrival",
                    "intent": "Introduce the room",
                    "opening": "Morning",
                    "closing": "Paused at a desk",
                    "seconds": 8,
                    "transition": "cut",
                    "overlap_frames": 0,
                    "prompt": "Walk into the room.",
                    "bindings": [],
                    "skill": "bundled:no-ref",
                    "skill_reason": "Original establishing shot.",
                    "skill_locked": False,
                },
                {
                    "id": "opening",
                    "intent": "Open the box",
                    "opening": "Paused at a desk",
                    "closing": "An open box",
                    "seconds": 6,
                    "transition": "continuation",
                    "overlap_frames": 22,
                    "prompt": "The lock on <Picture 1> opens.",
                    "bindings": [{"asset_id": "box", "role": "image"}],
                    "skill": "bundled:with-ref",
                    "skill_reason": "Match the lock.",
                    "skill_locked": False,
                },
            ]
            plan = {
                "version": 1,
                "segments": segments,
                "outline": "Arrive and open the box.",
                "continuity": "Morning light.",
                "coverage": {"Show the opening of the red box": ["opening"]},
            }
            calls = []

            def generate_director(agent: str, directory: Path, skill: Path, *_args: Any) -> str:
                context = json.loads((directory / "context.json").read_bytes())
                task = context["director"]
                calls.append(task["task"])
                assert set(task["film"]).isdisjoint({"requirements", "triggers", "continuity"})
                assert context["requirements"] == ""
                assert context["assets"][0]["note"] == "The brass lock" and "root" not in task["library"][0]
                assert (directory / context["assets"][0]["file"]).is_file()
                catalog = {row["id"]: row for row in task["writing_skills"]}
                assert all((skill / row["path"]).is_file() for row in catalog.values())
                if task["task"] == "plan":
                    assert task["film"]["brief"] == (
                        "# Find the red box\n\nKeep  **this**  formatting.\n\nRequired story elements:\nOpen the box"
                        "\n\nTrigger words:\nbrass lock\n\nContinuity:\nMorning light."
                    )
                    assert set(catalog) == {"bundled:no-ref", "bundled:with-ref"}
                    return "```text\n" + json.dumps(plan) + "\n```"
                assert task["selected"] == "opening" and task["segments"][0]["id"] == "arrival"
                assert task["film"]["brief"] == document["film"]["brief"] and task["coverage"] == plan["coverage"]
                assert set(catalog) == {"custom:handwritten"} and not context["motion"]["present"]
                if task["request"] == "more":
                    return "x" * (256 * 1024 + 33)
                replacement = {**segments[1], "prompt": "Open <Picture:box> slowly.", "skill": "custom:handwritten"}
                if task["request"] == "zoom":
                    crop = {"left": 0, "top": 0, "width": 1000, "height": 1000}
                    replacement["bindings"] = [{**replacement["bindings"][0], "crop": crop}]
                if task["request"] == "long chime":
                    replacement["bindings"] = [
                        *replacement["bindings"],
                        {"asset_id": "chime", "role": "audio", "clip": {"start": 0, "end": 120}},
                    ]
                return "```text\n" + json.dumps({"version": 1, "segment": replacement, "suggestions": ["Hold on the desk."]}) + "\n```"

            async def director_job(task: str, note: str) -> Dict[str, Any]:
                value = {
                    "node_id": "d",
                    "workflow": "director",
                    "director": {"task": task, "request": note},
                    "options": {"motion_enabled": False, "requirements": "Stale Prompt Workbench input"},
                    "prompt": {"d": {"class_type": "ArisuMiniMaxH3DirectorWorkbench", "inputs": {"film_json": json.dumps(document)}}},
                }
                accepted = await client.post("/arisu/workbench/generate", json=value)
                assert accepted.status == 202, await accepted.text()
                pending = await accepted.json()
                assert pending["prompt_id"] is None
                for _ in range(250):
                    result = await (await client.get("/arisu/workbench/jobs/" + pending["id"])).json()
                    if result["state"] in ("complete", "failed", "cancelled") and not owner.agents.guard.locked():
                        return result
                    await asyncio.sleep(0.04)
                raise AssertionError("Director task did not finish")

            with monkeypatch.context() as local:
                local.setattr(owner, "execute", real_execute)
                local.setattr(workbench_routes, "image_roots", lambda *args: {"input": str(root)})
                local.setattr(owner.agents, "generate", generate_director)
                plan["coverage"]["Keep the morning light"] = ["missing"]
                invalid = await director_job("plan", "")
                assert invalid["state"] == "failed" and "unknown segment in coverage" in invalid["error"] and not invalid["draft"]
                plan["coverage"]["Keep the morning light"] = ["arrival", "opening"]
                result = await director_job("plan", "")
                assert result["state"] == "complete", result["error"]
                draft = json.loads(result["draft"])
                assert len(draft["segments"]) == 2 and draft["segments"][1]["prompt"] == "The lock on <Picture:box> opens."
                assert draft["coverage"] == plan["coverage"] and not document["segments"]
                document["film"] = {"brief": "## Sound\n\nA bell rings throughout the film.\n"}
                document.update({key: draft[key] for key in ("segments", "outline", "continuity", "coverage")}, selected="opening")
                document["segments"][1].update(skill="custom:handwritten", skill_locked=True)
                result = await director_job("refine", "Slow the action")
                assert result["state"] == "complete", result["error"]
                assert result["director_tail_frames"] is False
                assert json.loads(result["draft"])["segment"]["id"] == "opening" and document["segments"][0] == segments[0]
                result = await director_job("refine", "more")
                assert result["state"] == "failed" and "budget" in result["error"] and not result["draft"]
                result = await director_job("refine", "zoom")
                assert result["state"] == "failed" and "Segment opening" in result["error"] and "asset box" in result["error"]
                assert not result["draft"] and document["segments"][1]["bindings"] == segments[1]["bindings"]
                result = await director_job("refine", "long chime")
                assert result["state"] == "failed" and "asset chime" in result["error"] and not result["draft"]
                assert calls == ["plan", "plan", "refine", "refine", "refine", "refine"] and not queued
            # Real operations still refuse concurrent generation immediately.
            owner.agents.guard.acquire()
            try:
                response = await client.post(
                    "/arisu/workbench/generate", json={"node_id": "w", "workflow": "other", "prompt": graph, "options": {}}
                )
                assert response.status == 409 and not queued
            finally:
                owner.agents.guard.release()
            # Disabled motion ignores even unsupported wired producers and never enters the queue.
            graph["w"]["inputs"].update(context_latent=["s", 0], vae=["s", 0])
            response = await client.post(
                "/arisu/workbench/generate",
                json={"node_id": "w", "workflow": "disabled", "prompt": graph, "options": {"motion_enabled": False}},
            )
            assert response.status == 202 and (await response.json())["prompt_id"] is None and not queued
            await asyncio.sleep(0.01)
            # Enabled motion submits only the allowlisted motion dependencies.
            graph["w"]["inputs"].update(context_latent=["l", 0], vae=["v", 0])
            graph["l"] = {"class_type": "MiniMaxH3MotionContextLoadLatent", "inputs": {"clip_index": 1, "latent_path": "context"}}
            graph["v"] = {"class_type": "VAELoader", "inputs": {"vae_name": "test"}}
            registered = []
            monkeypatch.setattr(workbench_routes.workbench_execution, "vae_identity", lambda job: "test-revision")
            monkeypatch.setattr(workbench_routes.workbench_execution, "register", lambda *args: registered.append(args))
            response = await client.post(
                "/arisu/workbench/generate", json={"node_id": "w", "workflow": "motion", "prompt": graph, "options": {}}
            )
            assert response.status == 202 and (await response.json())["prompt_id"]
            assert len(queued) == 1 and set(queued[0][2]) == {"w", "l", "v"}
            assert registered[0][2] is queued[0][2]
            await asyncio.sleep(0.01)
            # Queue tracking cannot mistake a running video for completion of this job.
            server.prompt_queue.get_current_queue = lambda: ([queued[0]], [])
            server.prompt_queue.delete_queue_item = lambda predicate: None
            assert not registered[0][1].queue_finished()
            server.prompt_queue.get_current_queue = lambda: ([], [])
            assert registered[0][1].queue_finished()
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
