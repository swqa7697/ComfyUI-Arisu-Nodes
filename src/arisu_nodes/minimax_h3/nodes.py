"""MiniMax H3 V3 nodes.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.

The tensor helpers mirror ``comfy_extras/nodes_minimax_h3.py`` (v0.34.5) rather
than importing its underscore-private names, so a ComfyUI rename cannot break
the pack at import time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

import comfy.model_management
import comfy.nested_tensor
import comfy.sd
import comfy.utils
import node_helpers
import torch
import torchaudio
from comfy_api.latest import io
from nodes import MAX_RESOLUTION

from .core import (
    ASPECT_RATIO_LABELS,
    AUDIO_CHANNELS,
    AUDIO_LATENT_CHANNELS,
    FRAME_TAG_MODES,
    REF_IMAGE_SIZE_MODES,
    VIDEO_LATENT_CHANNELS,
    align_clip_frames,
    canvas_from_megapixels,
    frame_needs_resize,
    frames_for_duration,
    keyframe_canvases,
    latent_size,
    order_picture_items,
    qwen_sample_indices,
    qwen_timestamps,
    ref_image_canvas,
    ref_video_canvas,
    scaled_canvas,
    soundtrack_key,
    temporal_shape,
)

RefItem = Dict[str, Any]
RefBlock = Dict[str, Any]
Conditioning = List[List[Any]]
# A keyframe before it is fitted to a canvas: (frames [1, H, W, C], crop mode, resolved frame index).
KeyframeSource = Tuple[torch.Tensor, str, int]


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


def fit_frames(image: torch.Tensor, width: int, height: int, crop: str) -> torch.Tensor:
    """Fit an image batch to ``width`` x ``height``, skipping the resize when it already matches.

    ComfyUI's lanczos path round-trips through 8-bit images even at the same
    size, so a batch that already has the canvas size is passed through as is,
    minus any alpha channel.

    Args:
        image: Frames shaped ``[B, H, W, C]`` in the 0-1 range.
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        crop: ``"disabled"`` for a plain stretch or ``"center"`` for an aspect-preserving cover-crop.

    Returns:
        Frames shaped ``[B, height, width, 3]``.
    """
    if frame_needs_resize(image.shape, width, height):
        return resize_frames(image, width, height, crop)
    return image[..., :3]


def encode_ref_audio(audio_vae: comfy.sd.VAE, audio: Dict[str, Any]) -> Tuple[torch.Tensor, int]:
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


def _require_audio_vae(audio_vae: Optional[comfy.sd.VAE]) -> comfy.sd.VAE:
    if audio_vae is None:
        raise ValueError("encoding reference audio needs the audio_vae input")
    return audio_vae


def _encode_ref_images(
    vae: Any, ref_images: Dict[str, Optional[torch.Tensor]], canvases: Sequence[Tuple[int, int]], ref_image_size: str
) -> Tuple[List[RefItem], List[List[RefBlock]]]:
    """Encode the reference images for every canvas, once per distinct size.

    Returns the tokenizer items for the first canvas (the prompt is encoded
    once) and one block list per canvas. A block is shared between canvases
    whenever ``ref_image_canvas`` yields the same size for both, which is
    always the case for ``"max"`` and for references smaller than the canvas.
    """
    items: List[RefItem] = []
    blocks_per_canvas: List[List[RefBlock]] = [[] for _ in canvases]
    for img in ref_images.values():
        if img is None:
            continue
        encoded: Dict[Tuple[int, int], RefBlock] = {}
        for canvas_blocks, (canvas_w, canvas_h) in zip(blocks_per_canvas, canvases):
            size = ref_image_canvas(img.shape[2], img.shape[1], canvas_w, canvas_h, ref_image_size)
            block = encoded.get(size)
            if block is None:
                resized = resize_frames(img[:1], size[0], size[1], "disabled")
                if not encoded:
                    # the text encoder sees the reference at the generation canvas only
                    items.append({"type": "image", "data": resized})
                latent_h, latent_w = latent_size(size[0], size[1])
                block = {"kind": "image", "latent_h": latent_h, "latent_w": latent_w, "latent": vae.encode(resized)}
                encoded[size] = block
            canvas_blocks.append(block)
    return items, blocks_per_canvas


def _encode_ref_videos(
    vae: Any,
    audio_vae: Optional[comfy.sd.VAE],
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


def _encode_ref_audios(
    audio_vae: Optional[comfy.sd.VAE], ref_audios: Dict[str, Optional[Dict[str, Any]]]
) -> Tuple[List[RefItem], List[RefBlock]]:
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


def _keyframe_sources(first_frame: Optional[torch.Tensor], last_frame: Optional[torch.Tensor], frame_count: int) -> List[KeyframeSource]:
    sources: List[KeyframeSource] = []
    if first_frame is not None:
        # geometry anchor: plain stretch to canvas
        sources.append((first_frame[:1], "disabled", 0))
    if last_frame is not None:
        # follower: aspect-preserving cover-crop
        sources.append((last_frame[:1], "center", frame_count - 1))
    return sources


def _fit_keyframes(sources: Sequence[KeyframeSource], width: int, height: int) -> List[torch.Tensor]:
    return [fit_frames(img, width, height, crop) for img, crop, _index in sources]


def encode_hybrid(
    clip: Any,
    vae: Any,
    audio_vae: Optional[comfy.sd.VAE],
    prompt: str,
    canvases: Sequence[Tuple[int, int]],
    length: int,
    ref_image_size: str,
    frame_picture_tags: str,
    first_frame: Optional[torch.Tensor],
    last_frame: Optional[torch.Tensor],
    ref_images: Dict[str, Optional[torch.Tensor]],
    ref_videos: Dict[str, Optional[torch.Tensor]],
    ref_video_audios: Dict[str, Optional[Dict[str, Any]]],
    ref_audios: Dict[str, Optional[Dict[str, Any]]],
) -> Tuple[List[Conditioning], Dict[str, Any]]:
    """Build the hybrid fl2va + ref2va conditioning, once per keyframe canvas.

    The prompt is tokenized and encoded once, with the keyframes and
    references presented on the generation canvas. Every canvas then gets its
    own conditioning sharing those text embeddings, with the keyframes encoded
    at that canvas and the reference images sized for it. Reference videos and
    audio never depend on the canvas, so their blocks are shared.

    Args:
        clip: The MiniMax H3 text encoder.
        vae: The video VAE.
        audio_vae: The audio VAE, or ``None`` when no audio reference is connected.
        prompt: The prompt text.
        canvases: ``(width, height)`` per conditioning; the first is the
            generation canvas the latent is built for.
        length: Requested frame count at 24 fps.
        ref_image_size: One of ``REF_IMAGE_SIZE_MODES``.
        frame_picture_tags: One of ``FRAME_TAG_MODES``.
        first_frame: Optional keyframe pinned at frame 0.
        last_frame: Optional keyframe pinned at the last frame.
        ref_images: Autogrow slot dict of reference images.
        ref_videos: Autogrow slot dict of reference clips.
        ref_video_audios: Autogrow slot dict of reference clip soundtracks.
        ref_audios: Autogrow slot dict of standalone reference audios.

    Returns:
        ``(conditionings, latent)``: one conditioning per canvas, in order, and
        the empty AV latent for the generation canvas.
    """
    width, height = canvases[0]
    latent, frame_count = empty_av_latent(width, height, length)

    sources = _keyframe_sources(first_frame, last_frame, frame_count)
    base_frames = _fit_keyframes(sources, width, height)
    frame_items: List[RefItem] = [{"type": "image", "data": img} for img in base_frames]

    picture_items, image_blocks = _encode_ref_images(vae, ref_images, canvases, ref_image_size)
    video_items, video_blocks = _encode_ref_videos(vae, audio_vae, ref_videos, ref_video_audios, frame_count)
    audio_items, audio_blocks = _encode_ref_audios(audio_vae, ref_audios)

    # Presentation order: pictures, then videos (each soundtrack right before its
    # video), then standalone audio. The frames are presentation-only here; they
    # reach the model as keyframes, not as reference blocks.
    ref_items = order_picture_items(frame_picture_tags, frame_items, picture_items) + video_items + audio_items

    tokens = clip.tokenize(prompt, minimax_ref_items=ref_items)
    cond = clip.encode_from_tokens_scheduled(tokens)

    conds: List[Conditioning] = []
    for i, (canvas_w, canvas_h) in enumerate(canvases):
        frames = base_frames if i == 0 else _fit_keyframes(sources, canvas_w, canvas_h)
        ref_blocks = image_blocks[i] + video_blocks + audio_blocks
        values: Dict[str, Any] = {"minimax_refs": ref_blocks} if ref_blocks else {}
        if sources:
            values["minimax_keyframes"] = [
                {"resolved_frame_index": index, "latent": vae.encode(img)} for img, (_src, _crop, index) in zip(frames, sources)
            ]
        conds.append(node_helpers.conditioning_set_values(cond, values) if values else cond)
    return conds, latent


def _hybrid_inputs_head() -> List[io.Input]:
    return [
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
    ]


def _hybrid_inputs_tail() -> List[io.Input]:
    return [
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
                input=io.Image.Input("ref_image", tooltip="Reference image (downscaled to 2048 short edge if larger, never upscaled)"),
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
    ]


class ArisuMiniMaxH3HybridToVideo(io.ComfyNode):
    """fl2va and ref2va in one conditioning: first/last keyframes plus references.

    ComfyUI's stock nodes set either ``minimax_keyframes`` (Image to Video) or
    ``minimax_refs`` (Reference to Video) and each builds its own latent, so
    they cannot be chained. The model already packs both, keyframes first, so
    this node sets both keys on one conditioning and returns one AV latent.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema with the shared hybrid inputs and two outputs: the positive
            conditioning and the empty AV latent.
        """
        return io.Schema(
            node_id="ArisuMiniMaxH3HybridToVideo",
            display_name="MiniMax H3 Hybrid to Video",
            category="Arisu Nodes/MiniMax H3",
            description=(
                "MiniMax H3 conditioning with first/last keyframes and <Picture i> / <Video k> / <Audio j> "
                "references in one node. Outputs positive conditioning and the AV latent."
            ),
            inputs=[*_hybrid_inputs_head(), *_hybrid_inputs_tail()],
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
        audio_vae: Optional[comfy.sd.VAE] = None,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        ref_images: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_videos: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_video_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
        ref_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    ) -> io.NodeOutput:
        """Encode the hybrid conditioning and build the matching AV latent.

        Args:
            clip: The MiniMax H3 text encoder.
            vae: The video VAE.
            prompt: The prompt text.
            width: Generation canvas width in pixels.
            height: Generation canvas height in pixels.
            length: Requested frame count at 24 fps; snapped up to the model's 17k+5 grid.
            ref_image_size: One of ``REF_IMAGE_SIZE_MODES``.
            frame_picture_tags: One of ``FRAME_TAG_MODES``.
            audio_vae: The audio VAE, or ``None`` when no audio reference is connected.
            first_frame: Optional keyframe pinned at frame 0.
            last_frame: Optional keyframe pinned at the last frame.
            ref_images: Autogrow slot dict of reference images.
            ref_videos: Autogrow slot dict of reference clips.
            ref_video_audios: Autogrow slot dict of reference clip soundtracks.
            ref_audios: Autogrow slot dict of standalone reference audios.

        Returns:
            ``(positive, latent)``: the conditioning for the generation canvas and
            the empty AV latent built for it.
        """
        conds, latent = encode_hybrid(
            clip,
            vae,
            audio_vae,
            prompt,
            [(width, height)],
            length,
            ref_image_size,
            frame_picture_tags,
            first_frame,
            last_frame,
            ref_images or {},
            ref_videos or {},
            ref_video_audios or {},
            ref_audios or {},
        )
        return io.NodeOutput(conds[0], latent)


class ArisuMiniMaxH3HybridToVideoAdvanced(io.ComfyNode):
    """The hybrid node plus a second conditioning whose keyframes fit the upscaled video.

    In a two-sampler latent-upscale workflow the keyframe latents of the first
    pass are on the wrong spatial grid for the second sampler. Re-encoding the
    original pixel keyframes at the target size keeps them sharp, unlike
    resampling their latents.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema with the hybrid inputs plus ``target_width`` / ``target_height``,
            and three outputs: the positive conditioning for the generation canvas,
            the empty AV latent, and the positive conditioning for the upscaled canvas.
        """
        return io.Schema(
            node_id="ArisuMiniMaxH3HybridToVideoAdvanced",
            display_name="MiniMax H3 Hybrid to Video (Advanced)",
            category="Arisu Nodes/MiniMax H3",
            description=(
                "MiniMax H3 Hybrid to Video for two-sampler latent upscaling: also outputs a positive conditioning "
                "whose keyframes are encoded at target_width x target_height, for the sampler that refines the "
                "upscaled latent."
            ),
            inputs=[
                *_hybrid_inputs_head(),
                io.Int.Input(
                    "target_width",
                    default=2688,
                    min=32,
                    max=MAX_RESOLUTION,
                    step=32,
                    tooltip="Width of the upscaled video, as produced by the latent upscaler between the two samplers.",
                ),
                io.Int.Input(
                    "target_height",
                    default=1536,
                    min=32,
                    max=MAX_RESOLUTION,
                    step=32,
                    tooltip="Height of the upscaled video, as produced by the latent upscaler between the two samplers.",
                ),
                *_hybrid_inputs_tail(),
            ],
            outputs=[
                io.Conditioning.Output("positive"),
                io.Latent.Output("latent"),
                io.Conditioning.Output(
                    "positive_upscaled",
                    display_name="positive (upscaled)",
                    tooltip="Same prompt and references, with the keyframes encoded at target_width x target_height.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        clip: Any,
        vae: Any,
        prompt: str,
        width: int,
        height: int,
        target_width: int,
        target_height: int,
        length: int,
        ref_image_size: str,
        frame_picture_tags: str,
        audio_vae: Optional[comfy.sd.VAE] = None,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        ref_images: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_videos: Optional[Dict[str, Optional[torch.Tensor]]] = None,
        ref_video_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
        ref_audios: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    ) -> io.NodeOutput:
        """Encode one conditioning per keyframe canvas and build the AV latent.

        Args:
            clip: The MiniMax H3 text encoder.
            vae: The video VAE.
            prompt: The prompt text.
            width: Generation canvas width in pixels.
            height: Generation canvas height in pixels.
            target_width: Width of the upscaled video the second sampler refines.
            target_height: Height of the upscaled video the second sampler refines.
            length: Requested frame count at 24 fps; snapped up to the model's 17k+5 grid.
            ref_image_size: One of ``REF_IMAGE_SIZE_MODES``.
            frame_picture_tags: One of ``FRAME_TAG_MODES``.
            audio_vae: The audio VAE, or ``None`` when no audio reference is connected.
            first_frame: Optional keyframe pinned at frame 0.
            last_frame: Optional keyframe pinned at the last frame.
            ref_images: Autogrow slot dict of reference images.
            ref_videos: Autogrow slot dict of reference clips.
            ref_video_audios: Autogrow slot dict of reference clip soundtracks.
            ref_audios: Autogrow slot dict of standalone reference audios.

        Returns:
            ``(positive, latent, positive_target)``: the conditioning for the
            generation canvas, the empty AV latent built for it, and the conditioning
            whose keyframes are encoded at the target size. When the target size
            equals the generation size both conditionings are the same object.
        """
        conds, latent = encode_hybrid(
            clip,
            vae,
            audio_vae,
            prompt,
            keyframe_canvases(width, height, target_width, target_height),
            length,
            ref_image_size,
            frame_picture_tags,
            first_frame,
            last_frame,
            ref_images or {},
            ref_videos or {},
            ref_video_audios or {},
            ref_audios or {},
        )
        # with a single canvas both conditionings are the same object: nothing was encoded twice
        return io.NodeOutput(conds[0], latent, conds[-1])


def _settings_inputs_head() -> List[io.Input]:
    return [
        io.Combo.Input(
            "aspect_ratio",
            options=list(ASPECT_RATIO_LABELS),
            default="16:9 (Widescreen)",
            tooltip="Aspect ratio of the generation canvas.",
        ),
        io.Float.Input(
            "megapixels",
            default=1.0,
            min=0.1,
            max=16.0,
            step=0.1,
            tooltip=(
                "Pixel budget of the canvas in megapixels (1 MP = 1024 x 1024), rounded to multiples of 32. "
                "The stock 1344 x 768 canvas is about 0.98 MP."
            ),
        ),
    ]


def _settings_inputs_tail() -> List[io.Input]:
    return [
        io.Float.Input(
            "duration",
            default=5.0,
            min=0.2,
            max=150.0,
            step=0.1,
            tooltip="Clip length in seconds at 24 fps, snapped up to the model's 17k+5 frame grid (5.0 s = 124 frames).",
        ),
        io.Boolean.Input(
            "advertise",
            default=False,
            tooltip=(
                "Drive every MiniMax H3 Hybrid to Video node in this graph: their size and length widgets grey out at once, "
                "refuse links, and take these values. Off by default. Read by the frontend; the outputs stay available either way."
            ),
        ),
    ]


def _settings_outputs_head() -> List[io.Output]:
    return [
        io.Int.Output("width", tooltip="Canvas width in pixels, a multiple of 32."),
        io.Int.Output("height", tooltip="Canvas height in pixels, a multiple of 32."),
        io.Int.Output("length", tooltip="Frame count on the 17k+5 grid, for the hybrid nodes' length input."),
    ]


class ArisuMiniMaxH3VideoSettings(io.ComfyNode):
    """One place for the canvas and the clip length of a MiniMax H3 workflow.

    Replaces the aspect-ratio / megapixel / duration helper chains workflows
    build from generic math nodes, and with ``advertise`` on hands the result
    to the hybrid nodes without a link.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema taking an aspect ratio, a pixel budget and a duration, and returning
            width, height and length.
        """
        return io.Schema(
            node_id="ArisuMiniMaxH3VideoSettings",
            display_name="MiniMax H3 Video Settings",
            category="Arisu Nodes/MiniMax H3",
            description=(
                "Canvas size from an aspect ratio and a megapixel budget, and frame count from a duration in seconds, "
                "on MiniMax H3's grids. Wire the outputs into the hybrid nodes, or switch advertise on and every "
                "MiniMax H3 Hybrid to Video node in this graph takes them automatically."
            ),
            inputs=[*_settings_inputs_head(), *_settings_inputs_tail()],
            outputs=_settings_outputs_head(),
        )

    @classmethod
    def execute(cls, aspect_ratio: str, megapixels: float, duration: float, advertise: bool) -> io.NodeOutput:
        """Derive the canvas and frame count.

        Args:
            aspect_ratio: One of ``ASPECT_RATIO_LABELS``.
            megapixels: Pixel budget in units of 1024 x 1024.
            duration: Clip length in seconds.
            advertise: Frontend-only flag; the backend does not read it.

        Returns:
            ``(width, height, length)``.
        """
        width, height = canvas_from_megapixels(aspect_ratio, megapixels)
        return io.NodeOutput(width, height, frames_for_duration(duration))


class ArisuMiniMaxH3VideoSettingsUpscale(io.ComfyNode):
    """The video settings node plus the target size of a latent-upscale pass."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The settings schema with an ``upscale_factor`` input and the upscale factor and
            target size added to the outputs.
        """
        return io.Schema(
            node_id="ArisuMiniMaxH3VideoSettingsUpscale",
            display_name="MiniMax H3 Video Settings (Upscale)",
            category="Arisu Nodes/MiniMax H3",
            description=(
                "MiniMax H3 Video Settings for two-sampler latent-upscale workflows: also derives the upscaled "
                "target size from an upscale factor, for the Advanced hybrid node and the latent upscaler."
            ),
            inputs=[
                *_settings_inputs_head(),
                io.Float.Input(
                    "upscale_factor",
                    default=2.0,
                    min=1.0,
                    max=8.0,
                    step=0.05,
                    tooltip="Factor of the latent upscaler between the two samplers; the target size is rounded to multiples of 32.",
                ),
                *_settings_inputs_tail(),
            ],
            outputs=[
                *_settings_outputs_head(),
                io.Float.Output("upscale_factor", tooltip="The factor, for a latent upscaler's multiplier input."),
                io.Int.Output("target_width", tooltip="Upscaled width in pixels, a multiple of 32."),
                io.Int.Output("target_height", tooltip="Upscaled height in pixels, a multiple of 32."),
            ],
        )

    @classmethod
    def execute(cls, aspect_ratio: str, megapixels: float, upscale_factor: float, duration: float, advertise: bool) -> io.NodeOutput:
        """Derive the canvas, the upscaled target and the frame count.

        Args:
            aspect_ratio: One of ``ASPECT_RATIO_LABELS``.
            megapixels: Pixel budget in units of 1024 x 1024.
            upscale_factor: Factor of the latent upscale pass.
            duration: Clip length in seconds.
            advertise: Frontend-only flag; the backend does not read it.

        Returns:
            ``(width, height, length, upscale_factor, target_width, target_height)``.
        """
        width, height = canvas_from_megapixels(aspect_ratio, megapixels)
        target_width, target_height = scaled_canvas(width, height, upscale_factor)
        return io.NodeOutput(width, height, frames_for_duration(duration), upscale_factor, target_width, target_height)


NODES: List[Type[io.ComfyNode]] = [
    ArisuMiniMaxH3HybridToVideo,
    ArisuMiniMaxH3HybridToVideoAdvanced,
    ArisuMiniMaxH3VideoSettings,
    ArisuMiniMaxH3VideoSettingsUpscale,
]
