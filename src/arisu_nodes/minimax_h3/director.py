"""Versioned film, binding, timeline and creative-result contracts for the Director Workbench."""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .core import (
    ASPECT_RATIO_LABELS,
    CLIP_FRAME_STEP,
    FPS,
    FRAME_TAG_MODES,
    MIN_CLIP_FRAMES,
    MOTION_WINDOWS,
    RESOURCE_LIMITS,
    Resource,
    ResourceBundle,
    VideoSettings,
    canvas_from_megapixels,
    clip_frames,
    media_kind,
    order_picture_items,
    parse_resource,
)

DOCUMENT_LIMIT = 1024 * 1024
RESULT_LIMIT = 256 * 1024
MAX_SEGMENTS = 128
FILM_DEFAULTS = {
    "brief": "",
    "requirements": [],
    "triggers": "",
    "continuity": "",
    "aspect_ratio": "16:9 (Widescreen)",
    "megapixels": 1.0,
    "min_seconds": 5.0,
    "max_seconds": 15.0,
    "target_runtime": "",
    "writing_skill": "",
    "frame_picture_tags": "after_refs",
}
EMPTY_FILM = json.dumps(
    {"version": 1, "film": FILM_DEFAULTS, "assets": [], "segments": [], "selected": "", "outline": "", "continuity": "", "coverage": {}},
    separators=(",", ":"),
)
ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
TAG = re.compile(r"<(Picture|Video|Audio)(?:\s+(\d+)|:([^<>\s]+))>")
BINDING_FIELDS = {"crop", "crop_basis_ratio", "clip", "include_audio"}
SEGMENT_FIELDS = {
    "id",
    "intent",
    "seconds",
    "transition",
    "overlap_frames",
    "prompt",
    "opening",
    "closing",
    "bindings",
    "skill",
    "skill_reason",
    "skill_locked",
}


def read_json(text: str, limit: int, label: str) -> Dict[str, Any]:
    """Decode a bounded versioned object, rejecting ambiguous keys and nonfinite numbers."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > limit:
        raise ValueError(f"{label} exceeds the {limit // 1024} KiB size limit")

    def unique(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError(f"duplicate {label} field")
        return obj

    def finite(number: str) -> float:
        val = float(number)
        if not math.isfinite(val):
            raise ValueError(f"nonfinite {label} number")
        return val

    try:
        obj = json.loads(text, object_pairs_hook=unique, parse_constant=finite, parse_float=finite)
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError(f"incomplete or invalid {label} JSON") from error
    if not isinstance(obj, dict) or type(obj.get("version")) is not int or obj["version"] != 1:
        raise ValueError(f"unsupported {label} version")
    return obj


def _text(value: Any, name: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (required and not value.strip()):
        raise ValueError(f"invalid or missing {name} (maximum {limit} characters)")
    return value


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"invalid {name} ID")
    return value


def _list(value: Any, name: str, limit: int) -> List[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name} must be a list of at most {limit} items")
    return value


def _number(value: Any, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


def segment_frames(seconds: float, min_seconds: float, max_seconds: float) -> int:
    """Snap to the nearest available 24 fps H3 grid point, with ties upward."""
    _number(min_seconds, "minimum duration", 0.2, 150)
    _number(max_seconds, "maximum duration", min_seconds, 150)
    first = max(0, math.ceil((min_seconds * FPS - MIN_CLIP_FRAMES) / CLIP_FRAME_STEP))
    last = math.floor((max_seconds * FPS - MIN_CLIP_FRAMES) / CLIP_FRAME_STEP)
    if first > last:
        raise ValueError("No H3 frame count fits this duration range. Adjust the minimum or maximum.")
    _number(seconds, "segment duration", min_seconds, max_seconds)
    step = math.floor((seconds * FPS - MIN_CLIP_FRAMES) / CLIP_FRAME_STEP + 0.5)
    return MIN_CLIP_FRAMES + CLIP_FRAME_STEP * max(first, min(last, step))


def asset_resource(asset: Dict[str, Any], binding: Optional[Dict[str, Any]] = None) -> Resource:
    """Combine a library selection with one segment's permitted overrides."""
    source = {k: v for k, v in asset.items() if k not in ("note", "revision")}
    keyframe = binding is not None and binding["role"] in ("first", "last")
    if binding:
        source.update({k: v for k, v in binding.items() if k in BINDING_FIELDS})
    if not keyframe:
        source.pop("crop_basis_ratio", None)
    return replace(parse_resource(source, keyframe), revision=asset.get("revision", ""))


