"""Round-trip tests for the save-button route, on temp and output directories under ``tmp_path``.

Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
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


def post(payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """POST ``payload`` to the save route through a real aiohttp server."""

    async def run() -> Tuple[int, Dict[str, Any]]:
        app = web.Application()
        table = web.RouteTableDef()
        routes.register_routes(table)
        app.add_routes(table)
        async with TestClient(TestServer(app)) as client:
            response = await client.post(routes.SAVE_IMAGE_ROUTE, json=payload)
            return response.status, await response.json()

    return asyncio.run(run())


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
