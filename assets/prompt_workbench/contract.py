"""Shared read authorization and output contract, independent of provider CLIs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

POLICY_REVISION = 5
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
    seen = set()
    for asset in data["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str) or asset["id"] in seen:
            raise ValueError("invalid context asset")
        seen.add(asset["id"])
        if asset.get("mime") in ("image/png", "image/jpeg", "image/webp"):
            file = contained_file(root, asset["file"])
            if file.stat().st_size > 16 * 1024 * 1024 or file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                raise ValueError("invalid raster image")
            asset["path"] = "/inputs/" + asset["file"]
        else:
            asset.pop("path", None)
    return data


def image_path(value: str, root: Path = INPUTS) -> Path:
    """Authorize an exact manifest-listed mounted image, never a generic read."""
    if not isinstance(value, str) or not value.startswith("/inputs/"):
        raise ValueError("image is outside the job")
    relative = value[len("/inputs/") :]
    path = contained_file(root, relative)
    if not any(asset.get("path") == value for asset in context(root)["assets"]):
        raise ValueError("image is not listed")
    return path


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
