"""Save Video Segment and Assemble Video on the PyAV fallback, as on a host with no ffmpeg executable."""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict

import folder_paths
import pytest
import torch
from comfy_api.latest import InputImpl, Types

from src.arisu_nodes.common import video_jobs
from src.arisu_nodes.common.nodes import ArisuAssembleVideo, ArisuSaveVideoSegment
from src.arisu_nodes.common.video_jobs import EncoderUnavailable
from src.arisu_nodes.worker import worker_command, worker_environment
from tests.support.media import marker_clip, read_markers
from tests.support.workers import assert_worker_isolated, poison_parent

pytestmark = pytest.mark.comfyui


def save(output: Path, frames: int, codec: str = "h264", crf: int = 18) -> Dict[str, Any]:
    images, waveform = marker_clip(frames, 32000, flashes=[6], clicks=[8000])
    audio = {"waveform": torch.from_numpy(waveform)[None], "sample_rate": 32000}
    video = InputImpl.VideoFromComponents(Types.VideoComponents(images=torch.from_numpy(images), audio=audio, frame_rate=Fraction(24)))
    saved = ArisuSaveVideoSegment.execute(
        video=video, project_prefix="films/fallback", clip_name=codec, filename_prefix="", codec=codec, crf=crf, take_context=""
    ).ui["images"][0]
    stem = saved["filename"][: -len(".mp4")]
    return json.loads((output / saved["subfolder"] / f"{stem}.arisu" / "take.json").read_text())


def test_missing_ffmpeg_uses_pyav_with_a_warning_and_the_same_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    output = tmp_path / "output"
    monkeypatch.setattr(folder_paths, "output_directory", str(output))
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    monkeypatch.setattr(video_jobs.shutil, "which", lambda name: None)
    marker = poison_parent(tmp_path / "poison", monkeypatch)
    caplog.set_level(logging.WARNING, logger=video_jobs.logger.name)

    records = [save(output, frames) for frames in (36, 30)]
    # Each save on the fallback path says why, which backend and which codec.
    saves = [entry for entry in caplog.records if "save" in entry.getMessage()]
    assert len(saves) == 2 and all(
        entry.levelno == logging.WARNING and "PyAV" in entry.getMessage() and "h264" in entry.getMessage() for entry in saves
    )
    assert all(record["backend"] == "pyav" for record in records)
    assert [(record["video"]["frames"], record["audio"]["samples"], record["audio"]["embedded"]["samples"]) for record in records] == [
        (36, 48000, 48000),
        (30, 40000, 40000),
    ]
    seen = read_markers(output / records[0]["video"]["path"])
    assert (seen["frames"], seen["flashes"], seen["times"], seen["samples"]) == (36, [6], [0.25], 48000) and abs(
        seen["clicks"][0] - 8000
    ) <= 8
    assert save(output, 12, "av1", 30)["video"]["codec"] == "av1"

    # An encoder the linked libraries lack is reported before any output is written.
    with monkeypatch.context() as patch:
        patch.setattr(video_jobs, "_pyav_encoder", lambda name: name != "libx265")
        before = sorted(str(path) for path in output.rglob("*"))
        with pytest.raises(EncoderUnavailable, match="h265"):
            save(output, 12, "h265", 20)
        assert sorted(str(path) for path in output.rglob("*")) == before

    entries = [
        {
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
        for record in records
    ]
    caplog.clear()
    done = ArisuAssembleVideo.execute(
        project_prefix="films/fallback",
        export_name="main",
        encoding="inherit",
        codec="h264",
        crf=18,
        edit_json=json.dumps({"version": 1, "output": None, "entries": entries}),
        export_request=str(uuid.uuid4()),
    )
    assert any("export" in entry.getMessage() and "PyAV" in entry.getMessage() for entry in caplog.records)
    record = json.loads(done.args[2])
    # The fallback cannot copy packets, so it says so and encodes once to the same frame and sample plan.
    assert (record["backend"]["name"], record["video"]["operation"]) == ("pyav", "encode") and "PyAV" in record["video"]["reason"]
    assert (record["video"]["frames"], record["audio"]["samples"]) == (66, 88000)
    seen = read_markers(output / record["film"]["path"])
    assert (seen["frames"], seen["flashes"], seen["samples"]) == (66, [6, 42], 88000)
    assert all(abs(found - planned) <= 8 for found, planned in zip(seen["clicks"], (8000, 56000))) and len(seen["clicks"]) == 2
    # Decoding of existing files ran in the isolated worker, which took nothing from the hostile parent.
    assert not marker.exists()
    assert_worker_isolated(worker_command("video"), worker_environment(), subprocess.Popen)
