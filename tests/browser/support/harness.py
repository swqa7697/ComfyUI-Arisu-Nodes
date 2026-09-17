"""Isolated real-frontend host with synthetic API state and browser diagnostics."""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.resources
import io
import json
import signal
import threading
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from aiohttp import web
from PIL import Image, ImageDraw
from playwright.sync_api import Browser, ConsoleMessage, Error, Page, Route, WebSocketRoute, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/browser/fixtures"
ARTIFACTS = ROOT / ".tmp/browser/results"
STUDIO = "ArisuMiniMaxH3ResourceStudio"
WORKBENCH = "ArisuMiniMaxH3PromptWorkbench"
DRAFT = "A paper boat drifts across a sunlit pond. The camera follows slowly."


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
        self.settings: Dict[str, Any] = {
            "Comfy.VueNodes.Enabled": False,
            "Comfy.UseNewMenu": "Top",
            "Comfy.TutorialCompleted": True,
            "Comfy.Notification.ShowVersionUpdates": False,
            "Comfy.Workflow.WorkflowTabsPosition": "Topbar",
        }
        self.userdata: Dict[str, bytes] = {}
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
            "policy_revision": 5,
            "ready": self.available,
            "version": "fixture",
            "models": [{"id": "fixture", "name": "Fixture model", "efforts": ["medium"]}],
            "selection": {"model": "fixture", "effort": "medium"},
        }
        return {
            "docker": True,
            "agents": {"codex": info, "grok": info},
            "skills": [{"id": "bundled:with-ref", "name": "with-ref", "source": "bundled"}],
        }

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
            return web.json_response(json.loads((FIXTURES / "object_info.json").read_text()))
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
                    json.dumps({"item": {"type": "reasoning", "text": "Inspecting the selected reference, motion and lighting. " * 200}}),
                    "[tool] workbench.get_context",
                    *json.dumps(
                        {"references": [{"id": i, "notes": "Synthetic reference details " * 20} for i in range(20)]}, indent=2
                    ).splitlines(),
                    json.dumps({"message": {"content": [{"type": "thinking", "thinking": "Preserve the folded silhouette."}]}}),
                    '[tool · item.completed] view_image\n{"asset_id": "reference-1"}',
                    "[agent] The reference shows a paper boat with warm reflected light.",
                ]
                if job
                else ["[codex] build", "#1 [internal] load build definition from Dockerfile", "#2 resolve base image", "#3 DONE 0.4s"]
            )
            lines += [f"#4 Processing {'reference' if job else 'image build'} step {i + 1}" for i in range(65)]
            if not job:
                lines += ["Sign in at https://example.test/device", "Device code: ABCD-EFGH", "Waiting for browser authorization…"]
            if job:
                lines += [
                    '[tool · item.completed] view_image\n{"asset_id": "reference-1"}',
                    "[analysis] The reference shows a small paper boat on a calm pond. Preserve its folded silhouette and the warm light.",
                    "[tool · item.completed] workbench.get_context\nSelected video: 22 frames · Audio: excluded",
                    "[analysis] Match the gentle forward drift in the motion context. Keep the camera low and avoid a sudden change in direction.",
                    "[agent] Drafting a continuous tracking shot with soft reflections and restrained motion…",
                ]
            lines += [f"[analysis] Live update {i + 1}" for i in range(self.log_polls)]
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
            return web.json_response({"id": "fixture-job"})
        if path == "/arisu/workbench/jobs/fixture-job":
            self.polls += 1
            if self.fail_generation:
                return web.json_response({"state": "failed", "error": "Simulated provider unavailable"})
            return web.json_response(
                {"state": "generating"} if self.hold_generation or self.polls < 3 else {"state": "complete", "draft": DRAFT}
            )
        if path in ("/arisu/workbench/release", "/arisu/workbench/cancel", "/arisu/workbench/action") and method == "POST":
            return web.json_response({"accepted": True})
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
        if path == "/arisu/resources/metadata":
            kind = "audio" if request.query.get("path", "").endswith(".wav") else "image"
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


def add_node(page: Page, node_type: str) -> str:
    """Create through the real graph API; return the node ID for state assertions."""
    return page.evaluate(
        """type => {
        const app = window.comfyAPI.app.app;
        app.graph.clear();
        const node = LiteGraph.createNode(type);
        if (!node) throw new Error('Frontend could not create ' + type);
        app.graph.add(node); node.pos = [100, 140];
        app.canvas.ds.scale = Math.min(1, (innerHeight - 160) / node.size[1]); app.canvas.ds.offset = [0, 0];
        app.canvas.setDirty(true, true);
        return String(node.id);
    }""",
        node_type,
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
