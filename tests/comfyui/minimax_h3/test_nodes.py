"""Execute-level tests for the MiniMax H3 hybrid node with stub CLIP and VAEs.

The stubs return zero tensors of the right shapes, so these tests check the
conditioning payload (keys, ordering, dict shapes) and the latent geometry
without loading any model. Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import torch

from src.arisu_nodes.minimax_h3.core import video_latent_t
from src.arisu_nodes.minimax_h3.nodes import ArisuMiniMaxH3HybridToVideo

pytestmark = pytest.mark.comfyui


class _StubClip:
    def __init__(self) -> None:
        self.tokenize_kwargs: Dict[str, Any] = {}

    def tokenize(self, text: str, **kwargs: Any) -> Dict[str, Any]:
        self.tokenize_kwargs = kwargs
        return {"text": text}

    def encode_from_tokens_scheduled(self, tokens: Dict[str, Any]) -> List[List[Any]]:
        return [[torch.zeros(1, 4, 8), {}]]


class _StubVae:
    def encode(self, pixels: torch.Tensor) -> torch.Tensor:
        frames, height, width = pixels.shape[0], pixels.shape[1], pixels.shape[2]
        latent_t = 1 if frames == 1 else video_latent_t(frames)
        return torch.zeros(1, 24, latent_t, height // 16, width // 16)


class _StubAudioVae:
    audio_sample_rate = 32000

    def encode(self, waveform: torch.Tensor) -> torch.Tensor:
        return torch.zeros(1, 32, 2, 40)


def _image(height: int, width: int) -> torch.Tensor:
    return torch.rand(1, height, width, 3)


def _audio() -> Dict[str, Any]:
    return {"waveform": torch.zeros(1, 2, 32000), "sample_rate": 32000}


def _run(**overrides: Any) -> Any:
    kwargs: Dict[str, Any] = {
        "clip": _StubClip(),
        "vae": _StubVae(),
        "prompt": "a test",
        "width": 1344,
        "height": 768,
        "length": 124,
        "ref_image_size": "match",
        "frame_picture_tags": "after_refs",
    }
    kwargs.update(overrides)
    return kwargs["clip"], ArisuMiniMaxH3HybridToVideo.execute(**kwargs)


def _cond_values(result: Any) -> Dict[str, Any]:
    (cond, _latent) = result.result
    assert len(cond) == 1
    return cond[0][1]


def test_first_and_last_frames_only_pin_keyframes():
    clip, result = _run(first_frame=_image(768, 1344), last_frame=_image(1080, 1920), frame_picture_tags="none")

    values = _cond_values(result)
    assert [kf["resolved_frame_index"] for kf in values["minimax_keyframes"]] == [0, 123]
    for kf in values["minimax_keyframes"]:
        assert kf["latent"].shape == (1, 24, 1, 48, 84)
        assert "image" not in kf
    assert "minimax_refs" not in values
    assert clip.tokenize_kwargs == {"minimax_ref_items": []}

    samples = result.result[1]["samples"]
    assert samples.is_nested
    assert tuple(samples.tensors[0].shape) == (1, 24, 37, 48, 84)
    assert tuple(samples.tensors[1].shape) == (1, 32, 2, 207)


def test_frames_after_refs_keeps_reference_numbering():
    first = _image(768, 1344)
    ref_images = {"ref_image_0": _image(512, 512), "ref_image_1": _image(256, 1024)}
    clip, result = _run(first_frame=first, ref_images=ref_images, frame_picture_tags="after_refs")

    items = clip.tokenize_kwargs["minimax_ref_items"]
    assert [item["type"] for item in items] == ["image", "image", "image"]
    assert tuple(items[0]["data"].shape) == (1, 512, 512, 3)
    assert tuple(items[1]["data"].shape) == (1, 256, 1024, 3)
    assert tuple(items[2]["data"].shape) == (1, 768, 1344, 3)

    values = _cond_values(result)
    refs = values["minimax_refs"]
    # frames never add reference blocks; they reach the model as keyframes only
    assert [ref["kind"] for ref in refs] == ["image", "image"]
    assert (refs[0]["latent_h"], refs[0]["latent_w"]) == (32, 32)
    assert (refs[1]["latent_h"], refs[1]["latent_w"]) == (16, 64)
    assert len(values["minimax_keyframes"]) == 1


def test_frames_before_refs_numbers_frames_first():
    clip, _result = _run(first_frame=_image(768, 1344), ref_images={"ref_image_0": _image(512, 512)}, frame_picture_tags="before_refs")

    items = clip.tokenize_kwargs["minimax_ref_items"]
    assert [tuple(item["data"].shape) for item in items] == [(1, 768, 1344, 3), (1, 512, 512, 3)]


def test_ref_video_with_soundtrack_and_standalone_audio():
    clip, result = _run(
        audio_vae=_StubAudioVae(),
        ref_videos={"ref_video_0": torch.rand(30, 360, 640, 3)},
        ref_video_audios={"ref_video_audio_0": _audio()},
        ref_audios={"ref_audio_0": _audio()},
    )

    items = clip.tokenize_kwargs["minimax_ref_items"]
    # soundtrack label before its video, standalone audio last
    assert [item["type"] for item in items] == ["audio", "video", "audio"]
    assert tuple(items[1]["data"].shape) == (2, 352, 640, 3)
    assert items[1]["timestamps"] == [0.0, 0.5]

    refs = _cond_values(result)["minimax_refs"]
    assert [ref["kind"] for ref in refs] == ["video_audio", "audio"]
    assert refs[0]["latent_t"] == video_latent_t(22)
    assert (refs[0]["latent_h"], refs[0]["latent_w"], refs[0]["ref_audio_t"]) == (22, 40, 40)
    assert "latent" not in refs[1]
    assert refs[1]["ref_audio_t"] == 40


def test_ref_audio_without_audio_vae_is_rejected():
    with pytest.raises(ValueError, match="audio_vae"):
        _run(ref_audios={"ref_audio_0": _audio()})


def test_too_short_ref_video_is_rejected():
    with pytest.raises(ValueError, match="at least 5 frames"):
        _run(ref_videos={"ref_video_0": torch.rand(3, 360, 640, 3)})
