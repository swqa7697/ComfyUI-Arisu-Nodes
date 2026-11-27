"""Isolated real-frontend host with synthetic API state and browser diagnostics."""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.resources
import io
import json
import re
import signal
import threading
import uuid
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from aiohttp import web
from PIL import Image, ImageDraw
from playwright.sync_api import Browser, ConsoleMessage, Error, Page, Route, WebSocketRoute, sync_playwright

from assets.prompt_workbench.events import activity

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/browser/fixtures"
ARTIFACTS = ROOT / ".misc/browser/results"
STUDIO = "ArisuMiniMaxH3ResourceStudio"
WORKBENCH = "ArisuMiniMaxH3PromptWorkbench"
DRAFT = "A paper boat drifts across a sunlit pond. The camera follows slowly."
ASSEMBLY = "ArisuAssembleVideo"
PROJECT = "films/night shoot"
# Published takes of the fixture project, by file name.
TAKES = {
    "shot_00001_.mp4": "11111111-1111-4111-8111-111111111111",
    "shot_00002_.mp4": "22222222-2222-4222-8222-222222222222",
    "shot_00003_.mp4": "33333333-3333-4333-8333-333333333333",
}
OUTPUT_SPEC = {"width": 1280, "height": 720, "fps": [24, 1], "sample_rate": 32000, "channels": 2}
_DIRECTED = re.compile(r"(?:.+/director|arisu_director)/([0-9a-f-]{36})/clip_\d{5,}_\.mp4")


