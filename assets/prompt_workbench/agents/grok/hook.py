"""Grok managed hook: normalize only known tool schemas."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gate import main


def normalize(message: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    name = message.get("toolName", "")
    arguments = message.get("toolInput", {})
    if message.get("toolInputTruncated"):
        return "invalid", {}
    if name == "search_tool":
        return "discover", arguments
    if name == "use_tool" and isinstance(arguments, dict) and set(arguments) == {"tool_name", "tool_input"}:
        name, arguments = arguments["tool_name"], arguments["tool_input"]
    if name in ("workbench__get_context", "workbench__read_skill"):
        # Grok hooks report the resolved MCP name but retain the use_tool envelope.
        if isinstance(arguments, dict) and set(arguments) == {"tool_name", "tool_input"}:
            if arguments["tool_name"] != name:
                return "invalid", {}
            arguments = arguments["tool_input"]
        return name.removeprefix("workbench__"), arguments
    return "invalid", {}


if __name__ == "__main__":
    main(normalize, "grok")
