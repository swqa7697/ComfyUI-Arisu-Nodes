"""Execute-level tests for Save Video Segment on the native FFmpeg backend. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

import json
import os
import shutil
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import av
import comfy.model_management
import folder_paths
import numpy as np
import pytest
import torch
from comfy_api.latest import InputImpl, Types

from src.arisu_nodes.common import nodes
from src.arisu_nodes.common.nodes import ArisuSaveVideoSegment
from src.arisu_nodes.common.video_jobs import MediaToolError
from tests.support.media import marker_clip, read_markers

pytestmark = pytest.mark.comfyui

TAKE = "552564c1-1999-442e-a016-c1965b957d62"


def clip(frames: int = 36, sound: bool = True, noise: bool = False, **markers: Any) -> Any:
    """A 24 fps VIDEO held in memory, as Create Video delivers it with codec ``none``."""
    images, waveform = marker_clip(frames, 32000, **markers)
    pixels = torch.rand(frames, 64, 64, 3) if noise else torch.from_numpy(images)
    audio = {"waveform": torch.from_numpy(waveform)[None], "sample_rate": 32000} if sound else None
    return InputImpl.VideoFromComponents(Types.VideoComponents(images=pixels, audio=audio, frame_rate=Fraction(24)))


def save(video: Any, **inputs: Any) -> Dict[str, Any]:
    values = {"project_prefix": "", "clip_name": "clip", "codec": "h264", "crf": 18, "take_context": ""}
    return ArisuSaveVideoSegment.execute(video=video, **{**values, **inputs}).ui


def record(output: Path, ui: Dict[str, Any]) -> Dict[str, Any]:
    saved = ui["images"][0]
    stem = saved["filename"][: -len(".mp4")]
    return json.loads((output / saved["subfolder"] / f"{stem}.arisu" / "take.json").read_text())


def tree(root: Path) -> Dict[str, Optional[int]]:
    return {str(path.relative_to(root)): None if path.is_dir() else path.lstat().st_size for path in sorted(root.rglob("*"))}


def test_save_video_segment_publishes_measured_takes_and_leaves_nothing_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    output = tmp_path / "output"
    monkeypatch.setattr(folder_paths, "output_directory", str(output))
    monkeypatch.setattr(
        ArisuSaveVideoSegment, "hidden", SimpleNamespace(prompt={"1": {"class_type": "x"}}, extra_pnginfo={"workflow": {"n": 1}})
    )
    project = "films/夜 shoot"
    # A flash on frame 6 and a click at sample 8000 both sit at 0.250 s.
    video = clip(flashes=[6], clicks=[8000])

    ui = save(video, project_prefix=project, clip_name="shot")
    # The stock Save Video receipt shape is what Director and the history preview read.
    assert ui["images"] == [{"filename": "shot_00001_.mp4", "subfolder": f"{project}/videos", "type": "output"}]
    first = record(output, ui)
    assert ui["arisu_take"][0]["take"] == first["take"] and ui["arisu_take"][0]["frames"] == 36
    assert first["project"] == project and first["origin"] == "ordinary"
    assert (first["video"]["frames"], first["video"]["fps"], first["video"]["codec"]) == (36, [24, 1], "h264")
    assert first["video"]["path"] == f"{project}/videos/shot_00001_.mp4" and first["audio"]["samples"] == 48000
    film = output / first["video"]["path"]
    seen = read_markers(film)
    assert seen["frames"] == 36 and seen["flashes"] == [6] and seen["times"] == [0.25]
    # The playable track is trimmed to its valid samples: the decoder delivers exactly the picture's duration.
    assert seen["samples"] == first["audio"]["embedded"]["samples"] == 48000 and abs(seen["clicks"][0] - 8000) <= 8
    # The PCM companion is the delivered waveform itself, sample for sample, at its native rate and layout.
    companion = (output / first["audio"]["pcm"]["path"]).read_bytes()
    assert companion[20:24] == b"\x03\x00\x02\x00" and int.from_bytes(companion[24:28], "little") == 32000
    waveform = video.get_components().audio["waveform"][0].numpy()
    assert np.array_equal(np.frombuffer(companion[-48000 * 8 :], dtype="<f4").reshape(-1, 2).T, waveform)
    with av.open(str(film)) as container:
        assert json.loads(container.metadata["prompt"]) == {"1": {"class_type": "x"}}
        assert json.loads(container.metadata["workflow"]) == {"n": 1}

    # Rendering the same segment again keeps the earlier candidate.
    second = record(output, save(video, project_prefix=project, clip_name="shot"))
    assert second["video"]["path"].endswith("shot_00002_.mp4") and second["take"] != first["take"] and film.is_file()
    # A named silent clip keeps no audio companion.
    silent = record(output, save(clip(sound=False), project_prefix=project, clip_name="h3_clip"))
    assert silent["video"]["path"].endswith("videos/h3_clip_00001_.mp4") and silent["audio"] is None
    assert not (output / project / "videos" / "h3_clip_00001_.arisu" / "audio.wav").exists()
    assert record(output, save(clip(sound=False)))["video"]["path"] == "arisu_video/videos/clip_00001_.mp4"
    # A Director take directory names the take; the latent slot beside it does not take a counter.
    staged = output / project / "director" / TAKE
    staged.mkdir(parents=True)
    (staged / "clip_00001.safetensors").write_bytes(b"latent")
    context = json.dumps({"take": TAKE, "segment": "s2", "predecessor": None, "transition": "cut"})
    directed = record(output, save(video, project_prefix=project, take_context=context))
    assert (directed["take"], directed["origin"], directed["segment"]) == (TAKE, "director", "s2")
    assert directed["video"]["path"].endswith(f"director/{TAKE}/clip_00001_.mp4")

    unscoped = record(output, save(video, take_context=context))
    assert unscoped["project"] is None and unscoped["video"]["path"] == f"arisu_director/{TAKE}/clip_00001_.mp4"

    # A new Director render publishes one unnumbered, resumable take with its immutable segment identity.
    identity = {"uid": "adee7502-21a3-474d-8b60-e2952dcb5523", "order": 2, "title": "Cross the bridge"}
    current = json.dumps({**json.loads(context), "identity": identity})
    streams = [torch.zeros(1, 4, 2, 2, 2), torch.ones(1, 2, 3)]
    options = {"project_prefix": "film", "take_context": current, "director_latent": {"samples": streams}}
    result = save(video, **options)
    modern = record(output, result)
    assert modern["identity"] == identity and modern["video"]["path"] == f"film/director/{TAKE}/clip.mp4"
    latent = result["latents"][0]
    restored = comfy.utils.load_torch_file(str(output / latent["subfolder"] / latent["filename"]))
    assert all(torch.equal(restored[name], tensor) for name, tensor in zip(("video", "audio"), streams))
    with pytest.raises(FileExistsError):
        save(video, **options)
    assert record(output, result) == modern

    # Each encoder honours its own CRF scale: a lower value keeps more of a noisy picture.
    sizes = {}
    for codec, low, high in (("h264", 14, 40), ("h265", 14, 40), ("av1", 20, 55)):
        for crf in (low, high):
            saved = record(output, save(clip(12, sound=False, noise=True), project_prefix="codecs", clip_name=codec, codec=codec, crf=crf))
            sizes[codec, crf] = saved["video"]["size"]
            with av.open(str(output / saved["video"]["path"])) as container:
                assert container.streams.video[0].codec_context.name in (codec, "hevc", "libdav1d"), codec
        assert sizes[codec, low] > sizes[codec, high], codec

    # Refusals happen before anything is written, and never outside output.
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "escape").symlink_to(outside)
    before = tree(tmp_path)
    for inputs in (
        {"project_prefix": "../films"},
        {"project_prefix": "/abs"},
        {"project_prefix": "escape"},
        {"project_prefix": "escape", "take_context": context},
        {"clip_name": "a/b"},
        {"codec": "h264", "crf": 52},
        {"codec": "prores"},
        {"take_context": "{}"},
        {"take_context": json.dumps({**json.loads(context), "take": "../escape"})},
        {"filename_prefix": "old/prefix"},
    ):
        with pytest.raises((TypeError, ValueError)):
            save(video, **inputs)
        assert tree(tmp_path) == before, inputs
    assert ArisuSaveVideoSegment.validate_inputs(codec="av1", crf=63) is True
    assert isinstance(ArisuSaveVideoSegment.validate_inputs(codec="h265", crf=63), str)
    assert isinstance(ArisuSaveVideoSegment.validate_inputs(project_prefix="..", clip_name="a"), str)

    # A name already at the next number is a collision, even as a dangling symlink: it is neither followed nor replaced.
    videos = output / project / "videos"
    (videos / "shot_00003_.mp4").symlink_to(outside / "planted.mp4")
    assert record(output, save(video, project_prefix=project, clip_name="shot"))["video"]["path"].endswith("shot_00004_.mp4")
    assert not (outside / "planted.mp4").exists()

    # An interrupt or an encoder failure publishes nothing and removes only this job's files.
    before = tree(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            comfy.model_management,
            "throw_exception_if_processing_interrupted",
            lambda: (_ for _ in ()).throw(comfy.model_management.InterruptProcessingException()),
        )
        with pytest.raises(comfy.model_management.InterruptProcessingException):
            save(video, project_prefix=project, clip_name="shot")
    assert tree(tmp_path) == before
    with monkeypatch.context() as patch:
        broken = nodes.encode_take_argv
        patch.setattr(nodes, "encode_take_argv", lambda *args, **kwargs: [*broken(*args, **kwargs)[:-1], os.devnull + "/missing.mp4"])
        with pytest.raises(MediaToolError):
            save(video, project_prefix=project, clip_name="shot")
    assert tree(tmp_path) == before
