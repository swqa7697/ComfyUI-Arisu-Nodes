"""Execute-level tests for the MiniMax H3 context latent resize node with a stub VAE.

The stub decodes and encodes zero tensors of the right shapes, so these tests
check the container round trip, the pixel-space path, and the refusals without
loading any model. Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import comfy.nested_tensor
import pytest
import torch

from src.arisu_nodes.minimax_h3.nodes import ArisuMiniMaxH3ContextLatentResize
from tests.support.comfy import StubVae, audio_latent, video_latent

pytestmark = pytest.mark.comfyui


def _run(
    latent: Dict[str, Any], vae: Optional[StubVae] = None, width: int = 864, height: int = 480, crop: str = "disabled"
) -> Dict[str, Any]:
    return ArisuMiniMaxH3ContextLatentResize.execute(latent=latent, vae=vae or StubVae(), width=width, height=height, crop=crop)[0]


def test_containers_round_trip_with_resized_video_and_untouched_extras():
    video, audio = video_latent(), audio_latent()
    vae = StubVae()

    out = _run({"samples": [video, audio]}, vae)

    assert isinstance(out["samples"], list)
    assert tuple(out["samples"][0].shape) == (1, 24, 7, 30, 54)
    assert out["samples"][1] is audio
    assert len(vae.decoded) == 1 and vae.decoded[0] is video
    assert len(vae.encoded) == 1
    assert tuple(vae.encoded[0].shape) == (22, 480, 864, 3)

    # a nested pair comes back nested, with the audio stream passed through
    latent = {"samples": comfy.nested_tensor.NestedTensor((video_latent(), audio_latent()))}
    out = _run(latent)
    assert out["samples"].is_nested
    assert tuple(out["samples"].tensors[0].shape) == (1, 24, 7, 30, 54)
    assert out["samples"].tensors[1] is latent["samples"].tensors[1]

    # other latent keys survive untouched
    mask = torch.ones(1, 1, 8, 8)
    out = _run({"samples": [video_latent(), audio_latent()], "noise_mask": mask})
    assert out["noise_mask"] is mask


def test_matching_size_returns_the_input_without_touching_the_vae():
    latent = {"samples": [video_latent(), audio_latent()]}
    vae = StubVae()

    out = _run(latent, vae, width=1344, height=768)

    assert out is latent
    assert vae.decoded == [] and vae.encoded == []


def test_pixels_reach_the_vae_per_batch_item_with_crop_forwarded():
    vae = StubVae()

    out = _run({"samples": [video_latent(batch=2), audio_latent(batch=2)]}, vae)

    assert tuple(out["samples"][0].shape) == (2, 24, 7, 30, 54)
    assert [pixels.ndim for pixels in vae.encoded] == [4, 4]

    # a center crop changes the pixel canvas the VAE sees
    vae = StubVae()
    _run({"samples": [video_latent(), audio_latent()]}, vae, width=480, height=480, crop="center")
    assert tuple(vae.encoded[0].shape) == (22, 480, 480, 3)


def test_rejects_latents_and_sizes_before_touching_the_vae():
    cases = [
        ({"samples": [video_latent(latent_t=8), audio_latent()]}, {}, "5k\\+2"),
        ({"samples": [video_latent(), audio_latent(), audio_latent()]}, {}, "two streams"),
        ({"samples": [torch.rand(1, 16, 7, 48, 84), audio_latent()]}, {}, "video latent"),
        ({"samples": torch.rand(1, 24, 7, 48, 84)}, {}, "nested video/audio pair"),
        ({"samples": [video_latent(), audio_latent()]}, {"width": 1000}, "multiples of 16"),
    ]
    for latent, overrides, match in cases:
        vae = StubVae()
        with pytest.raises(ValueError, match=match):
            _run(latent, vae, **overrides)
        assert vae.decoded == [] and vae.encoded == [], f"case={match!r}"


def test_refuses_when_the_vae_changes_the_temporal_length():
    with pytest.raises(RuntimeError, match="temporal grid"):
        _run({"samples": [video_latent(), audio_latent()]}, StubVae(encode_latent_t=6))
