"""ComfyUI-free logic for the MiniMax H3 node family.

Everything here imports only the standard library so it can be unit-tested in
the project's own environment, without torch or ComfyUI on the path. The
numbers mirror ComfyUI's ``comfy_extras/nodes_minimax_h3.py`` (v0.34.5): the
17k+5 frame grid at 24 fps, the 40 Hz audio latent grid, the 32-pixel canvas
multiple, and the reference sizing rules.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple, TypeVar

T = TypeVar("T")

CANVAS_MULTIPLE = 32
BASE_SHORT_EDGE = 768
MAX_PIXELS = 768 * 1344
REF_IMAGE_SHORT_EDGE = 2048
FPS = 24
QWEN_FPS = 2
AUDIO_LATENT_FPS = 40
SPATIAL_DOWNSCALE = 16
VIDEO_LATENT_CHANNELS = 24
AUDIO_LATENT_CHANNELS = 32
AUDIO_CHANNELS = 2
# Valid clip lengths are 17k + 5 pixel frames: 5, 22, 39, ...
MIN_CLIP_FRAMES = 5
CLIP_FRAME_STEP = 17

REF_IMAGE_SIZE_MODES = ("match", "max")
FRAME_TAG_MODES = ("after_refs", "before_refs", "none")
# The labels of ComfyUI's core Resolution Selector node, so workflows read the same.
ASPECT_RATIOS: Tuple[Tuple[str, int, int], ...] = (
    ("1:1 (Square)", 1, 1),
    ("2:3 (Portrait Photo)", 2, 3),
    ("3:2 (Photo)", 3, 2),
    ("3:4 (Portrait Standard)", 3, 4),
    ("4:3 (Standard)", 4, 3),
    ("9:16 (Portrait Widescreen)", 9, 16),
    ("16:9 (Widescreen)", 16, 9),
    ("21:9 (Ultrawide)", 21, 9),
)
ASPECT_RATIO_LABELS: Tuple[str, ...] = tuple(label for label, _w, _h in ASPECT_RATIOS)
# The core node's megapixel: 1024 x 1024 pixels, not 10^6.
MEGAPIXEL = 1024 * 1024


def align_frame_count(n: int) -> int:
    """Snap a frame count up to the model's 17k+5 grid.

    Args:
        n: Requested frame count.

    Returns:
        The smallest count ``>= n`` that is congruent to 5 modulo 17.
    """
    while n % CLIP_FRAME_STEP != MIN_CLIP_FRAMES:
        n += 1
    return n


def video_latent_t(frame_count: int) -> int:
    """Return the video latent length for an aligned pixel frame count.

    The first 5 pixel frames map to 2 latent frames; every further 17 pixel
    frames add 5 latent frames.

    Args:
        frame_count: Pixel frame count on the 17k+5 grid.

    Returns:
        Number of latent frames along the temporal axis.
    """
    if frame_count <= MIN_CLIP_FRAMES:
        return 2
    return ((frame_count - MIN_CLIP_FRAMES) // CLIP_FRAME_STEP) * 5 + 2


def temporal_shape(length: int) -> Tuple[int, int, int]:
    """Resolve a requested length into the model's temporal sizes.

    Args:
        length: Requested frame count at 24 fps; anything below 5 is raised to 5.

    Returns:
        ``(frame_count, video_latent_t, audio_latent_t)``: the aligned pixel
        frame count, the video latent length, and the 40 Hz audio latent length.
    """
    frame_count = align_frame_count(max(MIN_CLIP_FRAMES, length))
    duration = frame_count / FPS
    return frame_count, video_latent_t(frame_count), round(duration * AUDIO_LATENT_FPS)


def round_to_canvas(value: float) -> int:
    """Round a pixel size to the nearest canvas multiple, never below one multiple.

    Args:
        value: Pixel size, possibly fractional.

    Returns:
        ``value`` rounded to a multiple of 32, at least 32.
    """
    return max(CANVAS_MULTIPLE, round(value / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)


def adapt_canvas(width: int, height: int) -> Tuple[int, int]:
    """Fit an aspect ratio onto the 768-short-edge canvas with a 768x1344 area cap.

    Args:
        width: Source width in pixels.
        height: Source height in pixels.

    Returns:
        ``(canvas_width, canvas_height)``, each rounded to a multiple of 32.
    """
    ratio = width / height
    if ratio >= 1.0:
        nom_w, nom_h = BASE_SHORT_EDGE * ratio, float(BASE_SHORT_EDGE)
    else:
        nom_w, nom_h = float(BASE_SHORT_EDGE), BASE_SHORT_EDGE / ratio
    if nom_w * nom_h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (nom_w * nom_h))
        nom_w, nom_h = nom_w * s, nom_h * s
    return round_to_canvas(nom_w), round_to_canvas(nom_h)


def ref_image_canvas(ref_width: int, ref_height: int, target_width: int, target_height: int, mode: str) -> Tuple[int, int]:
    """Size a reference image for encoding; aspect-preserving and never upscaled.

    Args:
        ref_width: Reference image width in pixels.
        ref_height: Reference image height in pixels.
        target_width: Generation width in pixels.
        target_height: Generation height in pixels.
        mode: ``"match"`` scales down to the generation's pixel area; ``"max"``
            caps the short edge at 2048 px.

    Returns:
        ``(width, height)`` for the encoded reference, multiples of 32.

    Raises:
        ValueError: If ``mode`` is not one of ``REF_IMAGE_SIZE_MODES``.
    """
    if mode == "match":
        scale = min(1.0, math.sqrt((target_width * target_height) / (ref_width * ref_height)))
    elif mode == "max":
        scale = min(1.0, REF_IMAGE_SHORT_EDGE / min(ref_width, ref_height))
    else:
        raise ValueError(f"unknown ref_image_size {mode!r}; expected one of {REF_IMAGE_SIZE_MODES}")
    return round_to_canvas(ref_width * scale), round_to_canvas(ref_height * scale)


def ref_video_canvas(video_width: int, video_height: int) -> Tuple[int, int]:
    """Size a reference video for encoding: the adapted canvas, or smaller if the source is.

    Args:
        video_width: Source frame width in pixels.
        video_height: Source frame height in pixels.

    Returns:
        ``(width, height)`` for the encoded clip, multiples of 32.
    """
    canvas_w, canvas_h = adapt_canvas(video_width, video_height)
    if video_width * video_height < canvas_w * canvas_h:
        return round_to_canvas(video_width), round_to_canvas(video_height)
    return canvas_w, canvas_h


def align_clip_frames(n_frames: int, frame_count: int) -> int:
    """Crop a reference clip length to the target duration and down to the 17k+5 grid.

    Args:
        n_frames: Frames available in the reference clip.
        frame_count: Aligned frame count of the target video.

    Returns:
        The number of leading frames to keep.

    Raises:
        ValueError: If fewer than 5 frames are available.
    """
    n = min(n_frames, frame_count)
    if n < MIN_CLIP_FRAMES:
        raise ValueError("MiniMax H3 reference videos need at least 5 frames (~0.2s at 24 fps)")
    while n % CLIP_FRAME_STEP != MIN_CLIP_FRAMES:
        n -= 1
    return n


def qwen_sample_indices(n_frames: int) -> List[int]:
    """Indices of the frames the text encoder sees: a 2 fps subsample of a 24 fps clip.

    Args:
        n_frames: Frames in the aligned reference clip.

    Returns:
        Frame indices ``0, 12, 24, ...`` below ``n_frames``.
    """
    return list(range(0, n_frames, FPS // QWEN_FPS))


def qwen_timestamps(count: int) -> List[float]:
    """Timestamps in seconds for ``count`` frames sampled at 2 fps.

    Args:
        count: Number of sampled frames.

    Returns:
        ``[0.0, 0.5, 1.0, ...]`` of length ``count``.
    """
    return [i / QWEN_FPS for i in range(count)]


def soundtrack_key(video_slot: str) -> str:
    """Name of the soundtrack slot paired with a reference video slot.

    ``ref_video_audio_N`` belongs to ``ref_video_N``.

    Args:
        video_slot: A reference video slot name such as ``"ref_video_2"``.

    Returns:
        The matching soundtrack slot name, ``"ref_video_audio_2"``.
    """
    return "ref_video_audio_" + video_slot.rsplit("_", 1)[-1]


def order_picture_items(mode: str, frame_items: Sequence[T], ref_items: Sequence[T]) -> List[T]:
    """Order the ``<Picture N>`` items the text encoder sees.

    The tokenizer numbers picture items 1-based in list order, so this decides
    whether first/last frames take ordinals before or after the reference
    images, or stay invisible to the prompt.

    Args:
        mode: One of ``FRAME_TAG_MODES``.
        frame_items: Items for the first/last frames, in that order.
        ref_items: Items for the reference images, in slot order.

    Returns:
        The combined list in presentation order.

    Raises:
        ValueError: If ``mode`` is not one of ``FRAME_TAG_MODES``.
    """
    if mode == "after_refs":
        return [*ref_items, *frame_items]
    if mode == "before_refs":
        return [*frame_items, *ref_items]
    if mode == "none":
        return list(ref_items)
    raise ValueError(f"unknown frame_picture_tags {mode!r}; expected one of {FRAME_TAG_MODES}")


def latent_size(width: int, height: int) -> Tuple[int, int]:
    """Spatial latent size for a pixel canvas.

    Args:
        width: Canvas width in pixels, a multiple of 32.
        height: Canvas height in pixels, a multiple of 32.

    Returns:
        ``(latent_height, latent_width)`` at the 16x spatial downscale.
    """
    return height // SPATIAL_DOWNSCALE, width // SPATIAL_DOWNSCALE


def keyframe_canvases(width: int, height: int, target_width: int, target_height: int) -> List[Tuple[int, int]]:
    """Distinct canvases the keyframes must be encoded at, generation canvas first.

    Args:
        width: Generation width in pixels.
        height: Generation height in pixels.
        target_width: Width of the upscaled video in pixels.
        target_height: Height of the upscaled video in pixels.

    Returns:
        ``[(width, height)]`` when the target equals the generation canvas, else
        ``[(width, height), (target_width, target_height)]``.
    """
    canvases = [(width, height)]
    if (target_width, target_height) != (width, height):
        canvases.append((target_width, target_height))
    return canvases


def frame_needs_resize(frame_shape: Sequence[int], width: int, height: int) -> bool:
    """Whether an image batch has to be resampled to fit a canvas.

    Args:
        frame_shape: Shape of the image batch, ``[B, H, W, C]``.
        width: Canvas width in pixels.
        height: Canvas height in pixels.

    Returns:
        ``True`` when the batch's ``(W, H)`` differ from ``(width, height)``.
    """
    return (frame_shape[2], frame_shape[1]) != (width, height)


def video_frame_count(latent_t: int) -> int:
    """Return the pixel frame count an H3 video latent decodes to.

    The inverse of :func:`video_latent_t`: 2 latent frames decode to 5 pixel
    frames and every further 5 latent frames add 17 pixel frames. Only lengths
    on the 5k+2 grid round-trip through the VAE, so anything else is refused.

    Args:
        latent_t: Number of latent frames along the temporal axis.

    Returns:
        Pixel frame count on the 17k+5 grid.

    Raises:
        ValueError: If ``latent_t`` is not of the form 5k+2 with k >= 0.
    """
    if latent_t < 2 or (latent_t - 2) % 5 != 0:
        raise ValueError(f"an H3 video latent has 5k+2 frames along its temporal axis, got {latent_t}")
    return ((latent_t - 2) // 5) * CLIP_FRAME_STEP + MIN_CLIP_FRAMES


def canvas_from_megapixels(aspect_ratio: str, megapixels: float) -> Tuple[int, int]:
    """Size a canvas from an aspect ratio label and a pixel budget, on the 32-pixel grid.

    Mirrors ComfyUI's core Resolution Selector with ``multiple`` fixed at the
    MiniMax H3 canvas multiple.

    Args:
        aspect_ratio: One of ``ASPECT_RATIO_LABELS``.
        megapixels: Pixel budget in units of 1024 x 1024.

    Returns:
        ``(width, height)`` rounded to multiples of 32, never below 32.

    Raises:
        ValueError: If ``aspect_ratio`` is not one of ``ASPECT_RATIO_LABELS``.
    """
    for label, w_ratio, h_ratio in ASPECT_RATIOS:
        if label == aspect_ratio:
            scale = math.sqrt(megapixels * MEGAPIXEL / (w_ratio * h_ratio))
            return round_to_canvas(w_ratio * scale), round_to_canvas(h_ratio * scale)
    raise ValueError(f"unknown aspect_ratio {aspect_ratio!r}; expected one of {ASPECT_RATIO_LABELS}")


def scaled_canvas(width: int, height: int, factor: float) -> Tuple[int, int]:
    """Scale a canvas by a factor and snap the result to the 32-pixel grid.

    Args:
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        factor: Upscale factor.

    Returns:
        ``(width, height)`` of the scaled canvas, multiples of 32, never below 32.
    """
    return round_to_canvas(width * factor), round_to_canvas(height * factor)


def frames_for_duration(seconds: float) -> int:
    """Frame count for a duration at 24 fps, snapped up to the 17k+5 grid.

    Args:
        seconds: Clip length in seconds.

    Returns:
        The aligned frame count, at least 5; 5.0 s gives 124, the stock default.
    """
    return align_frame_count(max(MIN_CLIP_FRAMES, round(seconds * FPS)))
