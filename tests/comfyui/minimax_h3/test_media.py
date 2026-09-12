"""Timestamp and containment regressions with real synthetic media, without models."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.arisu_nodes.minimax_h3.core import Resource
from src.arisu_nodes.minimax_h3.media import StaleResource, metadata, read_audio, read_video, validate_source
from tests.support.media import make_audio, make_av, make_video

pytestmark = pytest.mark.comfyui


def test_timestamp_sampling_and_audio_boundaries(tmp_path: Path):
    roots = {"input": str(tmp_path)}
    for fps in (24, 25, 30):
        name = f"{fps}.mkv"
        make_video(tmp_path / name, fps=fps, seconds=6)
        item = validate_source(roots, Resource("v", "video", "input", name, clip=(1, 6)))
        frames, audio = read_video(roots, item, 124)
        assert frames.shape == (107, 64, 64, 3)
        assert audio is None
        assert abs(float(frames[0, 0, 0, 0]) * 255 - fps) < 1
        assert abs(float(frames[-1, 0, 0, 0]) * 255 - int((1 + 106 / 24) * fps)) < 2
        shorter, _ = read_video(roots, item, 22)
        assert shorter.shape[0] == 22
        with pytest.raises(ValueError, match="at least 5"):
            read_video(roots, replace(item, clip=(0, 0.1)), 124)
    make_audio(tmp_path / "sound.wav")
    sound = validate_source(roots, Resource("a", "audio", "input", "sound.wav", clip=(0.10001, 0.60001)))
    samples, rate = read_audio(roots, sound)
    assert rate == 8000 and samples.shape == (1, 1, 4000)
    assert np.allclose(samples, 0.25, atol=1 / 32768)
    # Nonzero timestamps and variable presentation intervals use timestamp containment.
    make_video(tmp_path / "variable.mkv", timestamps=[2000, 2030, 2100, 2200, 2250, 2400, 2500, 2700, 2900, 3100])
    variable = validate_source(roots, Resource("v", "video", "input", "variable.mkv", clip=(0, 0.5)))
    assert metadata(roots, variable)["duration"] == pytest.approx(1.142)
    frames, _ = read_video(roots, variable, 5)
    assert [round(float(frame[0, 0, 0]) * 255) for frame in frames] == [0, 1, 1, 2, 2]

    make_av(tmp_path / "paired.mkv")
    paired = validate_source(roots, Resource("v", "video", "input", "paired.mkv", clip=(0, 1), include_audio=True))
    assert metadata(roots, paired)["duration"] == 2
    frames, soundtrack = read_video(roots, paired, 124)
    assert len(frames) == 22 and soundtrack is not None
    waveform, rate = soundtrack
    assert rate == 8000 and waveform.shape == (1, 1, 7334)
    assert np.count_nonzero(waveform[:, :, :2000]) == 0
    assert np.allclose(waveform[:, :, 2000:], 0.25, atol=1 / 32768)
    assert read_video(roots, replace(paired, include_audio=False), 124)[1] is None


def test_media_refuses_secondary_sources_and_stale_or_escaping_locations(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    roots = {"input": str(root)}
    outside = tmp_path / "outside.wav"
    make_audio(outside)
    original = outside.read_bytes()
    make_audio(root / "safe.wav")
    safe = validate_source(roots, Resource("a", "audio", "input", "safe.wav", clip=(0, 0.5)))
    (root / "safe.wav").write_bytes(original + b"changed")
    with pytest.raises(StaleResource):
        read_audio(roots, safe)
    (root / "escape.wav").symlink_to(outside)
    for path in ("../outside.wav", "..\\outside.wav", str(outside), "escape.wav"):
        with pytest.raises((OSError, ValueError)):
            metadata(roots, Resource("a", "audio", "input", path))
    # Real decoder inputs: renamed HLS and concat documents cannot open their local/network targets.
    for name, body in (
        ("local.mp4", f"#EXTM3U\n#EXTINF:1,\n{outside}\n#EXT-X-ENDLIST\n"),
        ("remote.mp4", "#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/never\n#EXT-X-ENDLIST\n"),
        ("concat.mp4", f"ffconcat version 1.0\nfile '{outside}'\n"),
    ):
        (root / name).write_text(body)
        with pytest.raises(ValueError):
            metadata(roots, Resource("v", "video", "input", name))
    assert outside.read_bytes() == original
