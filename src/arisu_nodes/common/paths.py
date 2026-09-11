"""Server-owned image roots, loaded once from the pack's local configuration.

This stdlib-only module owns configuration I/O. No workflow, HTTP request or
ComfyUI user setting can supply the configuration location or add a root.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

logger = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).resolve().parents[3] / "arisu_paths.json"


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def parse_roots(text: str) -> Dict[str, str]:
    """Validate administrator JSON and canonicalize existing external roots."""
    payload = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"roots"} or not isinstance(payload["roots"], dict):
        raise ValueError('expected {"roots": {"name": "/absolute/directory"}}')
    roots: Dict[str, str] = {}
    for name, path in payload["roots"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in ("input", "output"):
            raise ValueError("root IDs must be unique lowercase names; input and output are reserved")
        if not isinstance(path, str) or "\x00" in path or not os.path.isabs(path):
            raise ValueError("external roots must be absolute directory paths")
        resolved = os.path.realpath(path)
        if os.path.dirname(resolved) == resolved or not os.path.isdir(resolved):
            raise ValueError("external roots must be existing directories, not filesystem roots")
        roots[name] = resolved
    return roots


@lru_cache(maxsize=1)
def external_roots() -> Mapping[str, str]:
    """Load once; a missing or invalid local file never enables external access."""
    try:
        return parse_roots(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError):
        logger.exception("Invalid arisu_paths.json: external roots disabled. Fix the local JSON file and restart ComfyUI.")
        return {}


def image_roots(input_dir: str, output_dir: str) -> Dict[str, str]:
    """Return fixed built-in roots and the startup snapshot of external roots."""
    return {"input": input_dir, "output": output_dir, **external_roots()}


def select_root(roots: Mapping[str, str], name: Any = "input") -> str:
    """Look up a root ID without accepting caller-supplied base directories."""
    if not isinstance(name, str) or name not in roots:
        raise ValueError("unknown image root; select a configured root with Browse")
    return roots[name]
