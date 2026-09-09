"""Round-trip tests for the common family's routes, on temp, output and input directories under ``tmp_path``.

Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import folder_paths
import numpy as np
import pytest
import torch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from PIL.PngImagePlugin import PngImageFile, PngInfo

from src.arisu_nodes.common import routes
from src.arisu_nodes.common.nodes import ArisuPreviewSaveImage

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

    # with a model selected the saved file is the upscaled image, and the preview's metadata survives
    (dirs / "temp" / "sub").mkdir(parents=True)
    metadata = PngInfo()
    metadata.add_text("prompt", '{"1": "recorded"}')
    Image.fromarray(np.full((4, 5, 3), 200, dtype=np.uint8)).save(dirs / "temp" / "sub" / "meta.png", pnginfo=metadata)
    monkeypatch.setattr(routes, "model_upscaler", lambda name: lambda t: t.repeat_interleave(2, dim=1).repeat_interleave(2, dim=2))
    status, body = post({"images": [{"filename": "meta.png", "subfolder": "sub", "type": "temp"}], "path": "big", "upscale_model": "stub"})
    assert status == 200, body
    with Image.open(dirs / "output" / "big_00001_.png") as image:
        assert isinstance(image, PngImageFile)
        assert image.size == (10, 8)
        assert image.text == {"prompt": '{"1": "recorded"}'}


def test_save_route_refuses_bad_requests(dirs: Path):
    preview = {"filename": "missing.png", "subfolder": "", "type": "temp"}
    cases = [
        (404, {"images": [preview], "path": "a"}),  # the temp dir was wiped: run again
        (400, {"images": [{**preview, "subfolder": ".."}], "path": "a"}),
        (400, {"images": [{**preview, "type": "output"}], "path": "a"}),
        (400, {"images": [preview], "path": "  "}),
        (400, {"images": [preview], "path": "../a"}),
        (400, {"images": [preview], "path": "a", "upscale_model": "definitely-not-a-model.pth"}),
    ]
    for expected, payload in cases:
        status, body = post(payload)
        assert status == expected and "error" in body, f"case={payload!r} body={body!r}"
    assert not (dirs / "output").exists()


def test_browse_and_view_routes_list_and_serve_host_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    pics = tmp_path / "input" / "pics"
    pics.mkdir(parents=True)
    Image.fromarray(np.full((20, 40, 3), 90, dtype=np.uint8)).save(pics / "wide.png")
    (tmp_path / "input" / ".hidden.png").write_bytes(b"")
    (tmp_path / "input" / "notes.txt").write_text("x")

    # no path: the input directory, with its subdirectories and image files only
    status, body, _ = get(routes.BROWSE_ROUTE)
    assert status == 200, body
    assert body == {"path": str(tmp_path / "input"), "parent": str(tmp_path), "dirs": ["pics"], "files": []}
    # a file path lists the directory holding it; a missing directory is a 404
    status, body, _ = get(routes.BROWSE_ROUTE, path=str(pics / "wide.png"))
    assert status == 200 and body["path"] == str(pics) and body["files"] == ["wide.png"]
    status, body, _ = get(routes.BROWSE_ROUTE, path=str(tmp_path / "nope"))
    assert status == 404 and "error" in body

    # the file itself, then a thumbnail bounded on its longer side
    status, body, content_type = get(routes.VIEW_ROUTE, path=str(pics / "wide.png"))
    assert status == 200 and content_type == "image/png" and body == (pics / "wide.png").read_bytes()
    status, body, content_type = get(routes.VIEW_ROUTE, path=str(pics / "wide.png"), max="16")
    assert status == 200 and content_type == "image/webp"
    with Image.open(BytesIO(body)) as thumb:
        assert thumb.size == (16, 8)
    # refused: relative paths, non-image types, missing files
    refused = [
        (400, {"path": "pics/wide.png"}),
        (400, {"path": str(tmp_path / "input" / "notes.txt")}),
        (404, {"path": str(pics / "missing.png")}),
    ]
    for expected, params in refused:
        status, body, _ = get(routes.VIEW_ROUTE, **params)
        assert status == expected and "error" in body, f"case={params!r} body={body!r}"
