"""Execute-level tests for Assemble Video exports on the native FFmpeg backend. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional

import av
import comfy.model_management
import folder_paths
import pytest
import torch
from comfy_api.latest import InputImpl, Types
from comfy_execution.graph_utils import ExecutionBlocker

from src.arisu_nodes.common import nodes, video_jobs
from src.arisu_nodes.common.nodes import ArisuAssembleVideo, ArisuSaveVideoSegment
from src.arisu_nodes.common.video_jobs import ExportRefused
from tests.support.media import marker_clip, read_markers

pytestmark = pytest.mark.comfyui

PROJECT = "films/main"


def take(output: Path, frames: int, rate: int = 32000, sound: bool = True, codec: str = "h264", name: str = "shot") -> Dict[str, Any]:
    """Save one take with a flash on frame 6 and a click at 0.250 s, and return its record."""
    images, waveform = marker_clip(frames, rate, flashes=[6], clicks=[rate // 4])
    audio = {"waveform": torch.from_numpy(waveform)[None], "sample_rate": rate} if sound else None
    video = InputImpl.VideoFromComponents(Types.VideoComponents(images=torch.from_numpy(images), audio=audio, frame_rate=Fraction(24)))
    crf = {"h264": 18, "h265": 20, "av1": 24}[codec]
    saved = ArisuSaveVideoSegment.execute(
        video=video, project_prefix=PROJECT, clip_name=name, filename_prefix="", codec=codec, crf=crf, take_context=""
    ).ui["images"][0]
    stem = saved["filename"][: -len(".mp4")]
    return json.loads((output / saved["subfolder"] / f"{stem}.arisu" / "take.json").read_text())


def entry(record: Dict[str, Any], **changes: Any) -> Dict[str, Any]:
    video = record["video"]
    base = {
        "id": str(uuid.uuid4()),
        "source": "take",
        "take": record["take"],
        "segment": "",
        "root": "output",
        "path": video["path"],
        "revision": video["revision"],
        "included": True,
        "range": None,
        "audio": "auto",
        "join": {"correction": None, "fade": 0},
    }
    return {**base, **changes}


def export(entries: List[Dict[str, Any]], job: str = "", output: Optional[Dict[str, Any]] = None, **inputs: Any) -> Any:
    values = {"project_prefix": PROJECT, "export_name": "main", "encoding": "inherit", "codec": "h264", "crf": 18}
    document = json.dumps({"version": 1, "output": output, "entries": entries})
    return ArisuAssembleVideo.execute(**{**values, **inputs}, edit_json=document, export_request=job)


def listing(root: Path) -> List[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_assemble_video_exports_the_planned_timeline_and_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    output = tmp_path / "output"
    monkeypatch.setattr(folder_paths, "output_directory", str(output))
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    # The design's example: 243 generated frames per segment, with 0, 22 and 39 already trimmed upstream.
    records = [take(output, frames) for frames in (243, 221, 204)]
    entries = [entry(record) for record in records]
    exports = output / PROJECT / "exports"

    # An ordinary run reports the project and writes no film.
    idle = export(entries)
    assert all(isinstance(value, ExecutionBlocker) for value in idle.args) and idle.ui == {"arisu_project": [PROJECT]}
    assert not exports.exists()

    job = str(uuid.uuid4())
    done = export(entries, job)
    assert done.ui["images"] == [{"filename": "main_00001.mp4", "subfolder": f"{PROJECT}/exports/main_00001", "type": "output"}]
    assert done.ui["arisu_export"][0]["request"] == job and done.args[1] == f"{PROJECT}/exports/main_00001/main_00001.mp4"
    record = json.loads(done.args[2])
    assert record == json.loads((exports / "main_00001" / "sequence.json").read_text())
    # The version directory holds the film and its record, nothing else.
    assert listing(exports) == ["main_00001", "main_00001/main_00001.mp4", "main_00001/sequence.json"]
    assert (record["video"]["frames"], record["audio"]["samples"]) == (668, 890667)
    assert [item["frames"] for item in record["entries"]] == [[0, 243], [243, 464], [464, 668]]
    assert [item["samples"] for item in record["entries"]] == [[0, 324000], [324000, 618667], [618667, 890667]]
    # Whole compatible takes keep their video packets; sound is rebuilt from PCM and encoded once.
    assert (record["video"]["operation"], record["audio"]["operation"]) == ("copy", "encode")
    assert all(item["audio"]["source"] == "pcm" for item in record["entries"])
    assert done.args[0].get_frame_count() == 668
    seen = read_markers(exports / "main_00001" / "main_00001.mp4")
    # Every join and the common start: each flash and click sits on its planned frame and sample, not a shared offset later.
    assert seen["frames"] == 668 and seen["flashes"] == [6, 249, 470] and seen["times"][0] == 0.25
    assert seen["times"][1:] == [249 / 24, 470 / 24] and seen["samples"] == 890667
    assert all(abs(found - planned) <= 8 for found, planned in zip(seen["clicks"], (8000, 332000, 626667))) and len(seen["clicks"]) == 3
    with av.open(str(exports / "main_00001" / "main_00001.mp4")) as container:
        stamps = [packet.pts * packet.time_base for packet in container.demux(container.streams.video[0]) if packet.pts is not None]
        assert sorted(stamps) == [Fraction(index, 24) for index in range(668)]

    # The same job recognizes its completed output; a deliberate repeat is a new version.
    assert json.loads(export(entries, job).args[2])["counter"] == 1
    assert json.loads(export(list(reversed(entries)), str(uuid.uuid4())).args[2])["counter"] == 2
    assert json.loads((exports / "main_00002" / "sequence.json").read_text())["entries"][0]["frames"] == [0, 204]

    # Concurrent exports never share a version.
    counters: List[int] = []
    workers = [
        threading.Thread(target=lambda: counters.append(json.loads(export(entries, str(uuid.uuid4())).args[2])["counter"]))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert sorted(counters) == [3, 4]

    # An interrupted export publishes nothing and keeps earlier versions and sources.
    before = listing(output)
    with monkeypatch.context() as patch:
        patch.setattr(
            comfy.model_management,
            "throw_exception_if_processing_interrupted",
            lambda: (_ for _ in ()).throw(comfy.model_management.InterruptProcessingException()),
        )
        with pytest.raises(comfy.model_management.InterruptProcessingException):
            export(entries, str(uuid.uuid4()))
    assert listing(output) == before
    # A film that does not match its plan is never published.
    with monkeypatch.context() as patch:
        patch.setattr(video_jobs, "count_samples", lambda *args: 1)
        with pytest.raises(video_jobs.MediaToolError):
            export(entries, str(uuid.uuid4()))
    assert listing(output) == before

    # A replaced source asks for reselection instead of exporting different footage.
    replaced = output / records[1]["video"]["path"]
    replaced.write_bytes(replaced.read_bytes())
    with pytest.raises(ExportRefused, match="entry 2"):
        export(entries, str(uuid.uuid4()))
    with pytest.raises(ExportRefused):
        export([{**item, "included": False} for item in entries], str(uuid.uuid4()))
    assert listing(output) == before
    assert isinstance(ArisuAssembleVideo.validate_inputs(edit_json="{}"), str)
    assert isinstance(ArisuAssembleVideo.validate_inputs(export_request="not-a-job"), str)
    assert ArisuAssembleVideo.validate_inputs(edit_json=json.dumps({"version": 1, "output": None, "entries": entries})) is True


def test_assemble_video_conforms_mixed_sources_in_one_encode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    output = tmp_path / "output"
    monkeypatch.setattr(folder_paths, "output_directory", str(output))
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    first = take(output, 48)
    # A legacy video has no record and no PCM: only its embedded AAC, with encoder delay and padding.
    legacy = take(output, 48, name="legacy")
    shutil.rmtree(output / PROJECT / "videos" / "legacy_00001_.arisu")
    silent = take(output, 24, sound=False, name="silent")
    wide = take(output, 48, rate=48000, name="wide")
    other = take(output, 48, codec="h265", name="other")
    basis = {"prev_revision": wide["video"]["revision"], "prev_end": 48, "revision": other["video"]["revision"], "start": 0}
    correction = {"luma_gain": 1.0, "luma_offset": 0.05, "cb_offset": 0.0, "cr_offset": 0.0, "taper": 12, "basis": basis}
    entries = [
        entry(first),
        # The user marked two leading frames of this source as overlap; its sound is cut at the same time.
        entry(legacy, take="", source="file", range=[2, 48]),
        entry(silent),
        entry(wide),
        entry(other, join={"correction": correction, "fade": 10}),
    ]
    spec = {"width": 64, "height": 64, "fps": [24, 1], "sample_rate": 32000, "channels": 2}

    # Mixed codecs and sample rates have no single inherited target: export waits for explicit choices.
    with pytest.raises(ExportRefused, match="confirm output"):
        export(entries, str(uuid.uuid4()))
    with pytest.raises(ExportRefused, match="choose codec"):
        export(entries, str(uuid.uuid4()), spec)
    # A correction approved for other neighbours must be previewed again.
    stale = [*entries[:4], entry(other, join={"correction": {**correction, "basis": {**basis, "prev_end": 47}}, "fade": 0})]
    with pytest.raises(ExportRefused, match="refresh correction"):
        export(stale, str(uuid.uuid4()), spec, encoding="encode")
    # An encoder missing from an existing native build is named; the codec choice is not changed silently.
    with monkeypatch.context() as patch:
        tools = video_jobs.detect_tools()
        patch.setattr(nodes, "detect_tools", lambda: replace(tools, encoders=tools.encoders - {"libx264"}))
        with pytest.raises(ExportRefused, match="no h264 encoder"):
            export(entries, str(uuid.uuid4()), spec, encoding="encode")
    assert not (output / PROJECT / "exports").exists() or not list((output / PROJECT / "exports").iterdir())

    done = export(entries, str(uuid.uuid4()), spec, encoding="encode", codec="h264", crf=16)
    record = json.loads(done.args[2])
    assert (record["video"]["operation"], record["video"]["encoder"], record["video"]["crf"]) == ("encode", "libx264", 16)
    assert [item["frames"] for item in record["entries"]] == [[0, 48], [48, 94], [94, 118], [118, 166], [166, 214]]
    assert [item["audio"]["source"] for item in record["entries"]] == ["pcm", "embedded", "none", "pcm", "pcm"]
    film = output / record["film"]["path"]
    seen = read_markers(film)
    assert seen["frames"] == 214 and seen["samples"] == record["audio"]["samples"] == 285333
    # Every following segment starts on its planned frame: the trimmed source shows its flash two frames earlier.
    assert seen["flashes"] == [6, 48 + 4, 94 + 6, 118 + 6, 166 + 6]
    # Sound follows the same boundaries: the head trim moves its click, the silent slot is empty, 48 kHz is resampled.
    planned = [8000, 64000 + 8000 - 2667, 157333 + 8000, 221333 + 8000]
    assert len(seen["clicks"]) == 4 and all(abs(found - click) <= 24 for found, click in zip(seen["clicks"], planned))
    # The correction lifts the opening frames of the last take and tapers away; frame count and sound position stay.
    with av.open(str(film)) as container:
        levels = [float(frame.to_ndarray(format="gray").mean()) for frame in container.decode(container.streams.video[0])]
    assert levels[166] > levels[165] + 5 and levels[166] > levels[171] > levels[180] and abs(levels[180] - levels[165]) < 2