class FixtureServer:
    """Serve only bundled assets and explicit fake API contracts on loopback."""

    def __init__(self):
        self.frontend = Path(str(importlib.resources.files("comfyui_frontend_package"))) / "static"
        self.errors: List[str] = []
        self.requests: List[str] = []
        self.available = True
        self.fail_generation = False
        self.hold_generation = False
        self.log_polls = 0
        self.polls = 0
        self.generation_requests: List[Dict[str, Any]] = []
        self.settings: Dict[str, Any] = {
            "Comfy.VueNodes.Enabled": False,
            "Comfy.UseNewMenu": "Top",
            "Comfy.TutorialCompleted": True,
            "Comfy.Notification.ShowVersionUpdates": False,
            "Comfy.Workflow.WorkflowTabsPosition": "Topbar",
        }
        self.userdata: Dict[str, bytes] = {}
        # Assemble Video: request bodies in order, deleted videos, Director renders seen, and join preview jobs.
        self.video_requests: List[Tuple[str, Any]] = []
        self.video_deleted: Set[str] = set()
        self.video_directed: Set[str] = set()
        self.previews: Dict[str, Dict[str, Any]] = {}
        # File revisions of Director takes that stay on a node after its render fixture ends.
        self.director_takes: Dict[str, Dict[str, str]] = {}
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.runner: Optional[web.AppRunner] = None
        self.url = ""
        output = io.BytesIO()
        picture = Image.new("RGB", (800, 600), "#30576b")
        draw = ImageDraw.Draw(picture)
        draw.rectangle((40, 40, 760, 560), outline="#f6d78b", width=12)
        draw.ellipse((240, 140, 560, 460), fill="#ea9b62")
        draw.text((65, 65), "ARISU BROWSER FIXTURE", fill="white", font_size=30)
        picture.save(output, format="PNG")
        self.png = output.getvalue()
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x00" * 80000)
        self.wav = output.getvalue()

    async def start(self):
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.runner = web.AppRunner(app, shutdown_timeout=0.2)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:" + str(self.runner.addresses[0][1])

    def __enter__(self) -> FixtureServer:  # noqa: PYI034 -- Python 3.10 has no typing.Self.
        self.thread.start()
        try:
            asyncio.run_coroutine_threadsafe(self.start(), self.loop).result(timeout=10)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *args: object):
        try:
            if self.runner is not None:
                asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(timeout=10)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=10)
            self.loop.close()

    def status(self) -> Dict[str, Any]:
        info = {
            "installed": True,
            "authenticated": True,
            "policy_ready": True,
            "policy_revision": 7,
            "ready": self.available,
            "version": "fixture",
            "models": [{"id": "fixture", "name": "Fixture model", "efforts": ["medium"]}],
            "selection": {"model": "fixture", "effort": "medium"},
        }
        return {
            "docker": True,
            "agents": {
                "codex": info,
                "grok": {**info, "models": [{**info["models"][0], "context_windows": [256000, 500000], "default_context_window": 256000}]},
            },
            "skills": [{"id": "bundled:with-ref", "name": "with-ref", "source": "bundled"}],
        }

    def draft(self) -> str:
        request = self.generation_requests[-1]
        if "director" not in request:
            return DRAFT
        doc = json.loads(request["prompt"][request["node_id"]]["inputs"]["film_json"])
        if request["director"]["task"] == "refine":
            segment = next(s for s in doc["segments"] if s["id"] == doc["selected"])
            return json.dumps({"version": 1, "segment": {**segment, "prompt": "The camera settles on the paper boat."}, "suggestions": []})
        segments = [
            {
                "id": key,
                "intent": intent,
                "seconds": 6,
                "transition": "cut" if key == "launch" else "continuation",
                "overlap_frames": 0 if key == "launch" else 22,
                "opening": "Sunlit pond",
                "closing": "Boat on the water",
                "prompt": prompt,
                "bindings": [],
                "skill": "bundled:no-ref",
                "skill_reason": "The scene uses written direction.",
                "skill_locked": False,
            }
            for key, intent, prompt in (
                ("launch", "Launch the paper boat", DRAFT),
                ("follow", "Follow the boat", "The boat reaches the willow."),
            )
        ]
        return json.dumps(
            {
                "version": 1,
                "outline": "A paper boat crosses the pond.",
                "continuity": "Soft morning light.",
                "coverage": {"Launch the boat": ["launch"]},
                "segments": segments,
            }
        )

    def video_description(self, root: str, path: str) -> Dict[str, Any]:
        """Describe one synthetic video in the route contract; only root IDs and relative paths appear."""
        name = path.rsplit("/", 1)[-1]
        directed = _DIRECTED.fullmatch(path) if root == "output" else None
        ordinary = root == "output" and path == f"{PROJECT}/videos/{name}" and name in TAKES
        found = root == "output" and name == "found.webm"
        if path in self.video_deleted or not (directed or ordinary or found):
            return {"root": root, "path": path, "state": "missing"}
        take = None
        if directed:
            self.video_directed.add(path)
            take = {"take": directed.group(1), "origin": "director", "segment": None, "predecessor": None, "transition": None}
        elif ordinary:
            take = {"take": TAKES[name], "origin": "ordinary", "segment": None, "predecessor": None, "transition": None}
        return {
            "root": root,
            "path": path,
            "state": "ok",
            "revision": "video-revision" if directed else "revision-" + name,
            "frames": 48,
            "fps": [24, 1],
            "duration": 2.0,
            # A plain file with another frame size makes the export check ask for a common output.
            "width": 800 if found else 1280,
            "height": 600 if found else 720,
            "codec": "vp9" if found else "h264",
            "vfr": False,
            "audio": {"rate": 32000, "channels": 2, "samples": 64000, "source": "pcm" if ordinary else "embedded"},
            "take": take,
        }

    async def handle_video(self, request: web.Request, path: str) -> Optional[web.StreamResponse]:
        """Synthetic Assemble Video routes; an unlisted route falls through and fails the scenario."""
        method, route = request.method, path.removeprefix("/arisu/video")
        if route == "/takes" and method == "GET":
            project = request.query.get("project", "")
            listed = [f"{project}/videos/{name}" for name in TAKES] if project == PROJECT else []
            if request.query.get("legacy") == "1" or project == PROJECT:
                listed += sorted(self.video_directed)
            self.video_requests.append(("takes", dict(request.query)))
            takes = [self.video_description("output", item) for item in listed]
            return web.json_response({"project": project, "takes": [take for take in takes if take["state"] == "ok"]})
        preview = re.fullmatch(r"/join-preview/([0-9a-f-]{36})(/view)?", route)
        if preview and preview.group(1) in self.previews:
            job = self.previews[preview.group(1)]
            if method == "DELETE" and not preview.group(2):
                del self.previews[preview.group(1)]
                return web.json_response({"released": True})
            if method == "GET" and preview.group(2):
                if request.query.get("variant", "a") not in job["variants"]:
                    return web.json_response({"error": "preview is not ready"}, status=409)
                return web.FileResponse(FIXTURES / "clip.webm", headers={"Content-Type": "video/webm"})
            if method == "GET":
                return web.json_response(job)
        if method != "POST" or route not in ("/describe", "/preflight", "/delete", "/join-preview"):
            return None
        body = await request.json()
        self.video_requests.append((route[1:], body))
        if route == "/describe":
            return web.json_response({"entries": [self.video_description(entry["root"], entry["path"]) for entry in body["entries"]]})
        if route == "/delete":
            results = []
            for entry in body["entries"]:
                found = self.video_description(entry["root"], entry["path"])
                revision = "review-" + found["revision"] if found["state"] == "ok" else ""
                allowed = bool(revision) and (not body["confirm"] or entry["revision"] == revision)
                files = []
                directory = None
                if allowed:
                    origin = (found["take"] or {}).get("origin")
                    if origin == "ordinary":
                        directory = entry["path"].removesuffix(".mp4") + ".arisu"
                        files.extend([(f"{directory}/take.json", 1200), (f"{directory}/audio.wav", 512044)])
                    elif origin == "director":
                        directory = entry["path"].rsplit("/", 1)[0]
                        files.append((f"{directory}/clip_00001.safetensors", 128000))
                    files.append((entry["path"], 2400000))
                if allowed and body["confirm"]:
                    self.video_deleted.add(entry["path"])
                results.append(
                    {
                        "root": entry["root"],
                        "path": entry["path"],
                        "directory": directory,
                        "revision": revision if allowed else "",
                        "state": ("deleted" if body["confirm"] else "deletable") if allowed else "refused",
                        "files": [{"path": name, "bytes": size} for name, size in files],
                        "bytes": sum(size for _, size in files),
                    }
                )
            return web.json_response({"entries": results, "bytes": sum(item["bytes"] for item in results)})
        if route == "/join-preview":
            join = body["join"]
            handle = str(uuid.uuid4())
            self.previews[handle] = {
                "state": "ready",
                "progress": 100,
                "error": None,
                "variants": ["a", "b"] if join["correction"] or join["fade"] else ["a"],
                "cut": 0.5,
                "signalling": {"match": True, "outgoing": {}, "incoming": {}},
                "suggestion": {
                    "stable": True,
                    "correction": {"luma_gain": 1.0, "luma_offset": -0.02, "cb_offset": 0.0, "cr_offset": 0.004, "taper": 24},
                },
            }
            return web.json_response({"id": handle}, status=202)
        document = body["document"]
        rows, position, states = [], 0, []
        for entry in (item for item in document["entries"] if item["included"]):
            found = self.video_description(entry["root"], entry["path"]) if entry["path"] else {"state": "missing"}
            states.append(found)
            usable = found["state"] == "ok"
            first, last = entry["range"] or (0, 48)
            count = last - first if usable else 0
            rows.append(
                {
                    "id": entry["id"],
                    "state": found["state"],
                    "frames": [position, position + count] if usable else None,
                    "samples": [position * 4000 // 3, (position + count) * 4000 // 3] if usable else None,
                    "audio": found["audio"]["source"] if usable and entry["audio"] != "none" else "none",
                    "message": None,
                }
            )
            position += count
        mixed = len({(found.get("width"), found.get("codec")) for found in states if found["state"] == "ok"}) > 1
        usable = bool(rows) and all(row["state"] == "ok" for row in rows)
        corrected = any(entry["join"]["correction"] for entry in document["entries"])
        encode = mixed or corrected or body["encoding"] == "encode"
        needs = []
        if usable and mixed and document["output"] is None:
            needs.append({"kind": "confirm_output", "entries": [row["id"] for row in rows], "suggested": OUTPUT_SPEC})
        if encode:
            reason = "a colour correction is applied" if corrected else "sources are conformed to one frame size and rate"
            video = {"operation": "encode", "reason": reason, "codec": body["codec"], "encoder": "libx264", "crf": body["crf"]}
        else:
            video = {
                "operation": "copy",
                "reason": "whole compatible segments are copied as packets",
                "codec": "h264",
                "encoder": None,
                "crf": None,
            }
        return web.json_response(
            {
                "entries": rows,
                "frames": position,
                "duration": position / 24,
                "samples": position * 4000 // 3,
                "fps": [24, 1],
                "width": 1280,
                "height": 720,
                "sample_rate": 32000,
                "channels": 2,
                "video": video,
                "audio": {"operation": "encode", "reason": "sound is rebuilt on one continuous sample timeline and encoded once"},
                "destination": f"{body['project']}/exports/{body['export_name']}_00001/{body['export_name']}_00001.mp4",
                "backend": "ffmpeg",
                "needs": needs,
                "warnings": [],
                "ready": usable and not needs,
            }
        )

    async def handle(self, request: web.Request) -> web.StreamResponse:
        path = request.path.removeprefix("/api") if request.path.startswith("/api/") else request.path
        method = request.method
        self.requests.append(f"{method} {request.path}")
        if path == "/ws":
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            await socket.send_json({"type": "status", "data": {"sid": "browser-fixture", "status": {"exec_info": {"queue_remaining": 0}}}})
            async for _ in socket:
                pass
            return socket
        if path in ("/user.css", "/userdata/user.css"):
            return web.Response(text="", content_type="text/css")
        if path == "/extensions":
            return web.json_response(
                ["/extensions/arisu/" + p.relative_to(ROOT / "web").as_posix() for p in sorted((ROOT / "web/js").rglob("*.js"))]
            )
        if path == "/object_info":
            definitions = json.loads((FIXTURES / "object_info.json").read_text())
            # Portable schema fixtures contain no host inventory. These names are
            # synthetic browser choices; no checkpoint endpoint serves their bytes.
            loader = definitions["ArisuMiniMaxH3ModelLoader"]["input"]["required"]
            models = ["base.safetensors", "overlay.safetensors"]
            loader["base_model"][1]["options"] = models
            loader["mode"][1]["options"][1]["inputs"]["required"]["overlay_model"][1]["options"] = models
            return web.json_response(definitions)
        if path == "/settings":
            if method == "POST":
                self.settings.update(await request.json())
            return web.json_response(self.settings)
        if path.startswith("/settings/") and method == "POST":
            self.settings[path.removeprefix("/settings/")] = await request.json()
            return web.json_response({})
        if path == "/users":
            return web.json_response({"storage": "server", "migrated": True})
        if path == "/userdata":
            return web.json_response([])
        if path.startswith("/userdata/"):
            if method == "POST":
                self.userdata[path] = await request.read()
            if method == "DELETE":
                self.userdata.pop(path, None)
            return web.Response(body=self.userdata.get(path, b"{}"), content_type="application/json")
        responses = {
            "/queue": {"queue_running": [], "queue_pending": []},
            "/history": {},
            "/prompt": {"exec_info": {"queue_remaining": 0}},
            "/embeddings": [],
            "/models": [],
            "/internal/folder_paths": {},
            "/experiment/models": [],
            "/features": {},
            "/i18n": {},
            "/global_subgraphs": {},
            "/jobs": {"jobs": [], "pagination": {"offset": 0, "limit": 200, "total": 0, "has_more": False}},
            "/system_stats": {
                "system": {
                    "comfyui_version": "fixture",
                    "python_version": "fixture",
                    "os": "linux",
                    "embedded_python": False,
                    "argv": [],
                    "ram_total": 0,
                    "ram_free": 0,
                },
                "devices": [],
            },
            "/arisu/roots": {"roots": [{"id": "input", "label": "Input"}, {"id": "output", "label": "Output"}]},
        }
        if path in responses and method == "GET":
            return web.json_response(responses[path])
        if path == "/arisu/workbench/logs":
            self.log_polls += 1
            job = request.query.get("job", "")
            lines = (
                [
                    activity(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "thought",
                                "type": "reasoning",
                                "text": "Inspecting the selected reference, motion and lighting. " * 200,
                            },
                        },
                        "codex",
                    ),
                    activity(
                        {
                            "type": "item.started",
                            "item": {"id": "context", "type": "mcp_tool_call", "server": "workbench", "tool": "get_context"},
                        },
                        "codex",
                    ),
                    activity(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "context",
                                "type": "mcp_tool_call",
                                "server": "workbench",
                                "tool": "get_context",
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": json.dumps(
                                                {
                                                    "references": [
                                                        {"id": i, "notes": "Synthetic reference details " * 20} for i in range(20)
                                                    ]
                                                },
                                                indent=2,
                                            ),
                                        }
                                    ]
                                },
                            },
                        },
                        "codex",
                    ),
                    activity(
                        {
                            "type": "assistant",
                            "message": {
                                "id": "grok-thought",
                                "content": [{"type": "thinking", "thinking": "Preserve the folded silhouette."}],
                            },
                        },
                        "grok",
                    ),
                    activity(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "skill",
                                "type": "mcp_tool_call",
                                "server": "workbench",
                                "tool": "read_skill",
                                "arguments": {"path": "SKILL.md"},
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": '# Skill\n[analysis] Hidden file content\n{"metadata": "inside the loaded file"}',
                                        },
                                        {"type": "image", "data": "private-image-bytes"},
                                    ]
                                },
                            },
                        },
                        "codex",
                    ),
                    activity(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "answer",
                                "type": "agent_message",
                                "text": "```markdown\n" + DRAFT + "\n```",
                            },
                        },
                        "codex",
                    ),
                ]
                if job
                else ["[codex] build", "#1 [internal] load build definition from Dockerfile", "#2 resolve base image", "#3 DONE 0.4s"]
            )
            lines += [f"#4 Processing {'reference' if job else 'image build'} step {i + 1}" for i in range(65)]
            if not job:
                lines += ["Sign in at https://example.test/device", "Device code: ABCD-EFGH", "Waiting for browser authorization…"]
            if job:
                lines += [
                    activity(
                        {"type": "item.completed", "item": {"id": f"live-{i}", "type": "reasoning", "text": f"Live update {i + 1}"}},
                        "codex",
                    )
                    for i in range(self.log_polls)
                ]
            session = "fixture-generation" if job else "fixture-management"
            cursor = int(request.query.get("cursor", "0")) if request.query.get("session") == session else 0
            return web.json_response(
                {
                    "session": session,
                    "agent": "codex",
                    "action": "generate" if job else "login",
                    "job": job,
                    "state": "running",
                    "lines": lines[cursor:],
                    "cursor": len(lines),
                    "more": False,
                }
            )
        if path == "/arisu/workbench/status":
            return web.json_response(self.status())
        if path == "/arisu/workbench/generate" and method == "POST":
            self.polls = 0
            self.generation_requests.append(await request.json())
            return web.json_response({"id": "fixture-job"})
        if path == "/arisu/workbench/jobs/fixture-job":
            self.polls += 1
            if self.fail_generation:
                return web.json_response({"state": "failed", "error": "Simulated provider unavailable", "generation_elapsed_ms": 12500})
            if self.hold_generation or self.polls < 3:
                return web.json_response({"state": "generating", "generation_elapsed_ms": 42000})
            completed = {"state": "complete", "draft": self.draft(), "generation_elapsed_ms": 78000}
            generation = self.generation_requests[-1]
            if generation.get("director", {}).get("task") == "refine":
                completed["director_tail_frames"] = "predecessor" in generation["director"]
            return web.json_response(completed)
        if path in ("/arisu/workbench/release", "/arisu/workbench/cancel", "/arisu/workbench/action") and method == "POST":
            return web.json_response({"accepted": True})
        if path == "/arisu/resources/director-take" and request.query.get("take") in self.director_takes:
            return web.json_response(self.director_takes[request.query["take"]])
        if path.startswith("/arisu/video/"):
            answer = await self.handle_video(request, path)
            if answer is not None:
                return answer
        if path == "/arisu/resources/browse" and request.query.get("root") == "output":
            # The output root holds one video beside an image, so a video-only Browse has something to hide.
            return web.json_response(
                {
                    "root": "output",
                    "path": "",
                    "parent": None,
                    "dirs": [],
                    "files": ["found.webm", "scene.png"],
                    "ancestors": [],
                    "roots": responses["/arisu/roots"]["roots"],
                    "kinds": {"found.webm": "video", "scene.png": "image"},
                }
            )
        if path in ("/arisu/resources/browse", "/arisu/browse"):
            return web.json_response(
                {
                    "root": request.query.get("root", "input"),
                    "path": "",
                    "parent": None,
                    "dirs": [],
                    "files": ["scene.png"]
                    + (["sound.wav"] if path == "/arisu/resources/browse" else [])
                    + [f"scene-{i}.png" for i in range(2, 10)],
                    "ancestors": [],
                    "roots": responses["/arisu/roots"]["roots"],
                    "kinds": {"scene.png": "image", "sound.wav": "audio", **{f"scene-{i}.png": "image" for i in range(2, 10)}},
                }
            )
        if path == "/arisu/resources/view" and request.query.get("path", "").endswith((".webm", ".mp4")):
            return web.FileResponse(FIXTURES / "clip.webm", headers={"Content-Type": "video/webm"})
        if path == "/arisu/resources/metadata":
            name = request.query.get("path", "")
            kind = "audio" if name.endswith(".wav") else "video" if name.endswith((".webm", ".mp4")) else "image"
            return web.json_response(
                {
                    "kind": kind,
                    "width": 800,
                    "height": 600,
                    "duration": 10,
                    "has_audio": True,
                    "revision": "fixture-v1",
                    "fps": 24,
                    "rate": 8000,
                    "size": 160044,
                }
            )
        if path in ("/arisu/view", "/arisu/resources/view", "/arisu/resources/poster"):
            audio = request.query.get("path", "").endswith(".wav") and path.endswith("/view")
            if audio:
                return web.Response(body=self.wav, content_type="audio/wav")
            if "crop" in request.query or "max" in request.query:
                with Image.open(io.BytesIO(self.png)) as image:
                    if "crop" in request.query:
                        left, top, width, height = map(int, request.query["crop"].split(","))
                        image = image.crop((left, top, left + width, top + height))
                    if "max" in request.query:
                        maximum = max(1, min(800, int(request.query["max"])))
                        image.thumbnail((maximum, maximum))
                    output = io.BytesIO()
                    image.save(output, format="PNG")
                    return web.Response(body=output.getvalue(), content_type="image/png")
            return web.Response(body=self.png, content_type="image/png")
        if method == "GET":
            base = ROOT / "web" if path.startswith("/extensions/arisu/") else self.frontend
            relative = path.removeprefix("/extensions/arisu/") if base == ROOT / "web" else path.lstrip("/") or "index.html"
            target = (base / relative).resolve()
            if target.is_relative_to(base.resolve()) and target.is_file():
                return web.FileResponse(target)
        self.errors.append(f"Unexpected request: {method} {request.path_qs}")
        return web.json_response({"error": "No browser fixture for this request"}, status=404)


