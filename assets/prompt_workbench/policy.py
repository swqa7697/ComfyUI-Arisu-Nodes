"""Immutable Codex tool gate; custom/user hooks are never loaded.

Codex can advertise apply_patch independently of its shell feature. This managed
PreToolUse gate denies it (and unknown local tools) before execution, in addition
to the native read-only sandbox. Hosted web tools are disabled in configuration.
"""

from __future__ import annotations

import errno
import json
import sys
from pathlib import Path
from typing import Any, Dict

TOOLS = ("get_context", "read_image", "read_skill")


def decision(message: Dict[str, Any]) -> Dict[str, Any]:
    """Allow only the fixed read-only MCP surface, without rewriting arguments."""
    allowed = message.get("hook_event_name") == "PreToolUse" and message.get("tool_name") in {"mcp__workbench__" + tool for tool in TOOLS}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if allowed else "deny",
            "permissionDecisionReason": "Workbench permits only its context, image, and skill readers.",
        }
    }


def main():
    """Return an explicit denial even for malformed or oversized hook input."""
    if sys.argv[1:] == ["--sandbox-probe"]:
        # /tmp is writable to the CLI itself, but must not be writable to a
        # Codex sandboxed tool. Never confuse a sandbox startup error with this.
        path = Path("/tmp/arisu-sandbox-probe")
        try:
            with path.open("xb") as output:
                output.write(b"sandbox probe")
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
                print("ARISU_SANDBOX_DENIED")
                return
            raise
        path.unlink()
        raise SystemExit("sandbox allowed a forbidden write")
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        message = json.loads(raw) if len(raw) <= 1024 * 1024 else {}
        if not isinstance(message, dict):
            message = {}
    except (ValueError, OSError):
        message = {}
    print(json.dumps(decision(message)), flush=True)


if __name__ == "__main__":
    main()