def _segment_fields(segment: Dict[str, Any]):
    """Check editable fields before including them in a planning snapshot."""
    if set(segment) - SEGMENT_FIELDS:
        raise ValueError("unknown segment field")
    for field in ("intent", "opening", "closing", "skill", "skill_reason", "prompt"):
        limit = 65536 if field == "prompt" else 160 if field == "skill" else 4096
        _text(segment.get(field), field, limit)
    if type(segment.get("skill_locked")) is not bool or (segment["skill_locked"] and not segment["skill"]):
        raise ValueError("select a writing skill before locking it")
    if segment.get("transition") not in ("cut", "continuation") or type(segment.get("overlap_frames")) is not int:
        raise ValueError("invalid segment transition")
    _number(segment.get("seconds"), "segment duration", 0.2, 150)
    for binding in _list(segment.get("bindings"), "bindings", 17):
        if not isinstance(binding, dict) or set(binding) - BINDING_FIELDS - {"asset_id", "role"}:
            raise ValueError("invalid binding fields")
        _id(binding.get("asset_id"), "bound asset")
        if binding.get("role") not in ("first", "last", "image", "video", "audio"):
            raise ValueError("invalid binding role")


def _index(items: Sequence[Dict[str, Any]], name: str) -> Dict[str, Dict[str, Any]]:
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise TypeError(f"invalid {name}")
        key = _id(item.get("id"), name)
        if key in result:
            raise ValueError(f"duplicate {name} ID {key}")
        result[key] = item
    return result


def parse_document(text: str) -> Dict[str, Any]:
    """Read editable film state. Unfinished segments can coexist with a renderable selected segment."""
    doc = read_json(text, DOCUMENT_LIMIT, "film")
    if set(doc) - {"version", "film", "assets", "segments", "selected", "outline", "continuity", "coverage"}:
        raise ValueError("unknown film document field")
    if not isinstance(doc.get("film"), dict) or set(doc["film"]) - FILM_DEFAULTS.keys():
        raise ValueError("invalid film settings")
    film = doc["film"] = {**FILM_DEFAULTS, **doc["film"]}
    for field, limit in (("brief", 32768), ("triggers", 16384), ("continuity", 16384), ("target_runtime", 256), ("writing_skill", 160)):
        _text(film[field], field, limit)
    requirements = _list(film["requirements"], "requirements", 128)
    for req in requirements:
        _text(req, "requirement", 1024, True)
    if len(set(requirements)) != len(requirements):
        raise ValueError("duplicate story requirement")
    if film["aspect_ratio"] not in ASPECT_RATIO_LABELS or film["frame_picture_tags"] not in FRAME_TAG_MODES:
        raise ValueError("invalid film canvas ratio or keyframe tag setting")
    _number(film["megapixels"], "megapixels", 0.1, 16)
    segment_frames(film["min_seconds"], film["min_seconds"], film["max_seconds"])
    for asset in _index(_list(doc.get("assets"), "assets", 256), "asset").values():
        asset.setdefault("muted", False)
        _text(asset.get("note", ""), "asset note", 4096)
        _text(asset.get("revision", ""), "source revision", 128)
        if asset.get("crop_basis_ratio") is not None and asset["crop_basis_ratio"] not in ASPECT_RATIO_LABELS:
            raise ValueError(f"Asset {asset['id']}: invalid crop basis")
        item = asset_resource(asset)
        if media_kind(item.path) is None:
            raise ValueError(f"Asset {item.id}: unsupported media extension")
    segments = _index(_list(doc.get("segments"), "segments", MAX_SEGMENTS), "segment")
    for segment in segments.values():
        try:
            _segment_fields(segment)
        except ValueError as error:
            raise ValueError(f"Segment {segment['id']}: {error}") from error
    selected = doc.setdefault("selected", "")
    if not isinstance(selected, str) or (segments and selected not in segments) or (not segments and selected):
        raise ValueError("select an existing segment")
    _text(doc.setdefault("outline", ""), "outline", 32768)
    _text(doc.setdefault("continuity", ""), "continuity decisions", 32768)
    if not isinstance(doc.setdefault("coverage", {}), dict):
        raise TypeError("invalid requirement coverage")
    return doc


