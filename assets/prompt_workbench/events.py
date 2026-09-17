"""Framed provider activity, separate from validation and final output extraction."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _text(content: Any) -> str:
    """Keep textual tool results; never forward image or other binary blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text")
    return ""


def activity(event: Dict[str, Any], provider: str = "") -> str:
    """Encode one provider event as a single physical line with explicit text boundaries."""
    entries: List[Dict[str, str]] = []

    def add(kind: str, text: Any, identifier: str = "", details: str = ""):
        entries.append({"id": provider + ":" + identifier if identifier else "", "kind": kind, "text": str(text), "details": details})

    kind = event.get("type", "progress")
    item = event.get("item") or {}
    item_type = item.get("type", "")
    identifier = str(item.get("id", ""))
    if item_type in ("reasoning", "agent_message"):
        add("analysis" if item_type == "reasoning" else "agent", item.get("text", ""), identifier)
    elif item_type == "mcp_tool_call":
        result = item.get("result") or {}
        details = json.dumps(item.get("arguments", {}), ensure_ascii=False, indent=2)
        details += "\n" + _text(result.get("content"))
        if item.get("error"):
            details += "\n" + str(item["error"])
        add("tool", str(item.get("server", "")) + "." + str(item.get("tool", "")), identifier, details)
    elif isinstance(event.get("message"), dict):
        message = event["message"]
        message_id = str(message.get("id") or event.get("uuid") or "")
        for index, block in enumerate(message.get("content", [])):
            block_type = block.get("type")
            block_id = message_id + ":" + str(index) if message_id else ""
            if block_type in ("thinking", "text"):
                add("analysis" if block_type == "thinking" else "agent", block.get("thinking", block.get("text", "")), block_id)
            elif block_type == "tool_use":
                add(
                    "tool",
                    block.get("name", "Tool call"),
                    str(block.get("id", "")),
                    json.dumps(block.get("input", {}), ensure_ascii=False, indent=2),
                )
            elif block_type == "tool_result":
                # A separate ID preserves the call arguments while correlating its result.
                call_id = str(block.get("tool_use_id", ""))
                add("tool", "Tool result", call_id + ":result" if call_id else "", _text(block.get("content")))
    elif kind == "error" or kind == "turn.failed":
        error = event.get("error")
        add(
            "error",
            error.get("message", "Agent request failed") if isinstance(error, dict) else event.get("message", "Agent request failed"),
        )
    elif kind == "system":
        add(
            "details",
            "Agent session",
            details=json.dumps(
                {key: event[key] for key in ("subtype", "model", "permissionMode", "tools") if key in event}, ensure_ascii=False, indent=2
            ),
        )
    elif kind in ("thread.started", "turn.started", "turn.completed", "result"):
        # The Grok result repeats assistant output and includes usage/session metadata.
        add("progress", "Generation complete" if kind in ("turn.completed", "result") else "Generation started", kind)
    else:
        add("details", "Agent event: " + str(kind))
    return "ARISU_ACTIVITY " + json.dumps({"version": 1, "entries": entries}, ensure_ascii=False)
