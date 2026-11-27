"""Resolve only the Director sources needed for a generation or creative task."""

from __future__ import annotations

import hashlib
import math
import os
import posixpath
import re
from bisect import bisect_right
from fractions import Fraction
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

import av
from PIL import Image

from ..common.core import relative_path
from ..common.media import MediaRef, open_media, revision_for, source_file, source_path, streams
from ..common.video import director_take_id
from .core import (
    FPS,
    MOTION_SAMPLE_LIMIT,
    MOTION_SAMPLE_STRIDE,
    MotionFootageError,
    Resource,
    ResourceBundle,
    VideoSettings,
    frames_for_duration,
)
from .director import asset_resource, parse_document, prompt_tags, segment_bindings, segment_snapshot
from .media import apply_selection, metadata, stream_duration, upright, validate_source, validate_workbench_source

_TAKE_VIDEO = re.compile(r"(?:clip\.mp4|clip_[0-9]{5,}_\.(?:mp4|webm|mov|mkv))")
# A seek can land at the beginning of a long GOP. Bound the scan even for a malformed output.
_MAX_TAKE_FRAMES = frames_for_duration(150)


def director_video_path(take: str, video: str, project: str) -> str:
    """Name one saved Director video in the legacy or project layout."""
    if not all(isinstance(value, str) for value in (take, video, project)) or not _TAKE_VIDEO.fullmatch(video):
        raise ValueError("invalid Director take")
    directory = f"{relative_path(project)}/director/{take}" if project else f"arisu_director/{take}"
    if director_take_id(directory) != take:
        raise ValueError("invalid Director take")
    return f"{directory}/{video}"


def director_video_ref(take: str, video: str, project: str) -> MediaRef:
    """Freeze a fixed output-video reference from a Director receipt."""
    return MediaRef("output", director_video_path(take, video, project))


def verify_director_video(roots: Mapping[str, str], item: MediaRef):
    """Verify that the actual file belongs to the named take directory."""
    directory, name = posixpath.split(item.path)
    take = director_take_id(directory)
    try:
        output = roots["output"]
        path = source_path(roots, "output", item.path)
        actual = os.path.relpath(path, os.path.realpath(output)).replace(os.sep, "/")
        if item.root != "output" or not take or not _TAKE_VIDEO.fullmatch(name) or actual != item.path:
            raise ValueError("invalid Director video location")
    except (OSError, ValueError, KeyError) as error:
        raise MotionFootageError("the previous Director video is unavailable") from error


def read_director_tail(roots: Mapping[str, str], item: MediaRef) -> Iterator[Tuple[Image.Image, float]]:
    """Read chronological half-second observations anchored to the final displayed video frame."""
    verify_director_video(roots, item)
    try:
        with source_file(roots, item) as handle, open_media(handle) as container:
            video, _ = streams(container)
            if video is None or not video.time_base:
                raise ValueError("no timed video stream")
            duration = stream_duration(container, video, packets_only=True)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("invalid video duration")
            stride = Fraction(MOTION_SAMPLE_STRIDE, FPS)
            tail_start = max(0.0, duration - float(MOTION_SAMPLE_LIMIT * stride))
            container.seek((video.start_time or 0) + int(tail_start / video.time_base), stream=video, backward=True)
            # Packet PTS identify the actual last picture even when container duration includes trailing audio.
            times = []
            for index, packet in enumerate(container.demux(video)):
                if index > _MAX_TAKE_FRAMES:
                    raise ValueError("video exceeds Director segment bounds")
                if packet.pts is not None:
                    times.append(packet.pts)
            if not times:
                raise ValueError("missing video timestamps")
            times.sort()
            selected = set()
            for index in range(MOTION_SAMPLE_LIMIT):
                pos = bisect_right(times, times[-1] - index * stride / video.time_base) - 1
                if pos < 0:
                    break
                selected.add(times[pos])
            first = min(selected)
            container.seek(first, stream=video, backward=True)
            for index, frame in enumerate(container.decode(video)):
                if index > _MAX_TAKE_FRAMES:
                    raise ValueError("video exceeds Director segment bounds")
                if frame.pts in selected:
                    yield upright(frame), float((frame.pts - first) * video.time_base)
                    selected.remove(frame.pts)
                    if not selected:
                        break
            if selected:
                raise ValueError("incomplete Director video")
    except (OSError, ValueError, EOFError, OverflowError, av.FFmpegError) as error:
        raise MotionFootageError("the previous Director video could not be sampled") from error
    verify_director_video(roots, item)


