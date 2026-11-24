"""Contained resource probing and timestamp-aware media reading, without models."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from fractions import Fraction
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import av
import numpy as np
from PIL import Image, ImageOps

from ..common.core import MAX_THUMBNAIL, MIN_THUMBNAIL, encode_preview, image_content_type, open_raster_image
from ..common.media import UnsupportedMedia, open_media, origin_for, revision_for, source_file, streams
from .core import (
    Resource,
    ResourceBundle,
    align_clip_frames,
    auto_crop,
    clip_frames,
    clip_interval,
    media_kind,
    parse_resources,
    ref_video_canvas,
)


def upright(frame: av.VideoFrame) -> Image.Image:
    """Apply display rotation without changing the source's spatial resolution."""
    image = frame.to_image()
    rotation = round(getattr(frame, "rotation", 0)) % 360
    if rotation:
        image = image.rotate(rotation, expand=True)
    return image


def stream_duration(container: av.container.InputContainer, stream: Any, *, packets_only: bool = False) -> float:
    """Resolve elapsed stream duration even when a container stores absolute end times."""
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    # Matroska DURATION tags are absolute presentation endpoints, not elapsed lengths.
    recorded = stream.metadata.get("DURATION", "")
    parts = recorded.split(":")
    if len(parts) == 3:
        try:
            hours, minutes, seconds = (float(part) for part in parts)
            elapsed = hours * 3600 + minutes * 60 + seconds - float(origin_for(stream))
            if math.isfinite(elapsed) and elapsed > 0:
                return elapsed
        except ValueError:
            pass
    if container.duration is None:
        raise UnsupportedMedia("media needs a finite duration")
    # For containers without per-stream duration, inspect the final presentation interval.
    estimate = Fraction(container.duration + (container.start_time or 0), av.time_base)
    container.seek(max(0, int(estimate / stream.time_base)), stream=stream, backward=True)
    if packets_only:
        # Audio is notes-only during writing. Use packet timestamps when the header omits the stream length.
        ends = (
            (packet.pts + packet.duration) * packet.time_base
            for packet in container.demux(stream)
            if packet.pts is not None and packet.duration and packet.time_base
        )
        last = max(ends, default=None)
        if last is None:
            raise UnsupportedMedia("cannot establish audio clip bounds from timestamps")
        return float(last - origin_for(stream))
    end = None
    for frame in container.decode(stream):
        if frame.pts is None:
            raise UnsupportedMedia("media timestamps are unavailable")
        duration = (
            Fraction(frame.samples, frame.sample_rate)
            if isinstance(frame, av.AudioFrame)
            else (frame.duration * frame.time_base if frame.duration else Fraction(1, 1) / (stream.average_rate or 24))
        )
        end = frame.pts * frame.time_base + duration
    if end is None:
        raise UnsupportedMedia("cannot establish finite media duration")
    container.seek(max(0, stream.start_time or 0), stream=stream, backward=True)
    return float(end - origin_for(stream))


def metadata(roots: Mapping[str, str], item: Resource, *, audio_headers_only: bool = False) -> Dict[str, Any]:
    """Probe image dimensions or finite media timing through an authorized handle."""
    if media_kind(item.path) is None:
        raise UnsupportedMedia("unsupported resource extension")
    with source_file(roots, item) as handle:
        stat = os.fstat(handle.fileno())
        revision = revision_for(stat)
        if image_content_type(item.path):
            with open_raster_image(handle) as image:
                width, height = image.size
                if image.getexif().get(274, 1) in (5, 6, 7, 8):
                    width, height = height, width
            return {"kind": "image", "width": width, "height": height, "size": stat.st_size, "revision": revision}
        try:
            with open_media(handle) as container:
                video, audio = streams(container)
                main = video or audio
                if main is None:
                    raise UnsupportedMedia("no usable media stream")
                if audio_headers_only and video is not None:
                    raise UnsupportedMedia("resource kind does not match the file")
                duration = stream_duration(container, main, packets_only=audio_headers_only)
                if not math.isfinite(duration) or duration <= 0:
                    raise UnsupportedMedia("media needs a finite duration")
                width = height = 0
                if video is not None:
                    frame = next(container.decode(video), None)
                    if frame is None:
                        raise UnsupportedMedia("video has no decodable frames")
                    width, height = upright(frame).size
                return {
                    "kind": "video" if video else "audio",
                    "duration": duration,
                    "has_audio": audio is not None,
                    "width": width,
                    "height": height,
                    "rate": float(video.average_rate or 0) if video else audio.rate,
                    "origin": float(origin_for(main)),
                    "size": stat.st_size,
                    "revision": revision,
                }
        except (av.FFmpegError, EOFError, StopIteration) as error:
            raise UnsupportedMedia("unsupported or incomplete media") from error


