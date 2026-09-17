"""Codex managed hook: normalize only known tool schemas."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gate import main


def normalize(message: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    name = message.get("tool_name", "")
    arguments = message.get("tool_input", {})
    if name in ("mcp__workbench__get_context", "mcp__workbench__read_skill"):
        return name.removeprefix("mcp__workbench__"), arguments
    return "invalid", {}


if __name__ == "__main__":
    main(normalize, "codex")
