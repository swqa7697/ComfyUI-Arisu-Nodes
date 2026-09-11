"""Round-trip tests for the common family's routes, on temp, output and input directories under ``tmp_path``.

Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Tuple

import folder_paths
import numpy as np
import pytest
import torch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import EpsImagePlugin, Image
from PIL.PngImagePlugin import PngImageFile, PngInfo

from src.arisu_nodes.common import paths, routes
from src.arisu_nodes.common.nodes import ArisuPreviewSaveImage, ArisuPreviewSaveImageUpscale

pytestmark = pytest.mark.comfyui


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ComfyUI's temp and output directories at ``tmp_path``."""
    monkeypatch.setattr(folder_paths, "temp_directory", str(tmp_path / "temp"))
    monkeypatch.setattr(folder_paths, "output_directory", str(tmp_path / "output"))
    return tmp_path


def call(method: str, route: str, **kwargs: Any) -> Tuple[int, Any, str]:
    """Send one request to the pack's routes through a real aiohttp server.

    Returns:
        The status, the body (decoded JSON, or the raw bytes of a file response), and the content type.
    """

    async def run() -> Tuple[int, Any, str]:
        app = web.Application()
        table = web.RouteTableDef()
        routes.register_routes(table)
        app.add_routes(table)
        async with TestClient(TestServer(app)) as client:
            response = await client.request(method, route, **kwargs)
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            body = await response.json() if response.content_type == "application/json" else await response.read()
            return response.status, body, response.content_type

    return asyncio.run(run())


