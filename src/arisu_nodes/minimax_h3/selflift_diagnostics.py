"""Optional memory snapshots without resetting shared allocator statistics."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import folder_paths
import psutil
import torch
from comfy.sd import VAE
from PIL import Image

from ..common.core import contained_path

_LOGGER = logging.getLogger(__name__)


def log_memory(label: str, device: torch.device):
    """Report process, system and CUDA memory when diagnostics are enabled."""
    if os.environ.get("SELFLIFT_MEMORY_LOG", "0") != "1":
        return
    device = torch.device(device)
    fields = []
    try:
        fields.append(f"process_rss={psutil.Process().memory_info().rss / 2**20:.2f} MiB")
        fields.append(f"system_available={psutil.virtual_memory().available / 2**20:.2f} MiB")
    except (psutil.Error, OSError) as error:
        fields.append(f"host_memory_unavailable={error}")
    if device.type == "cuda" and torch.cuda.is_initialized():
        try:
            free, total = torch.cuda.mem_get_info(device)
            fields.extend(
                [
                    f"allocated={torch.cuda.memory_allocated(device) / 2**20:.2f} MiB",
                    f"reserved={torch.cuda.memory_reserved(device) / 2**20:.2f} MiB",
                    f"process_peak_allocated={torch.cuda.max_memory_allocated(device) / 2**20:.2f} MiB",
                    f"device_used={((total - free) / 2**20):.2f} MiB",
                    f"device_free={free / 2**20:.2f} MiB",
                ]
            )
        except RuntimeError as error:
            fields.append(f"cuda_memory_unavailable={error}")
    _LOGGER.info("[SelfLift memory] %s device=%s; %s", label, device, "; ".join(fields))


class StageTimer:
    """Time a sampling stage with optional CUDA synchronization."""

    def __init__(self, stage: str, device: torch.device, resolution: Optional[Tuple[int, int]] = None, pixel_scale: int = 1):
        self.stage = stage
        self.resolution = resolution
        self.pixel_scale = pixel_scale
        self.device = torch.device(device)
        self.synchronize = os.environ.get("SELFLIFT_TIMING_SYNC", "0") == "1" and self.device.type == "cuda"
        self.started = self.previous = self._now()
        timing_mode = "CUDA-synchronized wall time" if self.synchronize else "wall time; no forced CUDA sync"
        suffix = ""
        if resolution is not None:
            pixels = tuple(int(value * self.pixel_scale) for value in resolution)
            suffix = f" latent={resolution} pixels={pixels}"
        _LOGGER.info("[SelfLift timing] %s start (%s)%s", stage, timing_mode, suffix)

    def _now(self) -> float:
        if self.synchronize:
            torch.cuda.synchronize(self.device)
        return time.perf_counter()

    def mark(self, label: str):
        current = self._now()
        _LOGGER.info("[SelfLift timing] %s %s: %.3fs", self.stage, label, current - self.previous)
        self.previous = current

    def finish(self):
        current = self._now()
        _LOGGER.info(
            "[SelfLift timing] %s total: %.3fs; after last mark: %.3fs", self.stage, current - self.started, current - self.previous
        )


def debug_dump(vae: VAE, latents: Dict[str, Optional[torch.Tensor]]):
    """Decode transition intermediates to PNGs when SELFLIFT_DEBUG=1."""
    if os.environ.get("SELFLIFT_DEBUG", "0") != "1":
        return
    temp_dir = folder_paths.get_temp_directory()
    os.makedirs(temp_dir, exist_ok=True)
    out_dir = Path(tempfile.mkdtemp(prefix="arisu-selflift-", dir=temp_dir))
    _LOGGER.warning("SelfLift: debug decoding enabled; intermediate video decodes can substantially increase time and memory")
    _LOGGER.info("[SelfLift debug] Saving transition frames to %s", out_dir)
    for name, lat in latents.items():
        if lat is None:
            continue
        img = vae.decode(lat)
        if img.ndim == 5:
            img = img.reshape(-1, img.shape[-3], img.shape[-2], img.shape[-1])
        frame = (img[0].float().cpu().numpy().clip(0.0, 1.0) * 255).round().astype("uint8")
        with open(contained_path(temp_dir, f"{out_dir.name}/{name}.png"), "xb") as output:
            Image.fromarray(frame).save(output, format="PNG")
