"""Small read-only stdio MCP: a per-job manifest and its listed raster images."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path("/inputs")
MAX_MESSAGE = 1024 * 1024


def call(name: str, arguments: Dict[str, Any], root: Path = ROOT) -> Dict[str, Any]:
    """Return only this job's manifest or a manifest-authorized image."""
    manifest = json.loads((root / "context.json").read_text())
    if name == "get_context" and not arguments:
        return {"content": [{"type": "text", "text": json.dumps(manifest, ensure_ascii=False)}]}
    if name != "read_image" or set(arguments) != {"asset_id"}:
        raise ValueError("unknown tool or arguments")
    item = next((asset for asset in manifest["assets"] if asset["id"] == arguments["asset_id"]), None)
    if item is None or item["mime"] not in ("image/png", "image/jpeg", "image/webp"):
        raise ValueError("unknown image")
    path = root / item["file"]
    if path.is_symlink() or path.resolve().parent != root.resolve() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid image")
    return {"content": [{"type": "image", "mimeType": item["mime"], "data": base64.b64encode(path.read_bytes()).decode()}]}


def respond(message: Dict[str, Any], root: Path = ROOT) -> Dict[str, Any]:
    """Handle the MCP initialization and read-only tool subset."""
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "arisu-workbench", "version": "1.0"}}
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
                    "name": "read_image",
                    "description": "Read an image by its context asset ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"asset_id": {"type": "string"}},
                        "required": ["asset_id"],
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        params = message.get("params", {})
        try:
            return call(params["name"], params.get("arguments", {}), root)
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
            if "id" not in message:
                continue
            identifier = message["id"]
            response = {"jsonrpc": "2.0", "id": identifier, "result": respond(message)}
        except (ValueError, KeyError, TypeError):
            response = {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32600, "message": "Invalid MCP request"}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