def poster(roots: Mapping[str, str], item: Resource, at: float, max_size: int) -> bytes:
    """Encode the upright video frame presented at source-relative ``at`` as a bounded WEBP still."""
    if not math.isfinite(at) or at < 0:
        raise ValueError("poster time must be a finite non-negative number")
    bound = min(MAX_THUMBNAIL, max(MIN_THUMBNAIL, max_size))
    try:
        with source_file(roots, item) as handle, open_media(handle) as container:
            video, _audio = streams(container)
            if video is None:
                raise UnsupportedMedia("no video stream")
            if at > stream_duration(container, video) + 1e-9:
                raise ValueError("poster time exceeds the source duration")
            target = origin_for(video) + Fraction(str(at))
            container.seek(int(target / video.time_base), stream=video, backward=True)
            chosen = None
            for frame in container.decode(video):
                if frame.pts is None:
                    raise UnsupportedMedia("video timestamps are unavailable")
                if chosen is not None and frame.pts * frame.time_base > target:
                    break
                chosen = frame
            if chosen is None:
                raise UnsupportedMedia("video has no decodable frames")
            return encode_preview(upright(chosen), bound)
    except (av.FFmpegError, EOFError, StopIteration) as error:
        raise UnsupportedMedia("unsupported or incomplete media") from error


def validate_workbench_source(roots: Mapping[str, str], item: Resource, ratio: Optional[str] = None) -> Resource:
    """Freeze the source revision and creative selection; audio preparation only needs notes."""
    if item.kind == "audio":
        if media_kind(item.path) not in ("video", "audio"):
            raise UnsupportedMedia("unsupported audio resource extension")
        with source_file(roots, item) as handle:
            return replace(item, revision=revision_for(os.fstat(handle.fileno())))
    return validate_source(roots, item, ratio)


def validate_source(roots: Mapping[str, str], item: Resource, ratio: Optional[str] = None) -> Resource:
    """Validate a source and freeze its current revision and effective crop."""
    return apply_selection(item, metadata(roots, item), ratio)


def apply_selection(item: Resource, info: Mapping[str, Any], ratio: Optional[str] = None) -> Resource:
    """Validate a crop or clip against metadata from the authorized source revision."""
    if info["kind"] != item.kind:
        raise UnsupportedMedia("resource kind does not match the file")
    result = replace(item, revision=info["revision"])
    if item.kind == "image":
        if ratio is not None and item.crop_basis_ratio != ratio:
            result = replace(result, crop=auto_crop(info["width"], info["height"], ratio), crop_basis_ratio=ratio)
        if result.crop:
            left, top, width, height = result.crop
            if left + width > info["width"] or top + height > info["height"]:
                raise ValueError("crop exceeds source bounds")
    else:
        if item.clip is None:
            raise ValueError("missing clip")
        clip_interval(dict(zip(("start", "end"), item.clip)), info["duration"])
        if item.kind == "video":
            result = replace(result, include_audio=item.include_audio and info["has_audio"])
    return result


def build_bundle(roots: Mapping[str, str], text: str, ratio: str) -> ResourceBundle:
    """Validate active sources and group immutable descriptors for Hybrid."""
    first, last, references = parse_resources(text)
    keys = [validate_source(roots, item, ratio) if item is not None and not item.muted else None for item in (first, last)]
    active = [validate_source(roots, item) for item in references if not item.muted]
    return ResourceBundle(*keys, *(tuple(item for item in active if item.kind == kind) for kind in ("image", "video", "audio")))


def source_fingerprint(roots: Mapping[str, str], text: str, ratio: Optional[str]) -> str:
    """Fingerprint active file revisions and canonical instructions, not muted files."""
    first, last, references = parse_resources(text)
    values = []
    for item in (first, last, *references):
        if item is not None and not item.muted:
            with source_file(roots, item) as handle:
                values.append(
                    (
                        item.kind,
                        item.root,
                        item.path,
                        item.crop,
                        item.crop_basis_ratio,
                        item.clip,
                        item.include_audio,
                        revision_for(os.fstat(handle.fileno())),
                    )
                )
    return hashlib.sha256(json.dumps([ratio, values], sort_keys=True).encode()).hexdigest()


