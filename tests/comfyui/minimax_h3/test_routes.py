"""Contained resource routes and their real HTTP contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from src.arisu_nodes.minimax_h3 import routes
from tests.support.media import make_audio, make_video

pytestmark = pytest.mark.comfyui


def test_resource_routes_browse_probe_ranges_and_reject_untrusted_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "authorized"
    root.mkdir()
    (root / "nested").mkdir()
    make_audio(root / "sound.wav")
    make_video(root / "movie.mkv")
    Image.new("RGB", (5, 3)).save(root / "image.png")
    (root / "document.svg").write_text("<svg/>")
    outside = tmp_path / "outside.wav"
    make_audio(outside)
    sentinel = outside.read_bytes()
    (root / "escape.wav").symlink_to(outside)
    monkeypatch.setattr(routes, "roots", lambda: {"input": str(root), "external": str(root)})
    monkeypatch.setattr(routes.folder_paths, "temp_directory", str(tmp_path / "temp"))

    monkeypatch.setattr(routes.folder_paths, "output_directory", str(tmp_path / "output"))

    async def run():
        app = web.Application()
        table = web.RouteTableDef()
        routes.register_routes(table, app)
        app.add_routes(table)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/arisu/resources/browse", params={"root": "external", "path": ""})
            data = await response.json()
            assert data["files"] == ["image.png", "movie.mkv", "sound.wav"]
            # Browse draws a poster for videos and a waveform tile for audio, so the listing tells them apart.
            assert data["kinds"] == {"image.png": "image", "movie.mkv": "video", "sound.wav": "audio"}
            assert data["dirs"] == ["nested"] and data["parent"] is None
            # Resuming a Director sequence requires the exact video and Motion Context latent.
            take = "552564c1-1999-442e-a016-c1965b957d62"
            directory = tmp_path / "output" / "arisu_director" / take
            directory.mkdir(parents=True)
            params = {"take": take, "video": "clip_00001_.mp4"}
            latent = directory / "clip_00001.safetensors"
            latent.write_bytes(b"latent")
            endpoint = "/arisu/resources/director-take"
            assert await (await client.get(endpoint, params=params)).json() == {}
            video = directory / params["video"]
            video.write_bytes(b"render")
            files = await (await client.get(endpoint, params=params)).json()
            assert files == {"video": True, "latent": True}
            video.write_bytes(b"another take")
            assert (await (await client.get(endpoint, params=params)).json()) == files
            # A project keeps its takes under <project>/director/<take>, with whatever counter the saver claimed.
            project = {"take": take, "video": "clip_00002_.mp4", "project": "films/night shoot"}
            staged = tmp_path / "output" / "films" / "night shoot" / "director" / take
            staged.mkdir(parents=True)
            (staged / "clip_00002_.mp4").write_bytes(b"render")
            (staged / "clip_00001.safetensors").write_bytes(b"latent")
            assert set(await (await client.get(endpoint, params=project)).json()) == {"video", "latent"}
            # The video stays available for assembly after its latent is removed; continuation needs both.
            (staged / "clip_00001.safetensors").unlink()
            assert set(await (await client.get(endpoint, params=project)).json()) == {"video"}
            assert (await client.get(endpoint, params={**project, "project": "../films"})).status == 400
            latent.unlink()
            latent.symlink_to(outside)
            assert (await client.get(endpoint, params=params)).status == 400
            assert (await client.get(endpoint, params={**params, "take": "../outside"})).status == 400
            # Studio reopens Browse at the last reference's file path, which lists its containing directory.
            response = await client.get("/arisu/resources/browse", params={"root": "external", "path": "sound.wav"})
            assert response.status == 200
            again = await response.json()
            assert again["path"] == "" and again["parent"] is None
            assert again["files"] == data["files"] and again["dirs"] == data["dirs"]
            response = await client.get("/arisu/resources/metadata", params={"root": "external", "path": "sound.wav"})
            info = await response.json()
            assert info["kind"] == "audio" and info["duration"] == 1 and info["has_audio"]
            response = await client.get(
                "/arisu/resources/view", params={"root": "external", "path": "sound.wav"}, headers={"Range": "bytes=2-9"}
            )
            assert response.status == 206 and await response.read() == (root / "sound.wav").read_bytes()[2:10]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            response = await client.get("/arisu/resources/poster", params={"root": "external", "path": "movie.mkv", "at": "0", "max": "32"})
            assert response.status == 200 and response.headers["Content-Type"] == "image/webp"
            assert response.headers["X-Content-Type-Options"] == "nosniff" and (await response.read())[:4] == b"RIFF"
            # A browser loads several posters at once: requests past the two worker slots wait their turn rather than
            # failing, while the queue depth and the deadline still refuse work the server cannot absorb.
            assert routes._PROBE_GUARD.acquire(blocking=False) and routes._PROBE_GUARD.acquire(blocking=False)
            try:
                poster = {"root": "external", "path": "movie.mkv", "at": "0", "max": "32"}
                queued = asyncio.create_task(client.get("/arisu/resources/poster", params=poster))
                await asyncio.sleep(0.2)
                assert not queued.done()
                monkeypatch.setattr(routes, "_MAX_WAITERS", 1)
                response = await client.get("/arisu/resources/metadata", params={"root": "external", "path": "sound.wav"})
                assert response.status == 429
                monkeypatch.setattr(routes, "_MAX_WAITERS", 32)
                monkeypatch.setattr(routes, "_WAIT_DEADLINE", 0.1)
                response = await client.get("/arisu/resources/metadata", params={"root": "external", "path": "sound.wav"})
                assert response.status == 429
                assert not queued.done()
            finally:
                routes._PROBE_GUARD.release()
                routes._PROBE_GUARD.release()
            response = await queued
            assert response.status == 200 and response.headers["Content-Type"] == "image/webp"
            response = await client.get("/arisu/resources/poster", params={"root": "external", "path": "sound.wav"})
            assert response.status == 415
            response = await client.get("/arisu/resources/poster", params={"root": "external", "path": "movie.mkv", "at": "abc"})
            assert response.status == 400
            for path in ("../outside.wav", "..\\outside.wav", str(outside), "escape.wav", "document.svg"):
                for endpoint in ("metadata", "view", "poster"):
                    response = await client.get(f"/arisu/resources/{endpoint}", params={"root": "external", "path": path})
                    assert response.status in (400, 415), (path, response.status)
                    assert str(tmp_path) not in await response.text()
            response = await client.post("/arisu/resources/proxy", json={"root": "external", "path": "sound.wav", "revision": "stale"})
            assert response.status == 409
            response = await client.post("/arisu/resources/proxy", data="{}")
            assert response.status == 415
            response = await client.post(
                "/arisu/resources/proxy", data="x" * (1024 * 1024 + 1), headers={"Content-Type": "application/json"}
            )
            assert response.status == 413

            async def chunks():
                for _ in range(17):
                    yield b"x" * 65536

            response = await client.post("/arisu/resources/proxy", data=chunks(), headers={"Content-Type": "application/json"})
            assert response.status == 413
            # Root discovery and relative ancestry never expose the administrator's filesystem path.
            response = await client.get("/arisu/resources/browse", params={"root": "external", "path": "nested"})
            data = await response.json()
            assert data["parent"] == "" and str(tmp_path) not in str(data)

    asyncio.run(run())
    assert outside.read_bytes() == sentinel
