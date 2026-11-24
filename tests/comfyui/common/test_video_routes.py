"""The video segment routes and their real HTTP contracts. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

import asyncio
import functools
import json
import shutil
import threading
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict

import folder_paths
import pytest
import torch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from comfy_api.latest import InputImpl, Types

from src.arisu_nodes.common import video_jobs, video_routes
from src.arisu_nodes.common.nodes import ArisuSaveVideoSegment
from src.arisu_nodes.common.video_store import reading
from tests.support.media import marker_clip

pytestmark = pytest.mark.comfyui

PROJECT = "films/main"
TAKE = "552564c1-1999-442e-a016-c1965b957d62"


def take(output: Path, frames: int = 36, value: float = 0.25, **inputs: Any) -> Dict[str, Any]:
    images, waveform = marker_clip(frames, 32000, value=value)
    audio = {"waveform": torch.from_numpy(waveform)[None], "sample_rate": 32000}
    video = InputImpl.VideoFromComponents(Types.VideoComponents(images=torch.from_numpy(images), audio=audio, frame_rate=Fraction(24)))
    values = {"project_prefix": PROJECT, "clip_name": "shot", "filename_prefix": "", "codec": "h264", "crf": 18, "take_context": ""}
    saved = ArisuSaveVideoSegment.execute(video=video, **{**values, **inputs}).ui["images"][0]
    stem = saved["filename"][: -len(".mp4")]
    return json.loads((output / saved["subfolder"] / f"{stem}.arisu" / "take.json").read_text())


def entry(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "source": "take",
        "take": record["take"],
        "segment": "",
        "root": "output",
        "path": record["video"]["path"],
        "revision": record["video"]["revision"],
        "included": True,
        "range": None,
        "audio": "auto",
        "join": {"correction": None, "fade": 0},
    }


def serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> web.Application:
    output, external = tmp_path / "output", tmp_path / "external"
    external.mkdir(exist_ok=True)
    monkeypatch.setattr(folder_paths, "output_directory", str(output))
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    monkeypatch.setattr(folder_paths, "temp_directory", str(tmp_path / "temp"))
    monkeypatch.setattr(video_routes, "roots", lambda: {"input": str(tmp_path / "input"), "output": str(output), "external": str(external)})
    app = web.Application()
    table = web.RouteTableDef()
    video_routes.register_routes(table, app)
    app.add_routes(table)
    return app


def test_video_routes_describe_plan_and_delete_only_verified_takes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    app = serve(tmp_path, monkeypatch)
    output, external = tmp_path / "output", tmp_path / "external"
    first, second = take(output), take(output, 30)
    directed = take(output, filename_prefix=f"{PROJECT}/director/{TAKE}/clip")
    (output / PROJECT / "director" / TAKE / "clip_00001.safetensors").write_bytes(b"latent")
    # Footage from before this node: a Director render and a stock save, neither with a record.
    legacy = output / "arisu_director" / TAKE
    legacy.mkdir(parents=True)
    shutil.copy(output / first["video"]["path"], legacy / "clip_00001_.mp4")
    shutil.copy(output / first["video"]["path"], output / PROJECT / "videos" / "stock_00001_.mp4")
    shutil.copy(output / first["video"]["path"], external / "found.mp4")
    (external / "notes.mp4").write_text("not a video")
    keep = output / PROJECT / "videos" / "shot_00002_.arisu" / "notes.txt"
    keep.write_text("the user's own file")

    async def run():
        async with TestClient(TestServer(app)) as client:
            listed = await (await client.get("/arisu/video/takes", params={"project": PROJECT})).json()
            # The project browser offers published takes and Director renders; a bare stock file is added explicitly.
            assert [item["path"] for item in listed["takes"]] == [
                first["video"]["path"],
                second["video"]["path"],
                directed["video"]["path"],
            ]
            assert [(item["state"], item["frames"], item["audio"]["source"], item["take"]["origin"]) for item in listed["takes"]] == [
                ("ok", 36, "pcm", "ordinary"),
                ("ok", 30, "pcm", "ordinary"),
                ("ok", 36, "pcm", "director"),
            ]
            # Only ordinary takes with a verified record can be deleted from here.
            assert [item["deletable"] for item in listed["takes"]] == [True, True, False]
            assert listed["takes"][2]["take"]["take"] == TAKE and listed["takes"][0]["fps"] == [24, 1]
            wider = await (await client.get("/arisu/video/takes", params={"project": PROJECT, "legacy": "1"})).json()
            assert (
                wider["takes"][-1]["path"] == f"arisu_director/{TAKE}/clip_00001_.mp4"
                and wider["takes"][-1]["take"]["origin"] == "director"
            )

            ask = [
                {"root": "external", "path": "found.mp4"},
                {"root": "external", "path": "missing.mp4"},
                {"root": "external", "path": "notes.mp4"},
                {"root": "elsewhere", "path": "found.mp4"},
                {"root": "output", "path": first["video"]["path"], "revision": "an older file"},
            ]
            response = await client.post("/arisu/video/describe", json={"entries": ask})
            text = await response.text()
            described = json.loads(text)["entries"]
            assert [item["state"] for item in described] == ["ok", "missing", "unusable", "missing", "changed"]
            # An existing file without companions is a reference: embedded sound, no take, never deletable.
            assert described[0]["audio"]["source"] == "embedded" and described[0]["take"] is None and not described[0]["deletable"]
            assert str(tmp_path) not in text and response.headers["X-Content-Type-Options"] == "nosniff"

            document = {"version": 1, "output": None, "entries": [entry(first), entry(second)]}
            request = {"project": PROJECT, "export_name": "main", "encoding": "inherit", "codec": "h264", "crf": 18, "document": document}
            plan = await (await client.post("/arisu/video/preflight", json=request)).json()
            assert (plan["frames"], plan["samples"], plan["ready"], plan["needs"]) == (66, 88000, True, [])
            assert plan["destination"] == f"{PROJECT}/exports/main_00001/main_00001.mp4" and plan["backend"] == "ffmpeg"
            assert (plan["video"]["operation"], plan["audio"]["operation"]) == ("copy", "encode") and plan["video"]["reason"]
            assert [(row["frames"], row["samples"], row["audio"]) for row in plan["entries"]] == [
                ([0, 36], [0, 48000], "pcm"),
                ([36, 66], [48000, 88000], "pcm"),
            ]
            # A lost PCM companion is named in preflight with an explicit way forward.
            (output / second["audio"]["pcm"]["path"]).rename(tmp_path / "moved.wav")
            plan = await (await client.post("/arisu/video/preflight", json=request)).json()
            assert not plan["ready"] and plan["needs"] == [
                {"kind": "switch_audio", "entries": [document["entries"][1]["id"]], "suggested": {"audio": "embedded"}}
            ]
            (tmp_path / "moved.wav").rename(output / second["audio"]["pcm"]["path"])
            # Preflight never writes: no export directory was reserved.
            assert not (output / PROJECT / "exports").exists()

            for status, kwargs in (
                (403, {"json": request, "headers": {"Origin": "http://elsewhere.example"}}),
                (415, {"data": json.dumps(request)}),
                (413, {"json": {**request, "document": {**document, "padding": "x" * (1024 * 1024)}}}),
                (400, {"json": {**request, "extra": 1}}),
                (400, {"json": {**request, "project": "../films"}}),
                (400, {"json": {**request, "document": {**document, "entries": [{**entry(first), "path": "/etc/passwd"}]}}}),
                (400, {"json": {**request, "crf": 99}}),
            ):
                response = await client.post("/arisu/video/preflight", **kwargs)
                assert response.status == status, kwargs
                assert str(tmp_path) not in await response.text()
            assert (await client.get("/arisu/video/takes", params={"project": "/abs"})).status == 400

            def reference(record: Dict[str, Any]) -> Dict[str, str]:
                return {"root": "output", "path": record["video"]["path"], "revision": record["video"]["revision"]}

            stock = f"{PROJECT}/videos/stock_00001_.mp4"
            candidates = [
                reference(first),
                reference(directed),
                {"root": "external", "path": "found.mp4", "revision": described[0]["revision"]},
                {"root": "output", "path": stock, "revision": "any"},
                {**reference(second), "revision": "an older file"},
            ]
            before = sorted(str(path) for path in tmp_path.rglob("*"))
            dry = await (await client.post("/arisu/video/delete", json={"entries": candidates, "confirm": False})).json()
            assert [item["state"] for item in dry["entries"]] == ["deletable", "refused", "refused", "refused", "refused"]
            stem = first["video"]["path"][: -len(".mp4")]
            assert [item["path"] for item in dry["entries"][0]["files"]] == [
                f"{stem}.arisu/take.json",
                f"{stem}.arisu/audio.wav",
                first["video"]["path"],
            ]
            assert dry["bytes"] == dry["entries"][0]["bytes"] == sum(item["bytes"] for item in dry["entries"][0]["files"]) > 0
            assert sorted(str(path) for path in tmp_path.rglob("*")) == before
            # A browser-supplied list authorizes nothing: every refused candidate survives a confirmed request.
            done = await (await client.post("/arisu/video/delete", json={"entries": candidates, "confirm": True})).json()
            assert [item["state"] for item in done["entries"]] == ["deleted", "refused", "refused", "refused", "refused"]
            assert not (output / first["video"]["path"]).exists() and not (output / f"{stem}.arisu").exists()
            for kept in (directed["video"]["path"], directed["audio"]["pcm"]["path"], stock, second["video"]["path"]):
                assert (output / kept).is_file(), kept
            assert (external / "found.mp4").is_file() and (legacy / "clip_00001_.mp4").is_file()
            # While an export reads a take its deletion waits, then removes only the registered files.
            busy = str((output / second["video"]["path"]).resolve())
            with reading([busy]):
                waiting = await (await client.post("/arisu/video/delete", json={"entries": [reference(second)], "confirm": True})).json()
                assert waiting["entries"][0]["state"] == "deferred" and (output / second["video"]["path"]).is_file()
            assert not (output / second["video"]["path"]).exists() and keep.read_text() == "the user's own file"
            assert (await client.post("/arisu/video/delete", json={"entries": [reference(second)]})).status == 400

    asyncio.run(run())


def test_join_preview_is_bounded_and_suggests_only_a_persistent_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    # No idle allowance: a finished preview expires as soon as the manager is asked again after its last use.
    monkeypatch.setattr(video_routes, "PreviewManager", functools.partial(video_jobs.PreviewManager, idle=0.3))
    app = serve(tmp_path, monkeypatch)
    output = tmp_path / "output"
    dark, bright, same = take(output, 36, 0.25), take(output, 36, 0.35), take(output, 36, 0.25)

    def side(record: Dict[str, Any]) -> Dict[str, Any]:
        return {"root": "output", "path": record["video"]["path"], "revision": record["video"]["revision"], "range": None}

    async def ready(client: TestClient, handle: str) -> Dict[str, Any]:
        for _ in range(600):
            status = await (await client.get(f"/arisu/video/join-preview/{handle}")).json()
            if status["state"] != "running":
                return status
            await asyncio.sleep(0.05)
        raise AssertionError("preview did not finish")

    async def run():
        async with TestClient(TestServer(app)) as client:
            direct = {"outgoing": side(dark), "incoming": side(bright), "join": {"correction": None, "fade": 0}}
            gate, real = threading.Event(), video_jobs.run_export

            def held(*args: Any, **kwargs: Any):
                gate.wait(30)
                return real(*args, **kwargs)

            monkeypatch.setattr(video_jobs, "run_export", held)
            response = await client.post("/arisu/video/join-preview", json=direct)
            assert response.status == 202
            handle = (await response.json())["id"]
            # One worker: a second preview is refused while the first is running, not queued.
            assert (await client.post("/arisu/video/join-preview", json=direct)).status == 429
            assert (await client.get(f"/arisu/video/join-preview/{handle}/view")).status == 409
            gate.set()
            status = await ready(client, handle)
            assert status["state"] == "ready" and status["variants"] == ["a"] and status["cut"] == 1.5 and status["signalling"]["match"]
            # The incoming take is persistently brighter: the bounded suggestion lowers luma and leaves chroma alone.
            fix = status["suggestion"]["correction"]
            assert status["suggestion"]["stable"] and -0.06 <= fix["luma_offset"] < -0.03 and fix["cb_offset"] == fix["cr_offset"] == 0
            played = await client.get(f"/arisu/video/join-preview/{handle}/view", params={"variant": "a"})
            assert played.status == 200 and played.headers["Content-Type"] == "video/mp4" and len(await played.read()) > 1000
            assert (await client.get(f"/arisu/video/join-preview/{handle}/view", params={"variant": "b"})).status == 409
            directory = next((tmp_path / "temp" / "arisu_join").iterdir())
            assert sorted(path.name for path in directory.iterdir()) == ["a.mp4"]
            assert (await client.delete(f"/arisu/video/join-preview/{handle}")).status == 200
            assert (await client.get(f"/arisu/video/join-preview/{handle}")).status == 404 and not directory.exists()

            # A candidate correction or fade adds the B variant; frames and sound length match the direct cut.
            candidate = {**direct, "join": {"correction": {**fix, "taper": 12}, "fade": 10}}
            handle = (await (await client.post("/arisu/video/join-preview", json=candidate)).json())["id"]
            assert (await ready(client, handle))["variants"] == ["a", "b"]
            directory = next((tmp_path / "temp" / "arisu_join").iterdir())
            tools = video_jobs.detect_tools()
            a, b = (video_jobs.probe_path(str(directory / name), tools) for name in ("a.mp4", "b.mp4"))
            assert (a.video.frames, a.audio.samples) == (b.video.frames, b.audio.samples) == (72, 96000)
            # Takes on the same level get no suggestion, and an idle preview expires with its files.
            await asyncio.sleep(0.4)
            steady = {"outgoing": side(dark), "incoming": side(same), "join": {"correction": None, "fade": 0}}
            other = (await (await client.post("/arisu/video/join-preview", json=steady)).json())["id"]
            assert (await client.get(f"/arisu/video/join-preview/{handle}")).status == 404 and not directory.exists()
            assert (await ready(client, other))["suggestion"] == {"stable": False, "correction": None}

            stale = {**direct, "incoming": {**side(bright), "revision": "an older file"}}
            assert (await client.post("/arisu/video/join-preview", json=stale)).status == 409
            for bad in (
                {**direct, "join": {"correction": None, "fade": 500}},
                {**direct, "extra": 1},
                {**direct, "outgoing": {"path": "../x"}},
            ):
                assert (await client.post("/arisu/video/join-preview", json=bad)).status == 400

    asyncio.run(run())
