"""MiniMax H3 V3 nodes.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.

The tensor helpers mirror ``comfy_extras/nodes_minimax_h3.py`` (v0.34.5) rather
than importing its underscore-private names, so a ComfyUI rename cannot break
the pack at import time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

import comfy.model_management
import comfy.nested_tensor
import comfy.utils
import node_helpers
import torch
import torchaudio
from comfy_api.latest import io
from nodes import MAX_RESOLUTION

from .core import (
    AUDIO_CHANNELS,
    AUDIO_LATENT_CHANNELS,
    FRAME_TAG_MODES,
    REF_IMAGE_SIZE_MODES,
    VIDEO_LATENT_CHANNELS,
    align_clip_frames,
    latent_size,
    order_picture_items,
    qwen_sample_indices,
    qwen_timestamps,
    ref_image_canvas,
    ref_video_canvas,
    soundtrack_key,
    temporal_shape,
)

RefItem = Dict[str, Any]
RefBlock = Dict[str, Any]


def resize_frames(image: torch.Tensor, width: int, height: int, crop: str) -> torch.Tensor:
    """Lanczos-resize an image batch to ``width`` x ``height``, dropping any alpha channel.

    Args:
        image: Frames shaped ``[B, H, W, C]`` in the 0-1 range.
        width: Target width in pixels.
        height: Target height in pixels.
        crop: ``"disabled"`` for a plain stretch or ``"center"`` for an aspect-preserving cover-crop.

    Returns:
        Frames shaped ``[B, height, width, 3]``.
    """
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(samples, width, height, "lanczos", crop)
    return samples.movedim(1, -1)


def encode_ref_audio(audio_vae: Any, audio: Dict[str, Any]) -> Tuple[torch.Tensor, int]:
    """Encode the first waveform of an AUDIO value with the H3 audio VAE.

    Args:
        audio_vae: The MiniMax H3 audio VAE.
        audio: ``{"waveform": [B, C, L], "sample_rate": int}``.

    Returns:
        ``(latent, latent_t)``: the ``[1, 32, 2, T]`` audio latent and its length ``T``.
    """
    waveform = audio["waveform"]
    sample_rate = audio["sample_rate"]
    vae_sample_rate = getattr(audio_vae, "audio_sample_rate", 32000)
    if sample_rate != vae_sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, vae_sample_rate)
    z = audio_vae.encode(waveform[:1].movedim(1, -1))
    return z, z.shape[-1]


def empty_av_latent(width: int, height: int, length: int) -> Tuple[Dict[str, Any], int]:
    """Build the zero AV latent pair for a generation and report its aligned frame count.

    Args:
        width: Canvas width in pixels, a multiple of 32.
        height: Canvas height in pixels, a multiple of 32.
        length: Requested frame count at 24 fps.

    Returns:
        ``(latent, frame_count)``: a LATENT dict whose ``samples`` is a
        ``NestedTensor`` of video ``[1, 24, T, H/16, W/16]`` and audio
        ``[1, 32, 2, T40]``, and the frame count snapped to the 17k+5 grid.
    """
    frame_count, latent_t, audio_t = temporal_shape(length)
    latent_h, latent_w = latent_size(width, height)
    device = comfy.model_management.intermediate_device()
    video = torch.zeros([1, VIDEO_LATENT_CHANNELS, latent_t, latent_h, latent_w], device=device)
    audio = torch.zeros([1, AUDIO_LATENT_CHANNELS, AUDIO_CHANNELS, audio_t], device=device)
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}, frame_count


def _require_audio_vae(audio_vae: Optional[Any]) -> Any:
    if audio_vae is None:
        raise ValueError("encoding reference audio needs the audio_vae input")
    return audio_vae


def _encode_ref_images(
    vae: Any, ref_images: Dict[str, Optional[torch.Tensor]], width: int, height: int, ref_image_size: str
) -> Tuple[List[RefItem], List[RefBlock]]:
    items: List[RefItem] = []
    blocks: List[RefBlock] = []
    for img in ref_images.values():
        if img is None:
            continue
        ref_w, ref_h = ref_image_canvas(img.shape[2], img.shape[1], width, height, ref_image_size)
        resized = resize_frames(img[:1], ref_w, ref_h, "disabled")
        latent_h, latent_w = latent_size(ref_w, ref_h)
        items.append({"type": "image", "data": resized})
        blocks.append({"kind": "image", "latent_h": latent_h, "latent_w": latent_w, "latent": vae.encode(resized)})
    return items, blocks


def _encode_ref_videos(
    vae: Any,
    audio_vae: Optional[Any],
    ref_videos: Dict[str, Optional[torch.Tensor]],
    ref_video_audios: Dict[str, Optional[Dict[str, Any]]],
    frame_count: int,
) -> Tuple[List[RefItem], List[RefBlock]]:
    items: List[RefItem] = []
    blocks: List[RefBlock] = []
    for name, video_frames in ref_videos.items():
        if video_frames is None:
            continue
        # index-paired soundtrack: ref_video_audio_N belongs to ref_video_N
        soundtrack = ref_video_audios.get(soundtrack_key(name))
        canvas_w, canvas_h = ref_video_canvas(video_frames.shape[2], video_frames.shape[1])
        n_frames = align_clip_frames(video_frames.shape[0], frame_count)
        frames = resize_frames(video_frames[:n_frames], canvas_w, canvas_h, "disabled")
        z = vae.encode(frames)
        audio_latent: Optional[torch.Tensor] = None
        ref_audio_t = 0
        if soundtrack is not None:
            audio_latent, ref_audio_t = encode_ref_audio(_require_audio_vae(audio_vae), soundtrack)
            # the soundtrack gets its own <Audio j> label, emitted before <Video k>
            items.append({"type": "audio"})
        # Qwen sees the video at 2 fps with timestamps
        sample_idx = qwen_sample_indices(n_frames)
        items.append({"type": "video", "data": frames[sample_idx], "timestamps": qwen_timestamps(len(sample_idx))})
        latent_h, latent_w = latent_size(canvas_w, canvas_h)
        blocks.append(
            {
                "kind": "video_audio" if ref_audio_t else "video",
                "latent_t": z.shape[2],
                "latent_h": latent_h,
                "latent_w": latent_w,
                "ref_audio_t": ref_audio_t,
                "latent": z,
                "audio_latent": audio_latent,
            }
        )
    return items, blocks


def _encode_ref_audios(audio_vae: Optional[Any], ref_audios: Dict[str, Optional[Dict[str, Any]]]) -> Tuple[List[RefItem], List[RefBlock]]:
    items: List[RefItem] = []
    blocks: List[RefBlock] = []
    for audio in ref_audios.values():
        if audio is None:
            continue
        audio_latent, ref_audio_t = encode_ref_audio(_require_audio_vae(audio_vae), audio)
        items.append({"type": "audio"})
        # audio-only blocks carry no "latent" key at all; the model checks for its presence
        blocks.append({"kind": "audio", "ref_audio_t": ref_audio_t, "audio_latent": audio_latent})
    return items, blocks


class ArisuMiniMaxH3HybridToVideo(io.ComfyNode):
    """fl2va and ref2va in one conditioning: first/last keyframes plus references.

    ComfyUI's stock nodes set either ``minimax_keyframes`` (Image to Video) or
    ``minimax_refs`` (Reference to Video) and each builds its own latent, so
    they cannot be chained. The model already packs both, keyframes first, so
    this node sets both keys on one conditioning and returns one AV latent.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="ArisuMiniMaxH3HybridToVideo",
            display_name="MiniMax H3 Hybrid to Video",
            category="Arisu Nodes/MiniMax H3",
            description=(
                "MiniMax H3 conditioning with first/last keyframes and <Picture i> / <Video k> / <Audio j> "
                "references in one node. Outputs positive conditioning and the AV latent."
            ),
            inputs=[
                io.Clip.Input("clip"),
                io.Vae.Input("vae", tooltip="Video VAE; encodes keyframes and visual references."),
                io.Vae.Input(
                    "audio_vae",
                    optional=True,
                    tooltip="Audio VAE, needed only when a reference audio or a reference video soundtrack is connected.",
                ),
                io.String.Input("prompt", multiline=True, dynamic_prompts=True),
                io.Int.Input("width", default=1344, min=32, max=MAX_RESOLUTION, step=32),
                io.Int.Input("height", default=768, min=32, max=MAX_RESOLUTION, step=32),
                io.Int.Input(
                    "length",
                    default=124,
                    min=5,
                    max=3600,
                    step=17,
                    tooltip="Frame count at 24 fps, snapped up to the model's 17k+5 grid (124 = ~5s; trained range is ~124-362).",
                ),
                io.Combo.Input(
                    "ref_image_size",
                    options=list(REF_IMAGE_SIZE_MODES),
                    default="match",
                    tooltip=(
                        "Reference image sizing. 'match' scales each ref (down only, keeping aspect) to the generation's "
                        "pixel area; 'max' uses the reference pipeline's 2048px short edge for best identity fidelity. "
                        "Reference tokens ride through every sampling step, so 'max' can be several times slower."
                    ),
                ),
                io.Combo.Input(
                    "frame_picture_tags",
                    options=list(FRAME_TAG_MODES),
                    default="after_refs",
                    tooltip=(
                        "How the first/last frames appear to the text encoder. 'after_refs': reference images keep "
                        "<Picture 1..n> and the frames follow as <Picture n+1..>. 'before_refs': the frames take "
                        "<Picture 1..> and references are numbered after them. 'none': the frames only pin the video "
                        "and are invisible to the prompt."
                    ),
                ),
                io.Image.Input("first_frame", optional=True, tooltip="Keyframe pinned at frame 0; stretched to the canvas."),
                io.Image.Input("last_frame", optional=True, tooltip="Keyframe pinned at the last frame; center-cropped to the canvas."),
                io.Autogrow.Input(
                    "ref_images",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input(
                            "ref_image", tooltip="Reference image (downscaled to 2048 short edge if larger, never upscaled)"
                        ),
                        prefix="ref_image_",
                        min=0,
                        max=9,
                    ),
                ),
                io.Autogrow.Input(
                    "ref_videos",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("ref_video", tooltip="Reference video frames at 24 fps (2-15s)"),
                        prefix="ref_video_",
                        min=0,
                        max=3,
                    ),
                ),
                io.Autogrow.Input(
                    "ref_video_audios",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input("ref_video_audio", tooltip="Soundtrack of the same-numbered reference video"),
                        prefix="ref_video_audio_",
                        min=0,
                        max=3,
                    ),
                ),
                io.Autogrow.Input(
                    "ref_audios",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input("ref_audio", tooltip="Standalone reference audio"),
                        prefix="ref_audio_",
                        min=0,
                        max=3,
                    ),
                ),
            ],
            outputs=[io.Conditioning.Output(display_name="positive"), io.Latent.Output()],
        )

    @classmethod
    def execute(
        cls,
        clip: Any,
        vae: Any,
        prompt: str,
        width: int,
        height: int,
        length: int,
        ref_image_size: str,
        frame_picture_tags: str,
        audio_vae: Optional[Any] = None,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        ref_images: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_videos: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_video_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
        ref_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    ) -> io.NodeOutput:
        latent, frame_count = empty_av_latent(width, height, length)

        frame_items: List[RefItem] = []
        keyframes: List[Dict[str, Any]] = []
        if first_frame is not None:
            # geometry anchor: plain stretch to canvas
            img = resize_frames(first_frame[:1], width, height, "disabled")
            frame_items.append({"type": "image", "data": img})
            keyframes.append({"resolved_frame_index": 0, "image": img})
        if last_frame is not None:
            # follower: aspect-preserving cover-crop
            img = resize_frames(last_frame[:1], width, height, "center")
            frame_items.append({"type": "image", "data": img})
            keyframes.append({"resolved_frame_index": frame_count - 1, "image": img})

        picture_items, ref_blocks = _encode_ref_images(vae, ref_images or {}, width, height, ref_image_size)
        video_items, video_blocks = _encode_ref_videos(vae, audio_vae, ref_videos or {}, ref_video_audios or {}, frame_count)
        audio_items, audio_blocks = _encode_ref_audios(audio_vae, ref_audios or {})

        # Presentation order: pictures, then videos (each soundtrack right before its
        # video), then standalone audio. The frames are presentation-only here; they
        # reach the model as keyframes, not as reference blocks.
        ref_items = order_picture_items(frame_picture_tags, frame_items, picture_items) + video_items + audio_items
        ref_blocks = ref_blocks + video_blocks + audio_blocks

        tokens = clip.tokenize(prompt, minimax_ref_items=ref_items)
        cond = clip.encode_from_tokens_scheduled(tokens)

        values: Dict[str, Any] = {}
        if keyframes:
            for kf in keyframes:
                kf["latent"] = vae.encode(kf.pop("image"))
            values["minimax_keyframes"] = keyframes
        if ref_blocks:
            values["minimax_refs"] = ref_blocks
        if values:
            cond = node_helpers.conditioning_set_values(cond, values)
        return io.NodeOutput(cond, latent)


NODES: List[Type[io.ComfyNode]] = [ArisuMiniMaxH3HybridToVideo]
