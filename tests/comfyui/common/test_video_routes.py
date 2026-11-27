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
from types import SimpleNamespace
from typing import Any, Dict, List

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
    values = {"project_prefix": PROJECT, "clip_name": "shot", "codec": "h264", "crf": 18, "take_context": ""}
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


def test_video_routes_describe_plan_and_delete_confirmed_videos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    app = serve(tmp_path, monkeypatch)
    output, external = tmp_path / "output", tmp_path / "external"
    # A legacy stock Director file can recover its recorded segment without a live workflow or sidecar.
    old_film = {"selected": "s1", "segments": [{"id": "s1", "intent": "The boat enters the bay"}]}
    old_graph = {
        "1": {"class_type": "ArisuMiniMaxH3DirectorWorkbench", "inputs": {"film_json": json.dumps(old_film)}},
        "2": {"class_type": "SaveVideo", "inputs": {"filename_prefix": f"arisu_director/{TAKE}/clip"}},
    }
    monkeypatch.setattr(ArisuSaveVideoSegment, "hidden", SimpleNamespace(prompt=old_graph))
    first, second = take(output), take(output, 30)
    directed = take(output, take_context=json.dumps({"take": TAKE, "segment": "s1", "predecessor": None, "transition": "cut"}))
    # A restored take keeps its metadata and PCM even when the filesystem gives both files new identities.
    for media in (directed["video"], directed["audio"]["pcm"]):
        location = output / media["path"]
        restored = location.with_suffix(".restored")
        shutil.copyfile(location, restored)
        restored.replace(location)
    (output / PROJECT / "director" / TAKE / "clip_00001.safetensors").write_bytes(b"latent")
    # Footage from before this node: a Director render and a stock save, neither with a record.
    legacy = output / "arisu_director" / TAKE
    legacy.mkdir(parents=True)
    shutil.copy(output / first["video"]["path"], legacy / "clip_00001_.mp4")
    shutil.copy(output / first["video"]["path"], output / PROJECT / "videos" / "stock_00001_.mp4")
    shutil.copy(output / first["video"]["path"], external / "found.mp4")
    (external / "notes.mp4").write_text("not a video")
    notes = output / PROJECT / "videos" / "shot_00002_.arisu" / "notes.txt"
    notes.write_text("notes for this take")

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
            assert listed["takes"][2]["take"]["take"] == TAKE and listed["takes"][0]["fps"] == [24, 1]
            wider = await (await client.get("/arisu/video/takes", params={"project": PROJECT, "legacy": "1"})).json()
            assert (
                wider["takes"][-1]["path"] == f"arisu_director/{TAKE}/clip_00001_.mp4"
                and wider["takes"][-1]["take"]["origin"] == "director"
            )

            assert wider["takes"][-1]["take"]["recorded_segment"] == {"segment": "s1", "order": 1, "title": "The boat enters the bay"}

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
            assert [item["state"] for item in described] == ["ok", "missing", "unusable", "missing", "ok"]
            # An existing file without companions is an edit reference with embedded sound.
            assert described[0]["audio"]["source"] == "embedded" and described[0]["take"] is None
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
                return {"root": "output", "path": record["video"]["path"], "revision": "legacy revision"}

            stock = f"{PROJECT}/videos/stock_00001_.mp4"
            candidates = [
                reference(first),
                reference(directed),
                {"root": "external", "path": "found.mp4", "revision": "legacy revision"},
                {"root": "output", "path": stock, "revision": "any"},
                {**reference(second), "revision": "an older file"},
            ]
            film = output / PROJECT / "exports" / "main_00001" / "main_00001.mp4"
            film.parent.mkdir(parents=True)
            film.write_bytes(b"video")
            sequence = film.with_name("sequence.json")
            sequence.write_text("the export record")
            input_video = tmp_path / "input" / "camera.AVI"
            input_video.parent.mkdir()
            input_video.write_bytes(b"corrupt but still selected for deletion")
            director_dir = output / PROJECT / "director" / TAKE
            alternate = director_dir / "clip_00003_.mp4"
            alternate.write_bytes(b"alternate clip")
            (director_dir / "empty").mkdir()
            nested = notes.with_name("reference.webm")
            nested.write_bytes(b"reference")
            candidates.extend(
                [
                    {"root": "output", "path": film.relative_to(output).as_posix(), "revision": ""},
                    {"root": "input", "path": input_video.name, "revision": ""},
                    {"root": "output", "path": sequence.relative_to(output).as_posix(), "revision": ""},
                    {"root": "elsewhere", "path": "found.mp4", "revision": ""},
                ]
            )
            before = sorted(str(path) for path in tmp_path.rglob("*"))
            # The dedicated folder covers another selected clip even if a nested video was selected first.
            overlaps = [{"root": "output", "path": p.relative_to(output).as_posix(), "revision": ""} for p in (nested, alternate)]
            dry = await (
                await client.post(
                    "/arisu/video/delete", json={"entries": [overlaps[0], *candidates, overlaps[1], candidates[0]], "confirm": False}
                )
            ).json()
            assert [item["state"] for item in dry["entries"]] == ["deletable"] * 7 + ["refused"] * 2
            stem = first["video"]["path"][: -len(".mp4")]
            assert {item["path"] for item in dry["entries"][0]["files"]} == {
                f"{stem}.arisu/take.json",
                f"{stem}.arisu/audio.wav",
                first["video"]["path"],
            }
            assert dry["entries"][0]["directory"] == f"{stem}.arisu"
            assert dry["entries"][1]["directory"] == director_dir.relative_to(output).as_posix()
            assert [len(item["files"]) for item in dry["entries"]] == [3, 5, 1, 1, 5, 1, 1, 0, 0]
            assert dry["bytes"] == sum(file["bytes"] for item in dry["entries"] for file in item["files"]) > 0
            assert sorted(str(path) for path in tmp_path.rglob("*")) == before

            async def confirm(rows: List[Dict[str, Any]]) -> List[str]:
                body = {"entries": [{key: row[key] for key in ("root", "path", "revision")} for row in rows], "confirm": True}
                result = await (await client.post("/arisu/video/delete", json=body)).json()
                return [item["state"] for item in result["entries"]]

            # A workflow revision, including one for the current file, cannot confirm deletion.
            assert await confirm(candidates) == ["refused"] * len(candidates)
            assert sorted(str(path) for path in tmp_path.rglob("*")) == before
            # Validate a whole batch before side effects; duplicates fit up to the maximum edit size.
            malformed = {"entries": [reference(first) | {"revision": dry["entries"][0]["revision"]}, {"id": "bad"}], "confirm": True}
            assert (await client.post("/arisu/video/delete", json=malformed)).status == 400 and (output / first["video"]["path"]).is_file()
            repeated = {"entries": [candidates[0]] * 512, "confirm": False}
            assert (await client.post("/arisu/video/delete", json=repeated)).status == 200
            repeated["entries"].append(candidates[0])
            assert (await client.post("/arisu/video/delete", json=repeated)).status == 400

            # A confirmed action removes both whole take folders; holding the alternate clip delays its UUID folder.
            busy = str((output / second["video"]["path"]).resolve())
            with reading([busy, str(alternate)]):
                assert await confirm(dry["entries"][:7]) == ["deleted", "deferred", "deleted", "deleted", "deferred", "deleted", "deleted"]
                assert (output / second["video"]["path"]).is_file() and (director_dir / "clip_00001.safetensors").is_file()
            for gone in (first["video"]["path"], f"{stem}.arisu", directed["video"]["path"], stock, second["video"]["path"]):
                assert not (output / gone).exists(), gone
            assert not (external / "found.mp4").exists() and not input_video.exists() and not film.exists()
            assert not director_dir.exists() and director_dir.parent.exists()
            assert not notes.parent.exists() and notes.parent.parent.exists()
            assert (legacy / "clip_00001_.mp4").is_file() and sequence.read_text() == "the export record"
            legacy_video = {"root": "output", "path": f"arisu_director/{TAKE}/clip_00001_.mp4", "revision": ""}
            legacy_plan = await (await client.post("/arisu/video/delete", json={"entries": [legacy_video], "confirm": False})).json()
            assert legacy_plan["entries"][0]["directory"] == f"arisu_director/{TAKE}"
            assert await confirm(legacy_plan["entries"]) == ["deleted"] and not legacy.exists() and legacy.parent.is_dir()
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
        return {"root": "output", "path": record["video"]["path"], "revision": "legacy revision", "range": None}

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

            missing = {**direct, "incoming": {**side(bright), "path": "gone.mp4"}}
            assert (await client.post("/arisu/video/join-preview", json=missing)).status == 409
            for bad in (
                {**direct, "join": {"correction": None, "fade": 500}},
                {**direct, "extra": 1},
                {**direct, "outgoing": {"path": "../x"}},
            ):
                assert (await client.post("/arisu/video/join-preview", json=bad)).status == 400

    asyncio.run(run())
