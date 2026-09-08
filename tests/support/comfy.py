"""ComfyUI-shaped fakes: the CLIP and VAE objects the MiniMax H3 nodes call, plus tensor builders.

The stubs return zero tensors of the right shapes and record what they were
handed, so execute-level tests can check payloads and geometry without loading
a model. This module imports torch, so only ``tests/comfyui/`` may import it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import torch

from src.arisu_nodes.minimax_h3.core import video_frame_count, video_latent_t


class StubClip:
    """Records the tokenizer kwargs and returns one zero conditioning block."""

    def __init__(self):
        self.tokenize_kwargs: Dict[str, Any] = {}

    def tokenize(self, text: str, **kwargs: Any) -> Dict[str, Any]:
        self.tokenize_kwargs = kwargs
        return {"text": text}

    def encode_from_tokens_scheduled(self, tokens: Dict[str, Any]) -> List[List[Any]]:
        return [[torch.zeros(1, 4, 8), {}]]


class StubVae:
    """Encodes ``[F, H, W, 3]`` to ``[1, 24, T, H/16, W/16]`` and decodes it back to pixels.

    Args:
        encode_latent_t: Forces the temporal length ``encode`` returns; ``None``
            derives it from the frame count (one frame encodes to one latent frame).
    """

    def __init__(self, encode_latent_t: Optional[int] = None):
        self.encoded: List[torch.Tensor] = []
        self.decoded: List[torch.Tensor] = []
        self.encode_latent_t = encode_latent_t

    def encode(self, pixels: torch.Tensor) -> torch.Tensor:
        self.encoded.append(pixels)
        frames, height, width = pixels.shape[0], pixels.shape[1], pixels.shape[2]
        if self.encode_latent_t is not None:
            latent_t = self.encode_latent_t
        else:
            latent_t = 1 if frames == 1 else video_latent_t(frames)
        return torch.zeros(1, 24, latent_t, height // 16, width // 16)

    def decode(self, video: torch.Tensor) -> torch.Tensor:
        self.decoded.append(video)
        batch, _, latent_t, latent_h, latent_w = video.shape
        return torch.zeros(batch, video_frame_count(latent_t), latent_h * 16, latent_w * 16, 3)


class StubAudioVae:
    """Encodes any waveform to a fixed ``[1, 32, 2, 40]`` audio latent."""

    audio_sample_rate = 32000

    def encode(self, waveform: torch.Tensor) -> torch.Tensor:
        return torch.zeros(1, 32, 2, 40)


def image(height: int, width: int, channels: int = 3) -> torch.Tensor:
    """A one-image batch ``[1, H, W, C]`` of random pixels."""
    return torch.rand(1, height, width, channels)


def audio_input() -> Dict[str, Any]:
    """One second of stereo silence in ComfyUI's AUDIO dict shape."""
    return {"waveform": torch.zeros(1, 2, 32000), "sample_rate": 32000}


def video_latent(batch: int = 1, latent_t: int = 7, height: int = 768, width: int = 1344) -> torch.Tensor:
    """A random H3 video latent ``[B, 24, T, H/16, W/16]`` for a pixel canvas."""
    return torch.rand(batch, 24, latent_t, height // 16, width // 16)


def audio_latent(batch: int = 1) -> torch.Tensor:
    """A random H3 audio latent ``[B, 32, 2, 37]``."""
    return torch.rand(batch, 32, 2, 37)