@contextmanager
def browser_page(browser: Browser, server: FixtureServer, name: str, width: int = 1440, height: int = 900) -> Iterator[Page]:
    """Keep each scenario's browser state and diagnostic files independent."""
    output = ARTIFACTS / name
    output.mkdir(parents=True, exist_ok=True)
    for previous in output.iterdir():
        if previous.suffix in (".png", ".json", ".zip") and previous.is_file():
            previous.unlink()
    context = browser.new_context(
        viewport={"width": width, "height": height}, device_scale_factor=1, reduced_motion="reduce", service_workers="block"
    )
    errors: List[str] = []
    startup_diagnostics: List[str] = []
    failure = None

    def route_request(route: Route):
        if route.request.url.startswith(server.url + "/"):
            route.continue_()
        elif route.request.method == "GET" and route.request.url == "https://cloud.comfy.org/api/features":
            # Recent local frontends read their Open on Cloud rollout on startup. Fulfill it entirely in the fixture.
            route.fulfill(json={"open_on_cloud_enabled": False})
        else:
            errors.append("Blocked external request: " + route.request.url)
            route.abort()

    def route_socket(socket: WebSocketRoute):
        if socket.url.split("?", 1)[0] == server.url.replace("http:", "ws:") + "/ws":
            socket.connect_to_server()
        else:
            errors.append("Blocked external WebSocket: " + socket.url)
            # Leaving the route unconnected keeps it mocked: no host connection is opened.

    context.route("**/*", route_request)
    context.route_web_socket("**/*", route_socket)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_message(message: ConsoleMessage):
        # Frontend 1.52.7's own reactive store reads rootGraph before setup.
        # Keep this exact startup diagnostic visible; never suppress page exceptions.
        if message.text == "ComfyApp graph accessed before initialization" and "/assets/settingStore-" in message.location.get("url", ""):
            startup_diagnostics.append(message.text)
        elif message.type == "error":
            errors.append(message.text)

    page.on("console", console_message)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    try:
        page.goto(server.url)
        page.wait_for_function("!!window.LiteGraph?.registered_node_types.ArisuMiniMaxH3ResourceStudio", timeout=30000)
        page.locator("#graph-canvas").wait_for()
        yield page
        assert not errors + server.errors, "\n".join(errors + server.errors)
    except BaseException as error:
        failure = str(error)
        if not page.is_closed():
            page.screenshot(path=str(output / "failure.png"))
        raise
    finally:
        (output / "diagnostics.json").write_text(
            json.dumps(
                {
                    "frontend": importlib.metadata.version("comfyui-frontend-package"),
                    "browser": browser.version,
                    "viewport": {"width": width, "height": height},
                    "errors": errors + server.errors,
                    "failure": failure,
                    "startup_diagnostics": startup_diagnostics,
                    "requests": server.requests,
                },
                indent=2,
            )
            + "\n"
        )
        try:
            context.tracing.stop(path=str(output / "trace.zip"))
        except Error:
            if not page.is_closed():
                raise
        finally:
            context.close()