def read_image(roots: Mapping[str, str], item: Resource) -> np.ndarray:
    """Read original upright cropped pixels, without generation resizing."""
    with source_file(roots, item) as handle, open_raster_image(handle) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if item.crop:
            left, top, width, height = item.crop
            image = image.crop((left, top, left + width, top + height))
        return np.asarray(image, dtype=np.float32)[None] / 255.0


def read_audio(
    roots: Mapping[str, str],
    item: Resource,
    origin: Optional[Fraction] = None,
    interval: Optional[Tuple[Union[float, Fraction], Union[float, Fraction]]] = None,
) -> Tuple[np.ndarray, int]:
    """Decode sample-aligned audio, preserving genuine gaps as silence."""
    start, end = interval or item.clip or (0, 0)
    with source_file(roots, item) as handle, open_media(handle) as container:
        video, audio = streams(container)
        if audio is None:
            raise UnsupportedMedia("no audio stream")
        base = origin if origin is not None else origin_for(audio)
        rate = audio.rate
        first_sample, last_sample = math.ceil((base + Fraction(str(start))) * rate), math.ceil((base + Fraction(str(end))) * rate)
        if last_sample <= first_sample:
            raise ValueError("selection contains no audio samples")
        channels = len(audio.layout.channels)
        output = np.zeros((channels, last_sample - first_sample), dtype=np.float32)
        container.seek(max(0, int((base + Fraction(str(start))) / audio.time_base)), stream=audio, backward=True)
        resampler = av.AudioResampler(format="fltp", layout=audio.layout, rate=rate)
        covered = False
        for frame in container.decode(audio):
            if frame.pts is None:
                raise UnsupportedMedia("audio timestamps are unavailable")
            position = round(frame.pts * frame.time_base * rate)
            if position >= last_sample:
                break
            for converted in resampler.resample(frame):
                position = round(converted.pts * converted.time_base * rate) if converted.pts is not None else position
                samples = converted.to_ndarray()
                left, right = max(first_sample, position), min(last_sample, position + samples.shape[1])
                if right > left:
                    output[:, left - first_sample : right - first_sample] = samples[:, left - position : right - position]
                    covered = True
        if not covered and video is None:
            raise UnsupportedMedia("selection has no audio coverage")
        return output[None], rate


def read_video(roots: Mapping[str, str], item: Resource, frame_count: int) -> Tuple[np.ndarray, Optional[Tuple[np.ndarray, int]]]:
    """Sample presentation intervals at 24 fps and resize each retained frame once."""
    start, end = item.clip or (0, 0)
    count = align_clip_frames(clip_frames(start, end), frame_count)
    samples = [Fraction(str(start)) + Fraction(i, 24) for i in range(count)]
    images: List[np.ndarray] = []
    with source_file(roots, item) as handle, open_media(handle) as container:
        video, _audio = streams(container)
        if video is None:
            raise UnsupportedMedia("no video stream")
        base = origin_for(video)
        container.seek(int((base + samples[0]) / video.time_base), stream=video, backward=True)
        previous = None
        previous_time = None
        size = None

        def collect(frame: av.VideoFrame, left: Fraction, right: Fraction):
            nonlocal size
            while len(images) < count and samples[len(images)] < right:
                if samples[len(images)] < left:
                    raise UnsupportedMedia("selected video interval has no frame coverage")
                picture = upright(frame)
                if size is None:
                    size = ref_video_canvas(*picture.size)
                if picture.size != size:
                    picture = picture.resize(size, Image.Resampling.LANCZOS)
                images.append(np.asarray(picture, dtype=np.float32) / 255.0)

        for frame in container.decode(video):
            if frame.pts is None:
                raise UnsupportedMedia("video timestamps are unavailable")
            current = frame.pts * frame.time_base - base
            if previous is not None and current > previous_time:
                collect(previous, previous_time, current)
            previous, previous_time = frame, current
            if len(images) == count:
                break
        if len(images) < count and previous is not None:
            duration = previous.duration * previous.time_base if previous.duration else Fraction(1, 1) / (video.average_rate or 24)
            collect(previous, previous_time, previous_time + duration)
        if len(images) != count:
            raise UnsupportedMedia("selected video interval has incomplete frame coverage")
    soundtrack = (
        read_audio(roots, item, base, (Fraction(str(start)), Fraction(str(start)) + Fraction(count, 24))) if item.include_audio else None
    )
    return np.stack(images), soundtrack
