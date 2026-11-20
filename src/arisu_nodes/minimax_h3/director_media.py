"""Resolve only the Director sources needed for a generation or creative task."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from .core import Resource, ResourceBundle, VideoSettings
from .director import asset_resource, parse_document, prompt_tags, segment_bindings, segment_snapshot
from .media import apply_selection, metadata, revision_for, source_file, validate_source, validate_workbench_source


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
