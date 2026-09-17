"""Managed pre-tool gate shared by provider-specific hook adapters."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

from contract import INPUTS, MAX_TEXT, SKILL
from mcp_server import call

AUDIT = Path("/home/agent/tool-audit.jsonl")


def authorize(name: str, arguments: Dict[str, Any], root: Path = INPUTS, skill: Path = SKILL) -> bool:
    """Authorize normalized tools and complete arguments, with deny as default."""
    try:
        if not isinstance(arguments, dict):
            return False
        if name in ("get_context", "read_skill"):
            call(name, arguments, root, skill)
        elif name == "discover":
            return (
                set(arguments) <= {"query", "limit"}
                and isinstance(arguments.get("query"), str)
                and len(arguments["query"]) <= 1024
                and type(arguments.get("limit", 5)) is int
                and 1 <= arguments.get("limit", 5) <= 1000
            )
        else:
            return False
        return True
    except (ValueError, TypeError, KeyError, OSError):
        return False


def main(normalize: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]], provider: str):
    """Always emit a denial on malformed input; persist decisions for the runner."""
    allowed, name, arguments = False, "invalid", {}
    message = {}
    try:
        raw = sys.stdin.buffer.read(MAX_TEXT + 1)
        if len(raw) <= MAX_TEXT:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise TypeError("invalid hook message")
            if isinstance(message, dict) and message.get("hook_event_name") == "PreToolUse":
                name, arguments = normalize(message)
                allowed = authorize(name, arguments)
        record = {
            "tool": name,
            "arguments": arguments,
            "allowed": allowed,
            "source_tool": str(message.get("toolName", message.get("tool_name", "")))[:128],
        }
        descriptor = os.open(AUDIT, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(json.dumps(record) + "\n")
    except (ValueError, TypeError, KeyError, OSError):
        allowed = False
    reason = "Workbench permits only context and selected skill text."
    if provider == "codex":
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if allowed else "deny",
                "permissionDecisionReason": reason,
            }
        }
    else:
        result = {"decision": "allow" if allowed else "deny", "reason": reason}
    print(json.dumps(result), flush=True)
