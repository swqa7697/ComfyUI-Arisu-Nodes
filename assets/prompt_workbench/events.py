"""Readable provider activity without binary image payloads."""

from __future__ import annotations

import json
from typing import Any, Dict


def activity(event: Dict[str, Any]) -> str:
    """Render provider-exposed text and tool activity without binary image payloads."""
    kind = event.get("type", "progress")
    item = event.get("item", {})
    item_type = item.get("type", "")
    if item_type in ("reasoning", "agent_message"):
        label = "analysis" if item_type == "reasoning" else "agent"
        return "[" + label + "] " + str(item.get("text", ""))
    if item_type == "command_execution":
        return "[command · " + kind + "] " + str(item.get("command", "")) + "\n" + str(item.get("aggregated_output", ""))
    if item_type == "mcp_tool_call":
        output = "[tool · " + kind + "] " + str(item.get("server", "")) + "." + str(item.get("tool", ""))
        output += "\n" + json.dumps(item.get("arguments", {}), ensure_ascii=False, indent=2)
        result = item.get("result") or {}
        for block in result.get("content", []):
            if block.get("type") == "text":
                output += "\n" + str(block.get("text", ""))
        if item.get("error"):
            output += "\n" + str(item["error"])
        return output
    if item_type == "web_search":
        return "[search] " + str(item.get("query", ""))
    if item_type in ("file_change", "todo_list"):
        return "[" + item_type + "] " + json.dumps(item.get("changes", item.get("items", [])), ensure_ascii=False, indent=2)
    message = event.get("message")
    blocks = message.get("content", []) if isinstance(message, dict) else []
    output = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in ("thinking", "text"):
            output.append(
                "[" + ("analysis" if block_type == "thinking" else "agent") + "] " + str(block.get("thinking", block.get("text", "")))
            )
        elif block_type == "tool_use":
            output.append("[tool] " + str(block.get("name", "")) + "\n" + json.dumps(block.get("input", {}), ensure_ascii=False, indent=2))
        elif block_type == "tool_result":
            content = block.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(part.get("text", "")) for part in content if part.get("type") == "text")
            output.append("[tool result] " + str(content))
    if output:
        return "\n".join(output)
    if isinstance(event.get("error"), dict):
        return "[error] " + str(event["error"].get("message", "Agent request failed"))
    return "[" + str(kind) + "] " + str(event.get("message", "") if isinstance(event.get("message"), str) else item.get("message", ""))
