"""HTTP regression for explicit Workbench actions and preparation admission."""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from src.arisu_nodes.common.paths import CONFIG_NAME, CONFIG_TEMPLATE, read_configuration
from src.arisu_nodes.minimax_h3 import workbench_routes
from src.arisu_nodes.minimax_h3.agent_docker import IMAGE_SOURCE_LABEL, POLICY_REVISION, image_source_digest
from src.arisu_nodes.minimax_h3.workbench import Generation, Workbench
from tests.support.media import make_audio, make_video

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
            entered, finish = threading.Event(), threading.Event()

            def inspect_agent(*args: Any) -> Dict[str, Any]:
                entered.set()
                assert finish.wait(5)
                return {
                    "authenticated": True,
                    "policy_ready": True,
                    "policy_revision": POLICY_REVISION,
                    "models": [{"id": "test", "efforts": ["medium"]}],
                }

            with monkeypatch.context() as local:
                local.setattr(owner.agents, "status", real_status)
                local.setattr(shutil, "which", lambda name: "/test/docker")
                labels = {"org.arisu.workbench.policy": str(POLICY_REVISION)}
                local.setattr(
                    owner.agents,
                    "command",
                    lambda args, **kwargs: json.dumps([{"Config": {"Labels": labels}}]) if args[:2] == ["image", "inspect"] else "linux",
                )
                local.setattr(owner.agents, "owned", lambda kind, name: name in (owner.agents.image("codex"), owner.agents.volume("codex")))
                # A previously installed image has the current policy but no fingerprint.
                # Both settings and direct callers get the same recovery action before a job exists.
                local.setattr(owner.agents, "invoke", lambda *args: pytest.fail("legacy image executed"))
                outdated = await (await client.get("/arisu/workbench/status")).json()
                provider = outdated["agents"]["codex"]
                assert provider["installed"] and provider["update_required"] and not provider["ready"]
                assert "Codex" in provider["error"] and "Update CLI" in provider["error"]
                for cached in (outdated, status):
                    # Even a recent successful discovery cannot authorize a stale image at admission.
                    owner.agents._status = cached
                    response = await client.post(
                        "/arisu/workbench/generate", json={"node_id": "w", "workflow": "tab", "prompt": graph, "options": {}}
                    )
                    assert response.status == 400 and (await response.json())["error"] == provider["error"]
                    assert not owner.jobs and not queued and not owner.temp.exists() and not owner.agents.guard.locked()

                # A readiness probe after the update must delay the first click, not reject it as busy.
                labels[IMAGE_SOURCE_LABEL] = image_source_digest("codex")
                owner.agents._checked = 0
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
            monkeypatch.setattr(owner.agents, "require_current_image", lambda agent: None)
            assert response.status == 202
            identifier = (await response.json())["id"]
            assert not queued and (await response.json())["prompt_id"] is None
            await asyncio.sleep(0.01)
            response = await client.get("/arisu/workbench/jobs/" + identifier)
            assert (await response.json())["draft"] == "review me"
            # Both nodes use the settings action and capture the provider selection at admission.
            owner.directory.mkdir()
            (owner.directory / CONFIG_NAME).write_text(CONFIG_TEMPLATE)
            with monkeypatch.context() as local:
                model = {"id": "test", "efforts": ["medium"], "context_windows": [256000, 500000], "default_context_window": 256000}
                local.setattr(owner.agents, "status", real_status)
                local.setattr(shutil, "which", lambda name: "/test/docker")
                local.setattr(owner.agents, "command", lambda *args, **kwargs: "linux")
                local.setattr(owner.agents, "owned", lambda *args: True)
                catalogue = {"authenticated": True, "policy_ready": True, "policy_revision": POLICY_REVISION, "models": [model]}
                local.setattr(owner.agents, "invoke", lambda *args: catalogue)
                legacy = real_status(refresh=True)["agents"]["grok"]["selection"]
                assert legacy == {"model": "test", "effort": "medium"}
                configure = {"agent": "grok", "action": "configure", **legacy}
                action = "/arisu/workbench/action"
                assert (await client.post(action, json={**configure, "context_window": 500000})).status == 200
                assert read_configuration(owner.directory)["workbench"]["grok"]["context_window"] == 500000
                for agent, invalid in (("grok", 128000), ("grok", "500000"), ("grok", 500000.0), ("grok", True), ("codex", 500000)):
                    assert (await client.post(action, json={**configure, "agent": agent, "context_window": invalid})).status == 400
                pending = await client.post(
                    "/arisu/workbench/generate",
                    json={"node_id": "w", "workflow": "grok-tab", "prompt": graph, "options": {"agent": "grok"}},
                )
                assert pending.status == 202
                job = owner.get((await pending.json())["id"])
                assert job.selection["context_window"] == 500000
                assert await asyncio.to_thread(owner.agents.guard.acquire, True, 5)
                owner.agents.guard.release()
                model["context_windows"] = [256000]
                assert real_status(refresh=True)["agents"]["grok"]["selection"] == legacy
                assert (await client.post(action, json={**configure, "context_window": None})).status == 200
                model["context_windows"] = [256000, 500000]
                assert real_status(refresh=True)["agents"]["grok"]["selection"] == legacy
                assert read_configuration(owner.directory)["workbench"]["grok"]["context_window"] is None
                assert job.selection["context_window"] == 500000
            # Cross the whole Director HTTP/CPU/attachment/review path, replacing only the provider.
            # The planning call returns both prompts. Refinement returns one draft and preserves the neighbor.
            root = tmp_path / "media"
            root.mkdir()
            Image.new("RGB", (20, 16), "red").save(root / "prop.png")
            make_audio(root / "sound.wav")
            make_video(root / "pan.mkv")
            video_id = "57ee5edb-dac7-4290-aeea-22c86896dbdd"
            custom = owner.directory / "skills" / "handwritten"
            custom.mkdir(parents=True)
            (custom / "SKILL.md").write_text("Write in short sentences.")
            document = {
                "version": 1,
                "film": {
                    "brief": "# Find the red box\n\nKeep  **this**  formatting.",
                    "target_runtime": "2 min",
                    "requirements": ["Open the box"],
                    "triggers": "brass lock",
                    "continuity": "Morning light.",
                },
                "assets": [{"id": "box", "kind": "image", "root": "input", "path": "prop.png", "muted": False, "note": "The brass lock"}],
                "segments": [],
                "selected": "",
            }
            document["assets"].extend(
                [
                    {"id": "motion", "kind": "audio", "root": "input", "path": "sound.wav", "clip": {"start": 0, "end": 1}},
                    {
                        "id": video_id,
                        "kind": "video",
                        "root": "input",
                        "path": "pan.mkv",
                        "include_audio": True,
                        "clip": {"start": 0, "end": 1},
                    },
                    {"id": "unused", "kind": "image", "root": "input", "path": "never-opened.png", "muted": True},
                ]
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
                    "prompt": f"The lock on <Picture 1> opens.\u2028Hold <Picture:box> during <Video:{video_id}>.",
                    "bindings": [{"asset_id": "box", "role": "first"}, {"asset_id": video_id, "role": "video"}],
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
                assert {row["id"] for row in task["library"]} == {row["id"] for row in document["assets"] if not row.get("muted")}
                assert (directory / context["assets"][0]["file"]).is_file()
                catalog = {row["id"]: row for row in task["writing_skills"]}
                assert all((skill / row["path"]).is_file() for row in catalog.values())
                if task["task"] == "plan":
                    assert task["film"]["target_runtime"] == "2 min"
                    assert task["film"]["brief"] == (
                        "# Find the red box\n\nKeep  **this**  formatting.\n\nRequired story elements:\nOpen the box"
                        "\n\nTrigger words:\nbrass lock\n\nContinuity:\nMorning light."
                    )
                    assert set(catalog) == {"bundled:no-ref", "bundled:with-ref"}
                    for rows in (task["library"], context["references"]):
                        assert not next(row for row in rows if row["id"] == video_id)["include_audio"]
                    # The provider copies image and video still IDs from its attachments. Those
                    # identify exact sources only within this job; the saved draft needs stable IDs.
                    attachments = {asset["resource_id"]: asset["id"] for asset in context["assets"]}
                    assert attachments["box"] != "box" and attachments[video_id] != video_id
                    response = deepcopy(plan)
                    for scene in response["segments"]:
                        scene["bindings"] = [{**b, "asset_id": attachments[b["asset_id"]]} for b in scene["bindings"]]
                        scene["prompt"] = scene["prompt"].replace("<Picture:box>", f"<Picture:{attachments['box']}>")
                        scene["prompt"] = scene["prompt"].replace(video_id, video_id.replace("-", "").upper())
                    return "```json \t\r\n" + json.dumps(response, ensure_ascii=False) + "\r\n```"
                assert task["selected"] == "opening" and task["segments"][0]["id"] == "arrival"
                assert task["film"]["brief"] == document["film"]["brief"] and task["coverage"] == plan["coverage"]
                assert set(catalog) == {"custom:handwritten"}
                assert context["motion"]["present"] == (task["request"] == "bind the tail")
                if task["request"] == "more":
                    return "x" * (256 * 1024 + 33)
                replacement = {**segments[1], "prompt": "Open <Picture:box> slowly.", "skill": "custom:handwritten"}
                if task["request"] == "Slow the action":
                    preview = context["keyframes"]["first"]["asset_id"]
                    replacement.update(
                        seconds=9, bindings=[{"asset_id": preview, "role": "image"}], prompt=f"Open <Picture:{preview}> slowly."
                    )
                if task["request"] == "zoom":
                    crop = {"left": 0, "top": 0, "width": 1000, "height": 1000}
                    replacement["bindings"] = [{**replacement["bindings"][0], "crop": crop}]
                if task["request"] == "long chime":
                    replacement["bindings"] = [
                        *replacement["bindings"],
                        {"asset_id": "motion", "role": "audio", "clip": {"start": 0, "end": 120}},
                    ]
                if task["request"] in ("unknown", "unused", "bind the tail"):
                    identifier = context["motion"]["stills"][0]["asset_id"] if task["request"] == "bind the tail" else task["request"]
                    role = "image" if task["request"] == "unused" else "audio"
                    replacement.update(bindings=[{"asset_id": identifier, "role": role}], prompt="The bell rings.")
                if task["request"] == "repeat the video":
                    frames = next(row for row in context["references"] if row["id"] == video_id)["inspect"]["frames"]
                    replacement.update(bindings=[{"asset_id": frame["asset_id"], "role": "video"} for frame in frames[:2]], prompt="Pan.")
                if task["request"] == "ambiguous video":
                    replacement.update(bindings=[{"asset_id": video_id.replace("-", "").upper(), "role": "video"}], prompt="Pan.")
                if task["request"] == "replace source":
                    Image.new("RGB", (20, 16), "blue").save(root / "replacement.png")
                    (root / "replacement.png").replace(root / "prop.png")
                return "```json\n" + json.dumps({"version": 1, "segment": replacement, "suggestions": ["Hold on the desk."]}) + "\n```"

            async def director_job(task: str, note: str) -> Dict[str, Any]:
                value = {
                    "node_id": "d",
                    "workflow": "director",
                    "director": {"task": task, "request": note},
                    "options": {"motion_enabled": note == "bind the tail", "requirements": "Stale Prompt Workbench input"},
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

                def execute_with_prepared_tail(job: Generation):
                    if job.director.request == "bind the tail":
                        # Supply the decoded predecessor frames at the preparation boundary.
                        owner.cache_motion(job, "test-tail", [Image.new("RGB", (16, 12), "blue")])
                    real_execute(job)

                local.setattr(owner, "execute", execute_with_prepared_tail)
                local.setattr(workbench_routes, "image_roots", lambda *args: {"input": str(root)})
                local.setattr(owner.agents, "generate", generate_director)
                plan["coverage"]["Keep the morning light"] = ["missing"]
                invalid = await director_job("plan", "")
                assert invalid["state"] == "failed" and "unknown segment in coverage" in invalid["error"] and not invalid["draft"]
                plan["coverage"]["Keep the morning light"] = ["arrival", "opening"]
                result = await director_job("plan", "")
                assert result["state"] == "complete", result["error"]
                draft = json.loads(result["draft"])
                # The same runtime target admits both this short sequence and the longer film below.
                assert [s["seconds"] for s in draft["segments"]] == [8, 6]
                assert draft["segments"][1]["prompt"] == segments[1]["prompt"].replace("<Picture 1>", "<Picture:box>")
                assert draft["segments"][1]["bindings"] == segments[1]["bindings"]
                assert draft["coverage"] == plan["coverage"] and not document["segments"]
                # The film has its own budget: twenty individually short prompts
                # can exceed 7000 characters in total without truncation or refusal.
                long_prompt = "The camera crosses the quiet room. " * 170
                plan["segments"] = [
                    {**segments[i % 2], "id": segments[i]["id"] if i < 2 else f"scene-{i}", "prompt": long_prompt} for i in range(20)
                ]
                long_result = await director_job("plan", "")
                assert long_result["state"] == "complete", long_result["error"]
                long_draft = json.loads(long_result["draft"])
                assert [s["seconds"] for s in long_draft["segments"]] == [8, 6] * 10
                assert all(s["prompt"] == long_prompt for s in long_draft["segments"])
                # UTF-8 size, not the sum of prompt character counts, bounds the JSON.
                # Each prompt remains below 7000 characters, but this film is too large.
                for segment in plan["segments"]:
                    segment["prompt"] = "镜头缓慢移动。" * 850
                oversized = await director_job("plan", "")
                assert oversized["state"] == "failed" and "budget" in oversized["error"] and not oversized["draft"]
                assert not document["segments"]
                plan["segments"] = segments
                document["film"] = {"brief": "## Sound\n\nA bell rings throughout the film.\n"}
                document.update({key: draft[key] for key in ("segments", "outline", "continuity", "coverage")}, selected="opening")
                document["segments"][1].update(skill="custom:handwritten", skill_locked=True)
                result = await director_job("refine", "Slow the action")
                assert result["state"] == "complete", result["error"]
                assert result["director_tail_frames"] is False
                replacement = json.loads(result["draft"])["segment"]
                assert replacement["id"] == "opening" and replacement["seconds"] == 9 and document["segments"][0] == segments[0]
                assert (
                    replacement["bindings"] == [{"asset_id": "box", "role": "image"}]
                    and replacement["prompt"] == "Open <Picture:box> slowly."
                )
                result = await director_job("refine", "more")
                assert result["state"] == "failed" and "budget" in result["error"] and not result["draft"]
                result = await director_job("refine", "zoom")
                assert result["state"] == "failed" and "Segment opening" in result["error"] and "asset box" in result["error"]
                assert not result["draft"] and document["segments"][1]["bindings"] == segments[1]["bindings"]
                result = await director_job("refine", "long chime")
                assert result["state"] == "failed" and "asset motion" in result["error"] and not result["draft"]
                # Even a library asset named "motion" does not own a predecessor still.
                # An alternate UUID spelling can identify two saved IDs of different kinds.
                # Selecting the only video would silently guess which source the provider meant.
                document["assets"].append({**document["assets"][1], "id": video_id.replace("-", "")})
                for refused, reason in (
                    ("unknown", "missing"),
                    ("unused", "muted"),
                    ("bind the tail", "missing"),
                    ("repeat the video", "more than once"),
                    ("ambiguous video", "ambiguous"),
                ):
                    result = await director_job("refine", refused)
                    assert (
                        result["state"] == "failed"
                        and "Segment opening" in result["error"]
                        and reason in result["error"]
                        and not result["draft"]
                    ), result
                    if refused == "unused":
                        assert "never-opened.png" in result["error"]
                # A legacy film can omit saved revisions. Review still refers to the
                # media staged before generation, including when the file was replaced.
                submitted = deepcopy(document)
                result = await director_job("refine", "replace source")
                assert result["state"] == "failed" and "asset box" in result["error"] and not result["draft"]
                assert document == submitted
                assert calls == ["plan"] * 4 + ["refine"] * 10 and not queued
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