def segment_bindings(doc: Dict[str, Any], segment: Dict[str, Any]) -> ResourceBundle:
    """Resolve a segment's bindings independently of the duration or prompt being edited."""
    assets = {asset["id"]: asset for asset in doc["assets"]}
    groups: Dict[str, List[Resource]] = {role: [] for role in ("first", "last", "image", "video", "audio")}
    seen = set()
    for binding in _list(segment.get("bindings"), "bindings", 17):
        if not isinstance(binding, dict) or set(binding) - BINDING_FIELDS - {"asset_id", "role"}:
            raise ValueError("invalid binding fields")
        asset_id, role = _id(binding.get("asset_id"), "bound asset"), binding.get("role")
        if not isinstance(role, str) or role not in groups:
            raise ValueError(f"asset {asset_id} has an invalid role")
        asset = assets.get(asset_id)
        if not asset or asset.get("muted"):
            raise ValueError(f"asset {asset_id} is missing or muted")
        if asset_id in seen or asset["kind"] != ("image" if role in ("first", "last") else role):
            raise ValueError(f"asset {asset_id} is duplicated or incompatible with role {role}")
        seen.add(asset_id)
        if len(groups[role]) >= RESOURCE_LIMITS.get(role, 1):
            raise ValueError(f"too many {role} bindings at asset {asset_id}")
        item = asset_resource(asset, binding)
        if role == "video" and item.clip and clip_frames(*item.clip) < MIN_CLIP_FRAMES:
            raise ValueError(f"video asset {asset_id} needs at least {MIN_CLIP_FRAMES} frames")
        groups[role].append(item)
    return ResourceBundle(
        next(iter(groups["first"]), None),
        next(iter(groups["last"]), None),
        tuple(groups["image"]),
        tuple(groups["video"]),
        tuple(groups["audio"]),
    )


def prompt_tags(prompt: str, segment_id: str, bundle: ResourceBundle, mode: str, *, stable: bool = False) -> str:
    """Resolve ordinal tags and stable asset tags through the same physical H3 input order."""
    keys = [v.id for v in (bundle.first, bundle.last) if v is not None]
    tags = {
        "Picture": order_picture_items(mode, keys, [v.id for v in bundle.images]),
        "Video": [v.id for v in bundle.videos],
        "Audio": [v.id for v in bundle.videos if v.include_audio] + [v.id for v in bundle.audios],
    }

    def substitute(match: re.Match) -> str:
        kind, ordinal, asset_id = match.groups()
        ids = tags[kind]
        if ordinal is not None:
            if len(ordinal) > 3 or not 1 <= int(ordinal) <= len(ids):
                raise ValueError(f"Segment {segment_id}: unbound tag {match[0]}")
            asset_id = ids[int(ordinal) - 1]
        if asset_id not in ids:
            raise ValueError(f"Segment {segment_id}: asset {asset_id} has no {kind} binding")
        return f"<{kind}:{asset_id}>" if stable else f"<{kind} {ids.index(asset_id) + 1}>"

    return TAG.sub(substitute, prompt)


def segment_snapshot(doc: Dict[str, Any], segment_id: Optional[str] = None) -> Tuple[Dict[str, Any], VideoSettings, ResourceBundle]:
    """Select and validate a render snapshot before any media I/O."""
    key = segment_id if segment_id is not None else doc["selected"]
    segments = doc["segments"]
    index = next((i for i, s in enumerate(segments) if s["id"] == key), None)
    if index is None:
        raise ValueError("Plan the film or add a segment before rendering.")
    seg, film = segments[index], doc["film"]
    try:
        frames = segment_frames(seg.get("seconds"), film["min_seconds"], film["max_seconds"])
        overlap = seg.get("overlap_frames")
        if type(overlap) is not int:
            raise ValueError("invalid overlap frame count")
        if seg.get("transition") == "continuation":
            if index == 0 or str(overlap) not in MOTION_WINDOWS or overlap >= frames:
                raise ValueError("continuation needs a predecessor and a shorter supported Motion Context window")
            previous_seconds = segments[index - 1].get("seconds")
            previous_frames = segment_frames(previous_seconds, film["min_seconds"], film["max_seconds"])
            if previous_frames < overlap:
                raise ValueError("predecessor has too few frames for this overlap")
        elif seg.get("transition") != "cut" or overlap:
            raise ValueError("a hard cut requires zero overlap")
        _text(seg.get("prompt"), "finalized prompt", 65536, True)
        bundle = segment_bindings(doc, seg)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Segment {key}: {error}") from error
    stable = prompt_tags(seg["prompt"], key, bundle, film["frame_picture_tags"], stable=True)
    width, height = canvas_from_megapixels(film["aspect_ratio"], film["megapixels"])
    return (
        {**seg, "prompt": stable},
        VideoSettings(width, height, frames, film["aspect_ratio"], frame_picture_tags=film["frame_picture_tags"]),
        bundle,
    )


