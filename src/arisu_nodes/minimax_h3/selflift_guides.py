"""Prepare H3 keyframes on the low-resolution sampling grid."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn.functional as F
from comfy.ldm.minimax.vae import MiniMaxH3VideoVAE
from comfy.nested_tensor import NestedTensor
from comfy.sd import VAE

from .core import video_frame_count, video_latent_t

Conditioning = Sequence[Sequence[Any]]


def _resize_latent(latent: torch.Tensor, h: int, w: int) -> torch.Tensor:
    """Preserve the spatial-only fallback for guides with no accompanying pixels."""
    frames = latent.transpose(1, 2).flatten(0, 1) if latent.ndim == 5 else latent
    frames = frames.float()
    resized = F.interpolate(frames, size=(h, w), mode="bilinear", align_corners=False)
    resized = resized + (frames.mean(dim=(-2, -1), keepdim=True) - resized.mean(dim=(-2, -1), keepdim=True))
    if latent.ndim == 5:
        resized = resized.unflatten(0, (latent.shape[0], latent.shape[2])).transpose(1, 2)
    return resized.to(latent)


def _encode_pixels(pixels: torch.Tensor, vae: VAE, h: int, w: int, template: torch.Tensor, steps: int) -> torch.Tensor:
    """Resize a continuous F,H,W,C pixel sequence before its single VAE encode."""
    ratio = vae.spacial_compression_encode()
    low = F.interpolate(
        pixels[..., :3].movedim(-1, 1).float(), size=(h * ratio, w * ratio), mode="bilinear", align_corners=False, antialias=True
    )
    encoded = vae.encode(low.movedim(1, -1))
    if encoded.shape != (1, template.shape[1], steps, h, w):
        raise ValueError(f"SelfLift: the video VAE returned an unexpected low-resolution guide shape {tuple(encoded.shape)}")
    return encoded.to(template)


def _head_rows(keyframes: Sequence[Dict[str, Any]], trim: int, steps: int) -> List[int]:
    """Locate the one-token rows belonging to the timed H3 video prefix."""
    timed = sorted(
        (kf["resolved_frame_index"], i)
        for i, kf in enumerate(keyframes)
        if kf.get("latent") is not None and 0 <= kf.get("resolved_frame_index", -1) < trim
    )
    # Each cycle represents 17 frames in five tokens spanning 1, 4, 4, 4, 4 frames.
    if len(timed) != steps or any(frame != 17 * (k // 5) + (0, 1, 5, 9, 13)[k % 5] for k, (frame, _) in enumerate(timed)):
        return []
    return [i for _, i in timed]


def _previous_video(context_latent: Dict[str, Any]) -> torch.Tensor:
    samples = context_latent.get("samples")
    if isinstance(samples, NestedTensor):
        samples = samples.unbind()
    if isinstance(samples, (list, tuple)) and samples:
        samples = samples[0]
    if not isinstance(samples, torch.Tensor) or samples.ndim not in (4, 5):
        raise ValueError("SelfLift: connect the previous Motion Context video latent to context_latent")
    return samples.unsqueeze(0) if samples.ndim == 4 else samples[:1]


def _motion_pixels(parts: Sequence[torch.Tensor], vae: VAE, context_latent: Optional[Dict[str, Any]], trim: int) -> torch.Tensor:
    reference = parts[0]
    if reference.ndim != 5 or reference.shape[0] != 1 or reference.shape[2] != 1 or any(p.shape != reference.shape for p in parts):
        raise ValueError("SelfLift: each pinned Motion Context row must contain one video latent step")
    if context_latent is None:
        video = torch.cat(parts, dim=2)
    else:
        video = _previous_video(context_latent)
        start = video.shape[2] - len(parts)
        if (
            start < 0
            or start % 5
            or any(not torch.equal(p, video[:, :, start + k : start + k + 1].to(device=p.device)) for k, p in enumerate(parts))
        ):
            raise ValueError(
                "SelfLift: context_latent does not match the pinned video tail; connect the same previous latent to both nodes"
            )
        # The stock decoder blends each five-token block with its predecessor.
        # Keeping one aligned warmup block reproduces the full decode's tail.
        # A different decoder (e.g. Sol) can use longer temporal attention.
        model = getattr(vae, "first_stage_model", None)
        if (
            type(model) is MiniMaxH3VideoVAE
            and getattr(model, "noncausal", None) is False
            and getattr(model, "tokens_chunk_size", None) == 5
            and getattr(model, "token_drop", None) == 3
        ):
            video = video[:, :, max(0, start - 5) :]
    expected = 1 if video.shape[2] == 1 else video_frame_count(video.shape[2])
    pixels = vae.decode(video)
    if pixels.ndim == 5 and pixels.shape[0] == 1:
        pixels = pixels[0]
    if pixels.ndim != 4 or pixels.shape[0] != expected or pixels.shape[-1] != 3:
        raise ValueError("SelfLift: the video VAE did not decode the expected Motion Context frames")
    return pixels[-trim:]


def prepare_keyframes(
    positive: Conditioning,
    negative: Conditioning,
    vae: VAE,
    h: int,
    w: int,
    context_latent: Optional[Dict[str, Any]],
    trim_frames: int,
) -> Tuple[Conditioning, Conditioning]:
    """Encode available source pixels on the low grid and preserve other conditioning fields."""
    steps = 1 if trim_frames == 1 else video_latent_t(trim_frames)
    if trim_frames and trim_frames != 1 and video_frame_count(steps) != trim_frames:
        raise ValueError("SelfLift: trim_frames must be the H3 Motion Context trim output")
    motion_cache: Dict[Tuple[int, ...], Tuple[torch.Tensor, ...]] = {}
    still_cache: Dict[Tuple[int, int], torch.Tensor] = {}

    def prepare(cond: Conditioning, use_motion: bool) -> List[Tuple[Any, Dict[str, Any]]]:
        result = []
        found_motion = False
        for embedding, metadata in cond:
            keys = metadata.get("minimax_keyframes") or []
            rows = _head_rows(keys, trim_frames, steps) if trim_frames else []
            replacements = {}
            if rows:
                parts = [keys[i]["latent"] for i in rows]
                signature = tuple(id(p) for p in parts)
                found_motion = True
                # The negative branch can share the positive guides (e.g. ConditioningZeroOut),
                # or carry unrelated keyframes at the same coordinates.
                if (use_motion or signature in motion_cache) and any(p.shape[-2:] != (h, w) for p in parts):
                    if signature not in motion_cache:
                        pixels = _motion_pixels(parts, vae, context_latent, trim_frames)
                        encoded = _encode_pixels(pixels, vae, h, w, parts[0], steps)
                        motion_cache[signature] = encoded.split(1, dim=2)
                    replacements = dict(zip(rows, motion_cache[signature], strict=True))

            pixels_by_id = {id(latent): image for latent, image in metadata.get("arisu_keyframe_pixels", [])}
            low_keys = []
            for i, key in enumerate(keys):
                latent = key.get("latent")
                if latent is None or latent.shape[-2:] == (h, w):
                    low_keys.append(key)
                    continue
                if i in replacements:
                    low_latent = replacements[i]
                elif id(latent) in pixels_by_id:
                    image = pixels_by_id[id(latent)]
                    identity = (id(latent), id(image))
                    if identity not in still_cache:
                        still_cache[identity] = _encode_pixels(image, vae, h, w, latent, 1)
                    low_latent = still_cache[identity]
                else:
                    low_latent = _resize_latent(latent, h, w)
                low_keys.append({**key, "latent": low_latent})
            result.append((embedding, {**metadata, "minimax_keyframes": low_keys} if keys else metadata))
        if use_motion and trim_frames and not found_motion:
            raise ValueError("SelfLift: trim_frames does not match the pinned rows in positive conditioning")
        return result

    return prepare(positive, True), prepare(negative, False)
