"""Execute-level tests for the MiniMax H3 context latent resize node with a stub VAE.

The stub decodes and encodes zero tensors of the right shapes, so these tests
check the container round trip, the pixel-space path, and the refusals without
loading any model. Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import comfy.nested_tensor
import pytest
import torch

from src.arisu_nodes.minimax_h3.core import video_frame_count, video_latent_t
from src.arisu_nodes.minimax_h3.nodes import ArisuMiniMaxH3ContextLatentResize

pytestmark = pytest.mark.comfyui


class _StubVae:
    """Decodes ``[B, 24, T, h, w]`` to ``[B, F, 16h, 16w, 3]`` and encodes ``[F, H, W, 3]`` back."""

    def __init__(self, encode_latent_t: Optional[int] = None) -> None:
        self.decoded: List[torch.Tensor] = []
        self.encoded: List[torch.Tensor] = []
        self.encode_latent_t = encode_latent_t

    def decode(self, video: torch.Tensor) -> torch.Tensor:
        self.decoded.append(video)
        batch, _, latent_t, latent_h, latent_w = video.shape
        return torch.zeros(batch, video_frame_count(latent_t), latent_h * 16, latent_w * 16, 3)

    def encode(self, pixels: torch.Tensor) -> torch.Tensor:
        self.encoded.append(pixels)
        frames, height, width = pixels.shape[0], pixels.shape[1], pixels.shape[2]
        latent_t = self.encode_latent_t if self.encode_latent_t is not None else video_latent_t(frames)
        return torch.zeros(1, 24, latent_t, height // 16, width // 16)


def _video(batch: int = 1, latent_t: int = 7, height: int = 768, width: int = 1344) -> torch.Tensor:
    return torch.rand(batch, 24, latent_t, height // 16, width // 16)


def _audio(batch: int = 1) -> torch.Tensor:
    return torch.rand(batch, 32, 2, 37)


def _run(latent: Dict[str, Any], vae: Optional[_StubVae] = None, width: int = 864, height: int = 480, crop: str = "disabled") -> Any:
    return ArisuMiniMaxH3ContextLatentResize.execute(latent=latent, vae=vae or _StubVae(), width=width, height=height, crop=crop).result[0]


def test_list_latent_comes_back_as_a_list_with_resized_video_and_untouched_audio():
    video, audio = _video(), _audio()
    vae = _StubVae()

    out = _run({"samples": [video, audio]}, vae)

    assert isinstance(out["samples"], list)
    assert tuple(out["samples"][0].shape) == (1, 24, 7, 30, 54)
    assert out["samples"][1] is audio
    assert len(vae.decoded) == 1 and vae.decoded[0] is video
    assert len(vae.encoded) == 1
    assert tuple(vae.encoded[0].shape) == (22, 480, 864, 3)


def test_nested_latent_comes_back_nested():
    latent = {"samples": comfy.nested_tensor.NestedTensor((_video(), _audio()))}

    out = _run(latent)

    assert out["samples"].is_nested
    assert tuple(out["samples"].tensors[0].shape) == (1, 24, 7, 30, 54)
    assert out["samples"].tensors[1] is latent["samples"].tensors[1]


def test_extra_latent_keys_survive():
    mask = torch.ones(1, 1, 8, 8)

    out = _run({"samples": [_video(), _audio()], "noise_mask": mask})

    assert out["noise_mask"] is mask


def test_matching_size_returns_the_input_without_touching_the_vae():
    latent = {"samples": [_video(), _audio()]}
    vae = _StubVae()

    out = _run(latent, vae, width=1344, height=768)

    assert out is latent
    assert vae.decoded == [] and vae.encoded == []


def test_batch_items_are_encoded_one_by_one_as_image_batches():
    vae = _StubVae()

    out = _run({"samples": [_video(batch=2), _audio(batch=2)]}, vae)

    assert tuple(out["samples"][0].shape) == (2, 24, 7, 30, 54)
    assert [pixels.ndim for pixels in vae.encoded] == [4, 4]


def test_center_crop_is_forwarded_to_the_resize():
    vae = _StubVae()

    _run({"samples": [_video(), _audio()]}, vae, width=480, height=480, crop="center")

    assert tuple(vae.encoded[0].shape) == (22, 480, 480, 3)


@pytest.mark.parametrize(
    ("samples", "match"),
    [
        ([_video(latent_t=8), _audio()], "5k\\+2"),
        ([_video(), _audio(), _audio()], "two streams"),
        ([torch.rand(1, 16, 7, 48, 84), _audio()], "video latent"),
        (torch.rand(1, 24, 7, 48, 84), "nested video/audio pair"),
    ],
)
def test_rejects_latents_that_are_not_an_h3_av_pair(samples, match):
    with pytest.raises(ValueError, match=match):
        _run({"samples": samples})


def test_rejects_sizes_off_the_16_grid_before_touching_the_vae():
    vae = _StubVae()
    with pytest.raises(ValueError, match="multiples of 16"):
        _run({"samples": [_video(), _audio()]}, vae, width=1000, height=480)
    assert vae.decoded == []


def test_refuses_when_the_vae_changes_the_temporal_length():
    with pytest.raises(RuntimeError, match="temporal grid"):
        _run({"samples": [_video(), _audio()]}, _StubVae(encode_latent_t=6))