def post(payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """POST ``payload`` to the save route."""
    status, body, _ = call("POST", routes.SAVE_IMAGE_ROUTE, json=payload)
    return status, body


def get(route: str, **params: str) -> Tuple[int, Any, str]:
    """GET ``route`` with ``params`` as the query string."""
    return call("GET", route, params=params)


def pixels(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def test_save_route_copies_the_preview_and_upscales_on_request(dirs: Path, monkeypatch: pytest.MonkeyPatch):
    batch = torch.rand(2, 8, 6, 3)
    ui = ArisuPreviewSaveImage.execute(images=batch, path="shots/a").ui
    assert isinstance(ui, dict)
    previews: List[Dict[str, str]] = ui["images"]

    status, body = post({"images": previews, "path": "shots/a"})
    assert status == 200, body
    saved = [dirs / "output" / f["subfolder"] / f["filename"] for f in body["saved"]]
    assert [p.name for p in saved] == ["a_00001_.png", "a_00002_.png"]
    for preview, copy in zip(previews, saved):
        assert (pixels(dirs / "temp" / preview["subfolder"] / preview["filename"]) == pixels(copy)).all()

    # a second click never overwrites: the counter moves on
    status, body = post({"images": previews[:1], "path": "shots/a"})
    assert status == 200 and body["saved"][0]["filename"] == "a_00003_.png"

    # The upscale node also keeps previews in temp and saves its relative prefix beneath output.
    ui = ArisuPreviewSaveImageUpscale.execute(images=batch[:1], path="nested/shots/a", upscale_model="none").ui
    assert isinstance(ui, dict)
    assert all(ref["type"] == "temp" for ref in ui["images"])
    status, body = post({"images": ui["images"], "path": ui["path"][0], "upscale_model": ui["upscale_model"][0]})
    assert status == 200, body
    assert body["saved"][0]["subfolder"] == "nested/shots"
    assert (pixels(dirs / "output" / "nested" / "shots" / "a_00001_.png") == pixels(saved[0])).all()

    # with a model selected the saved file is the upscaled image, and the preview's metadata survives
    (dirs / "temp" / "sub").mkdir(parents=True)
    metadata = PngInfo()
    metadata.add_text("prompt", '{"1": "recorded"}')
    Image.fromarray(np.full((4, 5, 3), 200, dtype=np.uint8)).save(dirs / "temp" / "sub" / "meta.png", pnginfo=metadata)
    monkeypatch.setattr(routes, "model_upscaler", lambda name: lambda t: t.repeat_interleave(2, dim=1).repeat_interleave(2, dim=2))
    status, body = post(
        {
            "images": [{"filename": "meta.png", "subfolder": "sub", "type": "temp"}],
            "path": "shots/%width%x%height%/big",
            "upscale_model": "stub",
        }
    )
    assert status == 200, body
    with Image.open(dirs / "output" / "shots" / "10x8" / "big_00001_.png") as image:
        assert isinstance(image, PngImageFile)
        assert image.size == (10, 8)
        assert image.text == {"prompt": '{"1": "recorded"}'}


def test_save_route_refuses_bad_requests(dirs: Path, monkeypatch: pytest.MonkeyPatch):
    preview = {"filename": "missing.png", "subfolder": "", "type": "temp"}
    cases = [
        (404, {"images": [preview], "path": "a"}),
        (400, {"images": [{**preview, "subfolder": ".."}], "path": "a"}),
        (400, {"images": [{**preview, "type": "output"}], "path": "a"}),
        (400, {"images": [preview], "path": "  "}),
        (400, {"images": [preview], "path": "../a"}),
        (400, {"images": [preview], "path": "a/../b"}),
        (400, {"images": [preview] * 257, "path": "a"}),
    ]
    for expected, payload in cases:
        status, body = post(payload)
        assert status == expected and "error" in body, f"case={payload!r} body={body!r}"
    assert not (dirs / "output").exists()
    assert call("POST", routes.SAVE_IMAGE_ROUTE, data="{}", headers={"Content-Type": "text/plain"})[0] == 415
    assert call("POST", routes.SAVE_IMAGE_ROUTE, data="{", headers={"Content-Type": "application/json"})[0] == 400
    assert call("POST", routes.SAVE_IMAGE_ROUTE, data=" " * (1024 * 1024 + 1), headers={"Content-Type": "application/json"})[0] == 413

    (dirs / "temp").mkdir()
    (dirs / "output").mkdir()
    outside = dirs / "outside"
    outside.mkdir()
    monkeypatch.setattr(paths, "external_roots", lambda: {"photos": str(outside)})
    Image.new("RGB", (3, 2)).save(dirs / "temp" / "ok.png")
    Image.new("RGB", (3, 2)).save(outside / "secret.png")
    sentinel = (outside / "secret.png").read_bytes()
    (dirs / "temp" / "escape.png").symlink_to(outside / "secret.png")
    (dirs / "temp" / "escape").symlink_to(outside, target_is_directory=True)
    (dirs / "output" / "escape").symlink_to(outside, target_is_directory=True)
    ok = {**preview, "filename": "ok.png"}
    loaded = []
    monkeypatch.setattr(routes, "model_upscaler", lambda name: loaded.append(name))
    # Every reference is checked before any output or model load, even a bad second reference.
    malicious = [
        {"images": [ok, {**ok, "filename": "escape.png"}], "path": "a"},
        {"images": [{**ok, "filename": "secret.png", "subfolder": "escape"}], "path": "a"},
        {"images": [ok], "path": "escape/new/a"},
        {"images": [ok], "path": "escape/%width%/a"},
    ]
    # Even an absolute prefix already inside output must be supplied as a relative path.
    malicious.extend(
        {"images": [ok], "path": prefix}
        for prefix in (
            str(dirs / "output" / "absolute"),
            str(outside / "absolute"),
            "~/a",
            "C:/a",
            "C:relative",
            "\\\\server\\share\\a",
            "../outside/a",
            "nested/../a",
            "nested\\..\\a",
        )
    )
    for payload in malicious:
        status, body = post({**payload, "upscale_model": "stub"})
        assert status == 400 and "error" in body, f"case={payload!r}"
    assert loaded == []
    assert (outside / "secret.png").read_bytes() == sentinel
    assert sorted(p.name for p in outside.iterdir()) == ["secret.png"]
    assert sorted(p.name for p in (dirs / "output").iterdir()) == ["escape"]
    # Existing and dangling output symlinks are collisions, never followed or overwritten.
    (dirs / "output" / "a_00001_.png").symlink_to(outside / "secret.png")
    (dirs / "output" / "a_00002_.png").symlink_to(outside / "missing.png")
    status, body = post({"images": [ok], "path": "a"})
    assert status == 200 and body["saved"][0]["filename"] == "a_00003_.png"
    assert not (outside / "missing.png").exists()
    assert (outside / "secret.png").read_bytes() == sentinel
    (dirs / "temp" / "bad.png").write_text("<svg><script>alert(1)</script></svg>")
    status, _ = post({"images": [{**ok, "filename": "bad.png"}], "path": "b"})
    assert status == 415

    # Read roots never redirect saves, even when a custom client supplies a root parameter.
    status, body = post({"images": [ok], "root": "photos", "path": "photos/nested/a"})
    assert status == 200, body
    assert (dirs / "output" / "photos" / "nested" / "a_00001_.png").is_file()
    assert sorted(p.name for p in outside.iterdir()) == ["secret.png"]
    assert (outside / "secret.png").read_bytes() == sentinel

    # Unexpected failures stay in server logs, not in client responses.
    def fail(req: Any) -> Any:
        raise RuntimeError(f"internal failure at {outside}")

    monkeypatch.setattr(routes, "_save", fail)
    status, body = post({"images": [ok], "path": "b"})
    assert status == 500 and str(outside) not in json.dumps(body)

    def invalid(req: Any) -> Any:
        raise ValueError(f"decoder failure at {outside}")

    monkeypatch.setattr(routes, "_save", invalid)
    status, body = post({"images": [ok], "path": "b"})
    assert status == 400 and str(outside) not in json.dumps(body)


def test_browse_and_view_routes_list_and_serve_host_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    monkeypatch.setattr(folder_paths, "output_directory", str(tmp_path / "output"))
    pics = tmp_path / "input" / "pics"
    pics.mkdir(parents=True)
    external = tmp_path / "photos"
    external.mkdir()
    monkeypatch.setattr(paths, "external_roots", lambda: {"photos": str(external)})
    Image.fromarray(np.full((20, 40, 3), 90, dtype=np.uint8)).save(pics / "wide.png")
    Image.new("RGB", (6, 4)).save(external / "other.tif")
    (tmp_path / "input" / ".hidden.png").write_bytes(b"")
    (tmp_path / "input" / "notes.txt").write_text("sentinel")
    (pics / "payload.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    (pics / "bad.png").write_text("private non-image content")
    Image.new("RGB", (2, 2)).save(pics / "document.png", format="EPS")

    def refuse_interpreter(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a document interpreter must never run")

    monkeypatch.setattr(EpsImagePlugin, "Ghostscript", refuse_interpreter)

    (pics / "escape").symlink_to(external, target_is_directory=True)
    (pics / "escaped.png").symlink_to(external / "other.tif")

    status, body, _ = get(routes.BROWSE_ROUTE)
    assert status == 200, body
    assert {key: body[key] for key in ("root", "path", "parent", "dirs", "files")} == {
        "root": "input",
        "path": "",
        "parent": None,
        "dirs": ["pics"],
        "files": [],
    }
    assert body["roots"] == [{"id": name, "label": name} for name in ("input", "output", "photos")]
    assert body["ancestors"] == [] and str(tmp_path) not in json.dumps(body)
    status, body, _ = get(routes.BROWSE_ROUTE, path="pics/wide.png", tree="0")
    assert status == 200 and body["path"] == "pics" and body["ancestors"] == []
    assert body["dirs"] == [] and body["files"] == ["bad.png", "document.png", "wide.png"]
    status, body, _ = get(routes.BROWSE_ROUTE, root="photos")
    assert status == 200 and body["files"] == ["other.tif"] and body["parent"] is None
    status, body, content_type = get(routes.VIEW_ROUTE, root="photos", path="other.tif")
    assert status == 200 and content_type == "image/png"
    with Image.open(BytesIO(body)) as image:
        assert image.size == (6, 4)
    # Source sidecars are never served, and all full-size responses are raster PNGs.
    (pics / "wide.png.gz").symlink_to(tmp_path / "input" / "notes.txt")
    status, body, content_type = call("GET", routes.VIEW_ROUTE, params={"path": "pics/wide.png"}, headers={"Accept-Encoding": "gzip"})
    assert status == 200 and content_type == "image/png"
    with Image.open(BytesIO(body)) as image:
        assert image.size == (40, 20) and np.array(image)[0, 0].tolist() == [90, 90, 90]
    for params, expected in [
        ({"max": "16"}, (16, 8)),
        ({"crop": "10,5,20,10"}, (20, 10)),
        ({"crop": "10,5,20,10", "max": "16"}, (16, 8)),
        ({"crop": "0,0,40,20"}, (40, 20)),
    ]:
        status, body, content_type = get(routes.VIEW_ROUTE, path="pics/wide.png", **params)
        assert status == 200 and content_type == ("image/webp" if "max" in params else "image/png"), f"case={params!r}"
        with Image.open(BytesIO(body)) as image:
            assert image.size == expected
    for route in (routes.BROWSE_ROUTE, routes.VIEW_ROUTE):
        for params in [
            {"path": str(pics / "wide.png")},
            {"path": "../photos/other.tif"},
            {"path": "pics/../pics/wide.png"},
            {"path": "pics/escape/other.tif"},
            {"path": "pics/escaped.png"},
            {"path": "x", "root": "unknown"},
            {"path": "C:\\wide.png"},
            {"path": "..\\photos\\other.tif"},
            {"path": "~/wide.png"},
            {"path": "a\x00.png"},
        ]:
            status, body, _ = get(route, **params)
            assert status == 400 and str(tmp_path) not in json.dumps(body), f"case={route, params!r} body={body!r}"
    for expected, params in [
        (415, {"path": "notes.txt"}),
        (415, {"path": "pics/payload.svg"}),
        (415, {"path": "pics/bad.png"}),
        (415, {"path": "pics/document.png"}),
        (404, {"path": "pics/missing.png"}),
        (400, {"path": "pics/wide.png", "crop": "x"}),
        (415, {"path": "pics/wide.png", "crop": "40,0,1,1"}),
    ]:
        status, body, _ = get(routes.VIEW_ROUTE, **params)
        assert status == expected and "error" in body, f"case={params!r} body={body!r}"
    assert get(routes.BROWSE_ROUTE, path="nope")[0] == 404
    # The HTTP layer decodes once: encoded traversal is still refused.
    for route in (routes.BROWSE_ROUTE, routes.VIEW_ROUTE):
        assert call("GET", route + "?path=%2e%2e%2fphotos%2fother.tif")[0] == 400


def test_save_guard_survives_cancellation_and_rejects_concurrent_work(monkeypatch: pytest.MonkeyPatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def worker(req: Any) -> List[Dict[str, str]]:
        entered.set()
        try:
            assert release.wait(5), "test did not release save worker"
            return []
        finally:
            finished.set()

    monkeypatch.setattr(routes, "_save", worker)
    payload = json.dumps({"images": [{"filename": "a.png", "subfolder": "", "type": "temp"}], "path": "a"}).encode()

    class Body:
        async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
            yield payload

    def request() -> Any:
        return SimpleNamespace(content_type="application/json", content_length=None, content=Body())

    async def run():
        first = asyncio.create_task(routes._save_image(request()))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert (await routes._save_image(request())).status == 429
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (await routes._save_image(request())).status == 429
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 5)
        # Give the worker completion callback a turn, then another save succeeds.
        assert (await routes._save_image(request())).status == 200

    asyncio.run(run())
