"""Progressive-resolution Euler sampling for MiniMax H3.

The last low-resolution evaluation supplies both the video prediction for the
lift and the audio state for the same Euler interval. The suffix resumes at
target resolution with the original schedule and number of evaluations.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import comfy.k_diffusion.sampling
import comfy.model_management
import comfy.model_patcher
import comfy.model_sampling
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview
import torch
from comfy.sd import VAE
from comfy_extras.nodes_custom_sampler import Guider_Basic

from . import selflift_tiling
from .selflift_diagnostics import StageTimer, debug_dump, log_memory
from .selflift_guides import prepare_keyframes
from .selflift_lift import LatentLifter, artifact_aware_consistency_lift, paired_lifts

_LOGGER = logging.getLogger(__name__)

Samples = Union[torch.Tensor, comfy.nested_tensor.NestedTensor]


def _streams(samples: Samples) -> Tuple[List[torch.Tensor], bool]:
    if samples.is_nested:
        return list(samples.unbind()), True
    return [samples], False


def _pack(streams: List[torch.Tensor], nested: bool) -> Samples:
    if nested:
        return comfy.nested_tensor.NestedTensor(streams)
    return streams[0]


def _validate_sampling(model_sampling: Any, sampler: comfy.samplers.KSAMPLER):
    if not isinstance(model_sampling, comfy.model_sampling.CONST):
        raise ValueError("SelfLift requires a rectified-flow model")  # noqa: TRY004 - preserve the upstream validation contract
    if not isinstance(sampler, comfy.samplers.KSAMPLER) or sampler.sampler_function is not comfy.k_diffusion.sampling.sample_euler:
        raise ValueError("SelfLift requires the standard Euler sampler")
    if sampler.extra_options.get("s_churn", 0.0) != 0.0:
        raise ValueError("SelfLift requires Euler with s_churn=0")


def _validate_schedule(sigmas: torch.Tensor, transition_step: int):
    if sigmas.ndim != 1 or not sigmas.is_floating_point():
        raise ValueError("SelfLift: sigmas must be a one-dimensional floating-point tensor")
    if not torch.isfinite(sigmas).all() or (sigmas < 0).any():
        raise ValueError("SelfLift: sigmas must be finite and nonnegative")
    if sigmas.numel() < 2:
        return
    if not isinstance(transition_step, int) or not 1 <= transition_step <= sigmas.numel() - 2:
        raise ValueError(f"SelfLift: transition_step {transition_step} out of range for {sigmas.numel() - 1} steps")
    if (sigmas[1:] > sigmas[:-1]).any():
        raise ValueError("SelfLift: sigmas must be non-increasing")
    if (sigmas[:-1] <= 0).any():
        raise ValueError("SelfLift: only the final sigma may be zero")
    if sigmas[transition_step] >= 1:
        raise ValueError("SelfLift: the high-resolution starting sigma must be less than 1")


def _validate_latent_input(latent_image: Dict[str, Any]) -> Optional[torch.Tensor]:
    """Validate the latent template; returns the normalized noise_mask or None.

    Accepted mask shapes: [B, H, W], [B, 1, H, W], [B, 1, T, H, W] (1 = generate,
    0 = keep the original content). Spatial dimensions are resized to match the latent. A time
    length of 1 shares the mask over all frames. Normalized to [B, 1, H, W] for
    image latents and [B, 1, T|1, H, W] for video latents.
    """
    streams, _ = _streams(latent_image["samples"])
    if not streams or streams[0].ndim not in (4, 5):
        raise ValueError("SelfLift: expected a 4D image or 5D video latent size template")
    for stream in streams:
        if stream.ndim == 0 or any(size == 0 for size in stream.shape) or stream.shape[0] != streams[0].shape[0]:
            raise ValueError("SelfLift: latent streams must be nonempty and have the same batch size")
    mask = latent_image.get("noise_mask")
    if mask is None:
        return None
    video = streams[0].ndim == 5
    b, H, W = streams[0].shape[0], streams[0].shape[-2], streams[0].shape[-1]
    if mask.ndim == 3:  # [B, H, W]
        mask = mask[:, None]
    if video and mask.ndim == 4:  # [B, 1, H, W] shared over time
        mask = mask[:, :, None]
    if mask.ndim != (5 if video else 4) or mask.shape[1] != 1:
        raise ValueError("SelfLift: noise_mask must have shape [B, H, W], [B, 1, H, W], or [B, 1, T, H, W]")
    if mask.shape[0] != b:
        raise ValueError(f"SelfLift: noise_mask batch {mask.shape[0]} does not match the latent batch {b}")
    if tuple(mask.shape[-2:]) != (H, W):
        # masks are accepted at any resolution and resized to the latent grid,
        # matching ComfyUI's Set Latent Noise Mask convention
        lead = mask.shape[:-2]
        mask = torch.nn.functional.interpolate(
            mask.reshape(-1, 1, *mask.shape[-2:]).float(), size=(H, W), mode="bilinear", align_corners=False
        ).reshape(*lead, H, W)
    if video and mask.shape[2] not in (1, streams[0].shape[2]):
        raise ValueError(f"SelfLift: noise_mask time length {mask.shape[2]} does not match the latent frames {streams[0].shape[2]}")
    if not torch.isfinite(mask).all():
        raise ValueError("SelfLift: noise_mask must be finite")
    return mask.float().clamp(0.0, 1.0)


def _mask_blend_fn(anchor: torch.Tensor, mask: torch.Tensor) -> Callable[[Dict[str, Any]], torch.Tensor]:
    """post-CFG hook pinning x0 to the clean anchor outside the generate region.

    Exact under Euler: with the unmasked x0 pinned to the original latent each
    step, the unmasked state tracks original + the step's noise exactly.
    """

    def fn(args: Dict[str, Any]) -> torch.Tensor:
        d = args["denoised"]
        m = mask.to(device=d.device, dtype=d.dtype)
        return d * m + anchor.to(device=d.device, dtype=d.dtype) * (1.0 - m)

    return fn


def _euler_step(state: torch.Tensor, denoised: torch.Tensor, sigma: torch.Tensor, sigma_next: torch.Tensor) -> torch.Tensor:
    step = ((sigma_next - sigma) / sigma).to(device=state.device, dtype=state.dtype)
    return state + (state - denoised.to(state)) * step


def progressive_sample(
    model: comfy.model_patcher.ModelPatcher,
    conditioning: Sequence[Sequence[Any]],
    vae: VAE,
    latent_image: Dict[str, Any],
    sampler: comfy.samplers.KSAMPLER,
    sigmas: torch.Tensor,
    seed: int,
    transition_step: int,
    lowres_scale: float,
    rho: float,
    w_min: float,
    w_max: float,
    latent_upsample: str,
    latent_lifter: Optional[LatentLifter] = None,
    highres_tiling: bool = False,
    model_hires: Optional[comfy.model_patcher.ModelPatcher] = None,
    context_latent: Optional[Dict[str, Any]] = None,
    trim_frames: int = 0,
) -> Dict[str, Any]:
    """Sample a low-resolution prefix, lift the endpoint, then resume at target size."""
    _validate_schedule(sigmas, transition_step)
    if sigmas.numel() < 2:
        return latent_image
    if not 0.25 <= lowres_scale <= 1.0:
        raise ValueError("SelfLift: lowres_scale must be between 0.25 and 1")
    if not 0.0 <= rho <= 1.0:
        raise ValueError("SelfLift: rho must be between 0 and 1")
    if not 0.0 <= w_min <= w_max <= 1.0:
        raise ValueError("SelfLift: weights must satisfy 0 <= w_min <= w_max <= 1")
    noise_mask = _validate_latent_input(latent_image)
    if highres_tiling and noise_mask is not None:
        raise ValueError("SelfLift: noise_mask is not compatible with highres_tiling")

    model_sampling = model.get_model_object("model_sampling")
    _validate_sampling(model_sampling, sampler)

    streams, nested = _streams(
        comfy.sample.fix_empty_latent_channels(
            model,
            latent_image["samples"],
            latent_image.get("downscale_ratio_spacial", None),
            latent_image.get("downscale_ratio_temporal", None),
        )
    )
    hires_base = model_hires if model_hires is not None else model
    high_model = selflift_tiling.tiled_model(hires_base, [tuple(stream.shape) for stream in streams]) if highres_tiling else hires_base
    video = streams[0].ndim == 5
    if video:
        b, c, t, H, W = streams[0].shape
    else:
        b, c, H, W = streams[0].shape
        t = None
    h = max(2, round(H * lowres_scale / 2) * 2)
    w = max(2, round(W * lowres_scale / 2) * 2)
    low_shape = (b, c, t, h, w) if video else (b, c, h, w)
    _LOGGER.info(
        "[SelfLift plan] low_latent=%s target_latent=%s spatial_lift=(%.4f, %.4f) "
        "low_nfe=%d high_nfe=%d sigma_prediction=%.8g sigma_resume=%.8g "
        "rho=%.4f weights=(%.4f, %.4f) direct_lift=%s pixel_anchor=%s mask=%s hires_model=%s",
        low_shape,
        tuple(streams[0].shape),
        H / h,
        W / w,
        transition_step,
        sigmas.numel() - 1 - transition_step,
        sigmas[transition_step - 1].item(),
        sigmas[transition_step].item(),
        rho,
        w_min,
        w_max,
        "skipped" if rho == 1.0 and w_min == 1.0 else "external" if latent_lifter is not None else latent_upsample,
        rho > 0.0 and w_max > 0.0,
        "none" if noise_mask is None else f"{tuple(noise_mask.shape)}",
        "custom" if model_hires is not None else "same",
    )

    device = comfy.model_management.intermediate_device()
    source_video = streams[0].to(device)
    audio_streams = [s.to(device) for s in streams[1:]]

    def masked_model(
        base: comfy.model_patcher.ModelPatcher, video_anchor: torch.Tensor, m: Optional[torch.Tensor]
    ) -> comfy.model_patcher.ModelPatcher:
        # pin the unmasked region to the clean anchor via a post-CFG x0 blend;
        # ComfyUI's denoise_mask path is unusable here: the high-res resume
        # latent deliberately carries noise, which would contaminate its anchor
        if m is None:
            return base
        patched = base.clone()
        if nested:
            flat_mask = m.reshape(b, 1, -1).repeat(1, 1, c).to(video_anchor.device)
            flat_anchor = video_anchor.reshape(b, 1, -1)
            for s in audio_streams:
                flat_mask = torch.cat([flat_mask, torch.ones_like(s.reshape(b, 1, -1))], dim=-1)
                flat_anchor = torch.cat([flat_anchor, s.reshape(b, 1, -1)], dim=-1)
            hook = _mask_blend_fn(flat_anchor, flat_mask)
        else:
            hook = _mask_blend_fn(video_anchor, m)
        patched.model_options = comfy.model_patcher.set_model_options_post_cfg_function(patched.model_options, hook)
        return patched

    if video:
        low_video = torch.nn.functional.interpolate(source_video.float(), size=(t, h, w), mode="trilinear", align_corners=False).to(
            dtype=source_video.dtype
        )
    else:
        low_video = torch.nn.functional.interpolate(source_video.float(), size=(h, w), mode="bilinear", align_corners=False).to(
            dtype=source_video.dtype
        )
    m_full = m_low = None
    if noise_mask is not None:
        if video and noise_mask.shape[2] == 1 and t > 1:
            m_full = noise_mask.expand(b, 1, t, H, W)
        else:
            m_full = noise_mask
        if video:
            m_low = torch.nn.functional.interpolate(
                m_full.reshape(b * t, 1, H, W).float(), size=(h, w), mode="bilinear", align_corners=False
            ).reshape(b, 1, t, h, w)
        else:
            m_low = torch.nn.functional.interpolate(m_full.float(), size=(h, w), mode="bilinear", align_corners=False)
        m_low = m_low.clamp(0.0, 1.0)
    low_anchor = low_video
    video_anchor = source_video
    low_latent = _pack([low_video] + audio_streams, nested)
    low_model = masked_model(model, low_anchor, m_low)
    high_model = masked_model(high_model, video_anchor, m_full)
    del source_video, low_video
    del streams
    noise_low = comfy.sample.prepare_noise(low_latent, seed, latent_image.get("batch_index", None))

    total_steps = sigmas.shape[-1] - 1
    callback = latent_preview.prepare_callback(model, total_steps)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    if video:  # keyframe cond latents share the generation grid on MiniMax H3
        conditioning_low = prepare_keyframes(conditioning, vae, h, w, context_latent, trim_frames)
    else:
        conditioning_low = conditioning

    transition = {}
    low_evaluations = 0

    def callback_low(step: int, x0: Samples, x: Samples, total: int) -> None:
        nonlocal low_evaluations
        step = low_evaluations
        low_evaluations += 1
        if low_evaluations > transition_step:
            raise RuntimeError("SelfLift: too many low-resolution callbacks for the Euler schedule")
        if step == transition_step - 1:
            transition["state"] = x
            transition["x0"] = x0
        # Preview decoders expect the target grid.  Decode a temporary lifted
        # preview while keeping the sampler state at its true low resolution.
        preview_x0 = x0
        if video:
            preview_streams, preview_nested = _streams(x0)
            preview_video = torch.nn.functional.interpolate(
                preview_streams[0].float(), size=(t, H, W), mode="trilinear", align_corners=False
            ).to(preview_streams[0].dtype)
            preview_x0 = _pack([preview_video] + preview_streams[1:], preview_nested)
            del preview_video, preview_streams
        elif x0.ndim == 4:
            preview_x0 = torch.nn.functional.interpolate(x0.float(), size=(H, W), mode="bilinear", align_corners=False).to(x0.dtype)
        result = callback(step, preview_x0, preview_x0, total_steps)
        del preview_x0
        low_timer.mark(f"step {step + 1}/{transition_step}" + (" (includes setup)" if step == 0 else ""))
        return result

    # The final low-resolution model evaluation is the Eq. 3 prediction. Its Euler
    # update is discarded and rebuilt after the resolution transition, preserving NFE.
    resolution_scale = getattr(model.get_model_object("latent_format"), "spacial_downscale_ratio", 1)
    low_timer = StageTimer("low_resolution", low_model.load_device, (h, w), resolution_scale)
    log_memory("low_resolution start", low_model.load_device)
    low_guider = Guider_Basic(low_model)
    low_guider.set_conds(conditioning_low)
    low_guider.sample(
        noise_low,
        low_latent,
        sampler,
        sigmas[: transition_step + 1],
        callback=callback_low,
        disable_pbar=disable_pbar,
        seed=seed,
    )
    if low_evaluations != transition_step:
        raise RuntimeError(
            f"SelfLift: expected {transition_step} low-resolution callbacks, received {low_evaluations}; check sampler wrappers"
        )
    low_timer.finish()
    log_memory("low_resolution end", model.load_device)
    transition_timer = StageTimer("transition", model.load_device, (H, W), resolution_scale)
    low_streams, nested = _streams(transition.pop("state"))
    x0_streams, _ = _streams(transition.pop("x0"))
    sigma_k = sigmas[transition_step - 1]
    sigma_next = sigmas[transition_step]
    auxiliary_next = [
        _euler_step(state.to(device), denoised.to(device), sigma_k, sigma_next) for state, denoised in zip(low_streams[1:], x0_streams[1:])
    ]
    latent_format = model.get_model_object("latent_format")
    z0_low_vae = latent_format.process_out(x0_streams[0].float()).to(device)
    del low_latent, noise_low, low_streams, x0_streams, conditioning_low, low_guider
    transition_timer.mark("prepare_endpoint")
    log_memory("transition endpoint_ready", model.load_device)

    # Artifact-Aware Consistency Lift (Eqs. 4-9); skip branches the weights discard
    need_pix = rho > 0.0 and w_max > 0.0
    need_lat = not (rho >= 1.0 and w_min >= 1.0 and w_max >= 1.0)
    z_lat_vae, z_pix_vae = paired_lifts(z0_low_vae, vae, (H, W), latent_upsample, latent_lifter, need_lat=need_lat, need_pix=need_pix)
    transition_timer.mark("paired_lifts")
    log_memory("transition lifts_ready", model.load_device)
    z_lat = latent_format.process_in(z_lat_vae) if z_lat_vae is not None else None
    z_pix = latent_format.process_in(z_pix_vae) if z_pix_vae is not None else None
    z0_high = artifact_aware_consistency_lift(z_lat, z_pix, rho, w_min, w_max, mask=m_full)
    if m_full is not None:
        # restore the keep-region with the true original instead of any lifted estimate
        m_cast = m_full.to(device=z0_high.device, dtype=z0_high.dtype)
        z0_high = z0_high * m_cast + video_anchor * (1.0 - m_cast)
    if os.environ.get("SELFLIFT_DEBUG", "0") == "1":
        debug_dump(
            vae,
            {
                "z0_low": z0_low_vae,
                "z_lat": z_lat_vae,
                "z_pix": z_pix_vae,
                "z0_high": latent_format.process_out(z0_high),
            },
        )
    z0_high = z0_high.to(device)
    del z0_low_vae, z_lat_vae, z_pix_vae, z_lat, z_pix
    transition_timer.mark("correction_and_debug")
    log_memory("transition correction_ready", model.load_device)

    # Re-noise the corrected video/image endpoint at the sigma of the reused model
    # evaluation, then complete that Euler interval without another denoiser call.
    video_noise = comfy.sample.prepare_noise(z0_high, (seed + 1) % (1 << 64), latent_image.get("batch_index", None)).to(z0_high)
    video_state = model_sampling.noise_scaling(sigma_k, video_noise, z0_high)
    next_streams = [_euler_step(video_state, z0_high, sigma_k, sigma_next)] + auxiliary_next
    del z0_high, video_noise, video_state, auxiliary_next
    resume_streams = [model_sampling.inverse_noise_scaling(sigma_next, s) for s in next_streams]
    resume_latent = model.model.process_latent_out(_pack(resume_streams, nested))
    resume_noise = _pack([torch.zeros_like(s) for s in resume_streams], nested)
    del next_streams, resume_streams
    transition_timer.mark("renoise")
    transition_timer.finish()
    log_memory("transition end / high_resolution start", model.load_device)

    high_evaluations = 0

    def callback_high(step: int, x0: Samples, x: Samples, total: int) -> None:
        nonlocal high_evaluations
        step = high_evaluations
        high_evaluations += 1
        if high_evaluations > total_steps - transition_step:
            raise RuntimeError("SelfLift: too many high-resolution callbacks for the Euler schedule")
        result = callback(step + transition_step, x0, x, total_steps)
        high_timer.mark(f"step {step + 1}/{total_steps - transition_step}" + (" (includes setup)" if step == 0 else ""))
        return result

    high_timer = StageTimer("high_resolution", model.load_device, (H, W), resolution_scale)
    if highres_tiling:
        _LOGGER.info("[SelfLift plan] automatic high-resolution tiling enabled; preparation selects the tile count")
    high_guider = Guider_Basic(high_model)
    high_guider.set_conds(conditioning)
    out = high_guider.sample(
        resume_noise,
        resume_latent,
        sampler,
        sigmas[transition_step:],
        callback=callback_high,
        disable_pbar=disable_pbar,
        seed=seed,
    )
    del resume_latent, resume_noise
    if high_evaluations != total_steps - transition_step:
        raise RuntimeError(
            f"SelfLift: expected {total_steps - transition_step} high-resolution callbacks, received {high_evaluations}; check sampler wrappers"
        )

    result = latent_image.copy()
    result["samples"] = out.to(device=comfy.model_management.intermediate_device(), dtype=comfy.model_management.intermediate_dtype())
    high_timer.finish()
    log_memory("high_resolution end", model.load_device)
    return result