def contained(page: Page, selector: str):
    """Assert the rendered panel/dialog fits the viewport without horizontal clipping.

    A new DOM widget gets its width one frame after the node appears, so the overflow check waits for the
    layout to settle; content that really overflows still fails when the wait runs out.
    """
    page.wait_for_function(
        "selector => { const e = document.querySelector(selector); return !!e && e.clientWidth > 0 && e.scrollWidth <= e.clientWidth + 1; }",
        arg=selector,
    )
    box = page.locator(selector).bounding_box()
    assert box and box["width"] > 0 and box["height"] > 0
    viewport = page.viewport_size
    assert box["x"] >= 0 and box["y"] >= 0, box
    assert box["x"] + box["width"] <= viewport["width"] + 1, box
    assert box["y"] + box["height"] <= viewport["height"] + 1, box


def add_node(page: Page, node_type: str, clear: bool = True) -> str:
    """Create through the real graph API; return the node ID for state assertions.

    With ``clear=False`` the graph keeps its nodes: they move far off the canvas view and stay in the workflow.
    """
    return page.evaluate(
        """([type, clear]) => {
        const app = window.comfyAPI.app.app;
        if (clear) app.graph.clear();
        else for (const other of app.graph.nodes) other.pos = [other.pos[0] - 4000, other.pos[1] - 4000];
        const node = LiteGraph.createNode(type);
        if (!node) throw new Error('Frontend could not create ' + type);
        app.graph.add(node); node.pos = [100, 140];
        app.canvas.ds.scale = Math.min(1, (innerHeight - 160) / node.size[1]); app.canvas.ds.offset = [0, 0];
        app.canvas.setDirty(true, true);
        return String(node.id);
    }""",
        [node_type, clear],
    )


