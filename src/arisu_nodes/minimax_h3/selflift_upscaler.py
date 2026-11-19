"""Run the SelfLift video transition through ComfyUI's learned MiniMax H3 upscaler."""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import comfy.model_management
import comfy.model_patcher
import comfy.ops
import comfy.utils
import folder_paths
import torch

from .selflift_diagnostics import log_memory

_LOGGER = logging.getLogger(__name__)
_FOLDER = "latent_upscale_models"
_model_cache: Dict[Tuple[str, str], comfy.model_patcher.CoreModelPatcher] = {}

if _FOLDER not in folder_paths.folder_names_and_paths:
    folder_paths.add_model_folder_path(_FOLDER, os.path.join(folder_paths.models_dir, _FOLDER))


def list_upscaler_models() -> List[str]:
    """List installed SelfLift checkpoint formats in ComfyUI's model directory."""
    return [name for name in folder_paths.get_filename_list(_FOLDER) if os.path.splitext(name)[1].lower() in (".pth", ".safetensors")]


def _normalize_checkpoint_dtype(state_dict: Dict[str, torch.Tensor], device: torch.device) -> Dict[str, torch.Tensor]:
    weight = state_dict.get("conv_in.weight")
    if weight is None:
        raise ValueError("SelfLift: upscaler checkpoint is missing conv_in.weight")
    if weight.dtype not in (torch.float16, torch.bfloat16, torch.float32, torch.float64) and not str(weight.dtype).startswith(
        "torch.float8_"
    ):
        raise ValueError(f"SelfLift: unsupported upscaler weight dtype {weight.dtype}")
    dtype = comfy.model_management.vae_dtype(device=device, allowed_dtypes=[torch.float16, torch.bfloat16, torch.float32])
    if any(value.is_floating_point() and value.dtype != dtype for value in state_dict.values()):
        _LOGGER.info("SelfLift: converting upscaler weights to %s", dtype)
    return {name: value.to(dtype=dtype) if value.is_floating_point() else value for name, value in state_dict.items()}


def _load_model(model_name: str, device: torch.device) -> comfy.model_patcher.CoreModelPatcher:
    # Only learned lifts need a ComfyUI version with the native H3 upscaler.
    try:
        from comfy.ldm.minimax.latent_upscaler import MiniMaxH3LatentUpscaler, TemporalConv
    except ImportError as exc:
        raise RuntimeError("SelfLift learned lift requires a ComfyUI version with the native MiniMax H3 latent upscaler.") from exc

    if model_name not in list_upscaler_models():
        raise FileNotFoundError(f"SelfLift: unknown latent upscaler {model_name!r} in models/{_FOLDER}")
    path = folder_paths.get_full_path_or_raise(_FOLDER, model_name)
    key = (path, str(device))
    if key in _model_cache:
        return _model_cache[key]

    sd = comfy.utils.load_torch_file(path, safe_load=True)
    if isinstance(sd, dict) and "model" in sd:
        sd = sd["model"]
    if any(k.startswith("upscaler.") for k in sd):
        sd = {k[len("upscaler.") :]: v for k, v in sd.items() if k.startswith("upscaler.")}
    sd = _normalize_checkpoint_dtype(sd, device)

    conv = sd["conv_in.weight"]
    temporal_weight = next((weight for key, weight in sd.items() if key.endswith(".dwconv.weight")), None)
    in_blocks = sum(key.startswith("in_blocks.") and key.endswith(".in_layers.2.weight") for key in sd)
    out_blocks = sum(key.startswith("out_blocks.") and key.endswith(".in_layers.2.weight") for key in sd)
    if not in_blocks or not out_blocks:
        raise ValueError("SelfLift: H3 upscaler checkpoint is missing residual blocks")
    with torch.device("meta"):
        model = MiniMaxH3LatentUpscaler(
            in_channels=conv.shape[1],
            channels=conv.shape[0],
            in_blocks=in_blocks,
            out_blocks=out_blocks,
            temporal_kernel=temporal_weight.shape[2] if temporal_weight is not None else 5,
            dtype=conv.dtype,
            operations=comfy.ops.disable_weight_init,
        )
    if temporal_weight is None:
        # Older spatial-only checkpoint variants contain consecutive residual blocks.
        model.in_blocks = torch.nn.ModuleList(block for block in model.in_blocks if not isinstance(block, TemporalConv))
        model.out_blocks = torch.nn.ModuleList(block for block in model.out_blocks if not isinstance(block, TemporalConv))
    model.load_state_dict(sd, strict=True, assign=True)
    model.eval().requires_grad_(False)
    comfy.model_management.archive_model_dtypes(model)
    patcher = comfy.model_patcher.CoreModelPatcher(model, load_device=device, offload_device=comfy.model_management.unet_offload_device())
    _model_cache[key] = patcher
    return patcher


def learned_latent_lift(
    z0_low: torch.Tensor, out_hw: Tuple[int, int], model_name: str, device: Optional[torch.device] = None, force_unload: bool = False
) -> torch.Tensor:
    """Lift an H3 video endpoint in VAE space, preserving its batch and time axes."""
    if device is None:
        device = comfy.model_management.get_torch_device()
    log_memory("upscaler before_load", device)
    patcher = _load_model(model_name, device)
    model = patcher.model
    size = (z0_low.shape[2], *out_hw)
    try:
        if size == tuple(z0_low.shape[2:]):
            return z0_low.to(device=comfy.model_management.intermediate_device(), dtype=torch.float32)
        memory_required = model.memory_required(z0_low.shape, size)
        _LOGGER.info(
            "[SelfLift upscaler] native MiniMax H3 model=%s dtype=%s input=%s target=%s estimated_workspace=%.2f MiB",
            model_name,
            patcher.model_dtype(),
            tuple(z0_low.shape),
            size,
            memory_required / 2**20,
        )
        comfy.model_management.load_models_gpu([patcher], memory_required=memory_required)
        log_memory("upscaler after_load", device)
        # The native model owns H3 normalization and computes group statistics across the complete clip.
        with torch.no_grad():
            out = model(z0_low.to(device=patcher.load_device, dtype=patcher.model_dtype()), size)
        log_memory("upscaler end", device)
        return out.to(device=comfy.model_management.intermediate_device(), dtype=torch.float32)
    finally:
        if force_unload:
            comfy.model_management.unload_model_and_clones(patcher, unload_additional_models=False)
            comfy.model_management.soft_empty_cache()
            log_memory("upscaler after_unload", device)