def _resolve(
    bundle: ResourceBundle,
    roots: Mapping[str, str],
    ratio: str,
    scope: str,
    *,
    preparation: bool = False,
    probes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> ResourceBundle:
    def source(item: Resource, keyframe: bool = False) -> Resource:
        try:
            if probes is not None:
                if item.id not in probes:
                    probes[item.id] = metadata(roots, item, audio_headers_only=item.kind == "audio")
                return apply_selection(item, probes[item.id], ratio if keyframe else None)
            if preparation:
                return validate_workbench_source(roots, item, ratio if keyframe else None)
            return validate_source(roots, item, ratio if keyframe else None)
        except (OSError, ValueError) as error:
            raise ValueError(f"{scope}: reselect asset {item.id}; its source or selection is unavailable") from error

    return ResourceBundle(
        source(bundle.first, True) if bundle.first else None,
        source(bundle.last, True) if bundle.last else None,
        tuple(source(item) for item in bundle.images),
        tuple(source(item) for item in bundle.videos),
        tuple(source(item) for item in bundle.audios),
    )


def library_resources(document: Dict[str, Any], roots: Mapping[str, str]) -> ResourceBundle:
    """Resolve the whole unmuted library for a single director task, independent of per-render limits."""
    items = [asset_resource(a) for a in document["assets"] if not a.get("muted")]
    bundle = ResourceBundle(None, None, *(tuple(item for item in items if item.kind == kind) for kind in ("image", "video", "audio")))
    return _resolve(bundle, roots, document["film"]["aspect_ratio"], "Film library", preparation=True)


def segment_resources(document: Dict[str, Any], roots: Mapping[str, str], segment_id: str) -> ResourceBundle:
    """Use the target segment's bindings and overrides in footage-informed revision tasks."""
    segment = next(s for s in document["segments"] if s["id"] == segment_id)
    try:
        bundle = segment_bindings(document, segment)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Segment {segment_id}: {error}") from error
    return _resolve(bundle, roots, document["film"]["aspect_ratio"], f"Segment {segment_id}", preparation=True)


def validate_draft_media(document: Dict[str, Any], result: Dict[str, Any], task: str, roots: Mapping[str, str]):
    """Check the proposed per-segment overrides and soundtrack tags before exposing the draft."""
    ratio = document["film"]["aspect_ratio"]
    mode = document["film"]["frame_picture_tags"]
    probes: Dict[str, Dict[str, Any]] = {}
    for segment in result["segments"] if task == "plan" else [result["segment"]]:
        bundle = segment_bindings(document, segment)
        active = _resolve(bundle, roots, ratio, f"Segment {segment['id']}", preparation=True, probes=probes)
        prompt_tags(segment["prompt"], segment["id"], active, mode)


def render_outputs(text: str, roots: Mapping[str, str]) -> Tuple[str, VideoSettings, ResourceBundle]:
    """Emit a consistent snapshot, taking soundtrack ordinals from real source streams."""
    document = parse_document(text)
    segment, settings, bundle = segment_snapshot(document)
    active = _resolve(bundle, roots, settings.aspect_ratio, f"Segment {segment['id']}")
    # Capture associations before probing: a disappeared or silent soundtrack cannot silently retarget another Audio tag.
    prompt = prompt_tags(segment["prompt"], segment["id"], active, document["film"]["frame_picture_tags"])
    return prompt, settings, active


def render_fingerprint(text: str, roots: Mapping[str, str]) -> str:
    """Include the finalized snapshot and every selected source revision in ComfyUI's cache key."""
    segment, _, bundle = segment_snapshot(parse_document(text))
    fingerprint = hashlib.sha256(text.encode("utf-8"))
    for item in bundle.sources():
        try:
            with source_file(roots, item) as handle:
                fingerprint.update(revision_for(os.fstat(handle.fileno())).encode())
        except (ValueError, OSError) as error:
            raise ValueError(f"Segment {segment['id']}: reselect asset {item.id}") from error
    return fingerprint.hexdigest()