def screenshot(page: Page, name: str, state: str):
    """Capture real pixels after fonts and layout have settled."""
    page.evaluate("document.fonts.ready")
    page.wait_for_function("""() => Array.from(document.images).filter(image => {
        const r = image.getBoundingClientRect();
        return image.checkVisibility() && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
    }).every(image => image.complete && image.naturalWidth > 0)""")
    page.screenshot(path=str(ARTIFACTS / name / (state + ".png")))


def main():
    """Run the same host with a visible Chromium window until it closes."""
    stopping = threading.Event()
    # Let Playwright finish its current protocol call before closing the browser.
    previous_handler = signal.signal(signal.SIGINT, lambda _number, _frame: stopping.set())
    try:
        with FixtureServer() as server, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                with browser_page(browser, server, "inspect") as page:
                    add_node(page, STUDIO)
                    print(
                        f"Fixture frontend: {server.url}\nUse ComfyUI's node search to add Workbench. Close the browser or press Ctrl+C to stop.",
                        flush=True,
                    )
                    try:
                        while not page.is_closed() and not stopping.is_set():
                            page.wait_for_timeout(250)
                    except Error:
                        if not page.is_closed():
                            raise
                    if not page.is_closed():
                        screenshot(page, "inspect", "closing")
            finally:
                browser.close()
    finally:
        signal.signal(signal.SIGINT, previous_handler)


if __name__ == "__main__":
    main()
