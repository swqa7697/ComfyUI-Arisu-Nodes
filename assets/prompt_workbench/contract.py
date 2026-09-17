"""Shared read authorization and output contract, independent of provider CLIs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

POLICY_REVISION = 6
REFUSAL = "ARISU_POLICY_REFUSAL"
INPUTS = Path("/inputs")
SKILL = Path("/skill")
TOOLS = ("get_context", "read_skill")
MAX_TEXT = 1024 * 1024


def contained_file(root: Path, relative: str) -> Path:
    """Accept only regular files beneath a fixed root, without symlink traversal."""
    if not isinstance(relative, str) or not relative or any(c in relative for c in ("\\", ":", "\x00")):
        raise ValueError("invalid relative file")
    parts = relative.split("/")
    if any(part in ("", ".", "..") or part.startswith("~") for part in parts):
        raise ValueError("invalid relative file")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink is not an authorized file")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("unavailable file")
    return path


def context(root: Path = INPUTS) -> Dict[str, Any]:
    """Load bounded metadata and authorize the container paths it advertises."""
    path = contained_file(root, "context.json")
    if path.stat().st_size > MAX_TEXT:
        raise ValueError("context exceeds limit")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 3 or not isinstance(data.get("assets"), list):
        raise ValueError("unsupported context manifest")
    seen = {}
    for index, asset in enumerate(data["assets"], 1):
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", asset["id"]):
            raise ValueError("invalid context asset")
        if asset["id"] in seen or asset.get("file") != asset["id"] + ".webp" or asset.get("mime") != "image/webp":
            raise ValueError("duplicate or invalid attachment")
        if type(asset.get("attachment_index")) is not int or asset["attachment_index"] != index or not isinstance(asset.get("note"), str):
            raise ValueError("invalid attachment identity")
        if any(type(asset.get(key)) is not int or not 1 <= asset[key] <= 4000 for key in ("width", "height")):
            raise ValueError("invalid attachment dimensions")
        file = contained_file(root, asset["file"])
        if not 12 <= file.stat().st_size <= 16 * 1024 * 1024:
            raise ValueError("invalid raster image size")
        with file.open("rb") as handle:
            header = handle.read(12)
        if header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            raise ValueError("invalid WebP attachment")
        asset["path"] = "/inputs/" + asset["file"]
        seen[asset["id"]] = asset
    linked = set()

    def link(identifier: str, role: str, resource: Any = None, note: Any = None):
        if identifier not in seen or identifier in linked or seen[identifier].get("role") != role:
            raise ValueError("invalid attachment association")
        asset = seen[identifier]
        if resource is not None and asset.get("resource_id") != resource:
            raise ValueError("attachment resource mismatch")
        if note is not None and asset["note"] != note:
            raise ValueError("attachment note mismatch")
        linked.add(identifier)

    for position, entry in data.get("keyframes", {}).items():
        if position not in ("first", "last"):
            raise ValueError("invalid keyframe role")
        if entry is not None:
            link(entry["asset_id"], position + "_keyframe", entry.get("resource_id"))
    for entry in data.get("references", []):
        inspection = entry["inspect"]
        if entry["kind"] == "image":
            if len(inspection["asset_ids"]) != 1:
                raise ValueError("image attachment missing")
            for identifier in inspection["asset_ids"]:
                link(identifier, "reference", entry["id"], entry["note"])
        elif entry["kind"] == "video":
            if not 1 <= len(inspection["frames"]) <= 8:
                raise ValueError("invalid video attachment count")
            for frame in inspection["frames"]:
                link(frame["asset_id"], "reference_video_frame", entry["id"], entry["note"])
        elif entry["kind"] != "audio" or inspection != {"type": "none"}:
            raise ValueError("invalid reference type")
    motion = data.get("motion", {})
    if bool(motion.get("stills")) != bool(motion.get("present")):
        raise ValueError("motion presence mismatch")
    for frame in motion.get("stills", []):
        link(frame["asset_id"], "motion", "motion", motion["notes"])
    if linked != set(seen):
        raise ValueError("unassociated attachment")
    return data


def skill_text(relative: str, root: Path = SKILL) -> str:
    """Read bounded UTF-8 skill documentation; never execute skill scripts."""
    path = contained_file(root, relative)
    if path.suffix.lower() not in (".md", ".txt") or path.stat().st_size > MAX_TEXT:
        raise ValueError("unavailable skill document")
    return path.read_text(encoding="utf-8")


def final_response(value: str) -> str:
    """Validate stream output, including the explicit policy refusal signal."""
    if not isinstance(value, str) or REFUSAL in value:
        raise ValueError("request refused by the prompt-only policy")
    match = re.fullmatch(r"\s*```(?:markdown|text)?[ \t]*\r?\n([\s\S]*?)\r?\n```\s*", value)
    if not match or not match[1].strip() or "```" in match[1] or len(match[1]) > 65536:
        raise ValueError("agent must return one nonempty markdown or plain-text fence")
    return value
