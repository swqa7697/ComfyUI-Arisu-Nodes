"""Read-only stdio MCP: context metadata and selected skill text, never image bytes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from contract import INPUTS, SKILL, context, skill_text

ROOT = INPUTS
MAX_MESSAGE = 1024 * 1024


def call(name: str, arguments: Dict[str, Any], root: Path = ROOT, skill: Path = SKILL) -> Dict[str, Any]:
    """Read metadata and skill text only, never image bytes."""
    if name == "get_context" and arguments == {}:
        value = json.dumps(context(root), ensure_ascii=False)
    elif name == "read_skill" and isinstance(arguments, dict) and set(arguments) == {"path"}:
        value = skill_text(arguments["path"], skill)
    else:
        raise ValueError("unknown tool or arguments")
    return {"content": [{"type": "text", "text": value}]}


def respond(message: Dict[str, Any], root: Path = ROOT, skill: Path = SKILL) -> Dict[str, Any]:
    """Handle the MCP initialization and read-only tool subset."""
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "arisu-workbench", "version": "3"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "get_context",
                    "description": "Read duration, aspect, requirements, trigger words, keyframes, grouped references, and motion stills.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                },
                {
                    "name": "read_skill",
                    "description": "Read selected skill text, starting with SKILL.md and its relative references.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        params = message.get("params", {})
        try:
            return call(params["name"], params.get("arguments", {}), root, skill)
        except (KeyError, ValueError, OSError, TypeError):
            return {"isError": True, "content": [{"type": "text", "text": "Unavailable context asset or invalid request."}]}
    raise ValueError("unsupported method")


def main():
    """Read bounded JSONL messages; stdout contains protocol messages only."""
    while line := sys.stdin.buffer.readline(MAX_MESSAGE + 1):
        if len(line) > MAX_MESSAGE:
            return
        identifier = None
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise TypeError("invalid message")
            if "id" not in message:
                continue
            identifier = message["id"]
            response = {"jsonrpc": "2.0", "id": identifier, "result": respond(message)}
        except (ValueError, KeyError, TypeError):
            response = {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32600, "message": "Invalid MCP request"}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