def validate_draft(doc: Dict[str, Any], task: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the complete response against the request snapshot without modifying finalized state."""
    # The bound also applies to direct callers, independently of provider output limits.
    result = read_json(json.dumps(result, ensure_ascii=False, separators=(",", ":")), RESULT_LIMIT, "director result")
    plan = task == "plan"
    fields = {"version", "outline", "continuity", "coverage", "segments"} if plan else {"version", "segment", "suggestions"}
    if task not in ("plan", "refine") or set(result) != fields:
        raise ValueError("incomplete or unexpected director result fields")
    old = {s["id"]: s for s in doc["segments"]}
    if plan:
        _text(result["outline"], "outline", 32768, True)
        _text(result["continuity"], "continuity decisions", 32768, True)
        changed = _list(result["segments"], "segments", MAX_SEGMENTS)
        ids = _index(changed, "segment")
        if not ids:
            raise ValueError("the plan must contain at least one segment")
        coverage = result["coverage"]
        if not isinstance(coverage, dict) or set(coverage) != set(doc["film"]["requirements"]):
            raise ValueError("provide coverage for each required story element")
        for req, positions in coverage.items():
            if not _list(positions, "coverage positions", MAX_SEGMENTS):
                raise ValueError(f"No segment covers requirement {req}")
            if any(not isinstance(v, str) or v not in ids for v in positions):
                raise ValueError(f"unknown segment in coverage for {req}")
        for segment_id, prior in old.items():
            if prior.get("skill_locked") and segment_id not in ids:
                raise ValueError(f"Segment {segment_id}: plan removes a locked writing skill")
        proposed = changed
    else:
        seg = result["segment"]
        if not isinstance(seg, dict) or seg.get("id") != doc["selected"] or seg.get("id") not in old:
            raise ValueError("refinement must replace the selected segment only")
        for suggestion in _list(result["suggestions"], "neighbor suggestions", 16):
            _text(suggestion, "neighbor suggestion", 4096, True)
        changed = [seg]
        proposed = [seg if s["id"] == seg["id"] else s for s in doc["segments"]]
    candidate = {**doc, "segments": proposed}
    for seg in changed:
        key = seg["id"]
        if set(seg) - SEGMENT_FIELDS:
            raise ValueError(f"Segment {key}: unknown draft fields")
        for field in ("intent", "opening", "closing", "skill", "skill_reason"):
            _text(seg.get(field), f"Segment {key} {field}", 160 if field == "skill" else 4096, True)
        locked = old.get(key, {}).get("skill_locked", False)
        required = old[key].get("skill") if locked else doc["film"]["writing_skill"]
        if required and required != seg["skill"]:
            raise ValueError(f"Segment {key}: expected writing skill {required}")
        seg["skill_locked"] = locked
        normalized, settings, _ = segment_snapshot(candidate, key)
        seg["prompt"] = _text(normalized["prompt"], f"Segment {key} normalized prompt", 65536, True)
        for binding in seg["bindings"]:
            if binding["role"] in ("first", "last") and binding.get("crop") and not binding.get("crop_basis_ratio"):
                binding["crop_basis_ratio"] = doc["film"]["aspect_ratio"]
    # Ensure a local replacement still supplies enough frames for its immediate successor.
    if not plan:
        index = next(i for i, item in enumerate(proposed) if item["id"] == doc["selected"])
        if index + 1 < len(proposed) and proposed[index + 1].get("transition") == "continuation":
            following = proposed[index + 1]
            if following.get("overlap_frames", 0) > settings.length:
                raise ValueError(f"Segment {following['id']}: replacement predecessor is too short")
    if plan:
        candidate.update({key: result[key] for key in ("outline", "continuity", "coverage")})
        candidate["selected"] = doc["selected"] if doc["selected"] in ids else changed[0]["id"]
    for value, limit, label in ((result, RESULT_LIMIT, "normalized Director result"), (candidate, DOCUMENT_LIMIT, "applied film")):
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > limit:
            raise ValueError(f"{label} exceeds the {limit // 1024} KiB size limit")
    return result
