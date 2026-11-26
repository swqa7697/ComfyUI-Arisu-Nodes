"""Framed provider activity, separate from validation and final output extraction."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, NamedTuple, Optional, Set


class EventValidationError(ValueError):
    """A provider rejection with a fixed, payload-free reason."""


class ProviderResultError(ValueError):
    """A provider failure carrying only a Workbench-defined reason code."""


class ProviderNotice(NamedTuple):
    """A validated progress message containing only safe display text."""

    text: str


def check_policy_hook(message: str):
    """Reject a failed policy hook on either native diagnostic channel."""
    text = message.lower()
    if "hook" in text and any(word in text for word in ("fail", "error", "timeout", "timed out")):
        raise EventValidationError("agent policy hook failed")


def reports_token_limit(event: Dict[str, Any]) -> bool:
    """Recognize provider limit reports without inspecting the generated answer."""
    details = json.dumps({key: event.get(key) for key in ("error", "message", "subtype", "stop_reason", "errors")}).lower()
    return any(
        marker in details
        for marker in ("context_length", "context window", "context length", "max_tokens", "max_output_tokens", "token limit")
    )


def failure_reason(event: Dict[str, Any], message: str) -> str:
    """Classify provider error text without exposing URLs, credentials or private inputs."""
    detail = message.lower()
    for reason, markers in (
        (
            "auth",
            (
                "not signed in",
                "authentication required",
                "unauthorized",
                "invalid api key",
                "invalid_api_key",
                "incorrect api key",
                "status 401",
                "http 401",
            ),
        ),
        ("usage_limit", ("usage limit", "usage_limit", "insufficient_quota", "exceeded your current quota", "free-usage-exhausted")),
        (
            "unavailable",
            (
                "temporarily at capacity",
                "overloaded",
                "service unavailable",
                "bad gateway",
                "internal server error",
                "status 503",
                "http 503",
            ),
        ),
        ("rate_limit", ("rate limit", "rate-limit", "rate_limit", "too many requests", "status 429", "http 429")),
        ("timeout", ("model stopped responding", "timed out", "deadline exceeded", "gateway timeout", "request timeout")),
        (
            "connection",
            (
                "connection closed",
                "connection reset",
                "connection refused",
                "error sending request",
                "stream disconnected",
                "stream closed before",
                "failed to connect",
            ),
        ),
        ("empty_response", ("empty response from model",)),
    ):
        if any(marker in detail for marker in markers):
            return reason
    return "token_limit" if reports_token_limit(event) else "execution"


def activity_entry(kind: str, text: str, details: str = "") -> str:
    """Frame a single anonymous status or diagnostic for the host."""
    return "ARISU_ACTIVITY " + json.dumps(
        {"version": 1, "entries": [{"id": "", "kind": kind, "text": text, "details": details}]}, ensure_ascii=False
    )


def _scalar(value: Any) -> str:
    """Bound metadata and suppress credentials, paths and terminal controls."""
    if not isinstance(value, str):
        return "<" + type(value).__name__ + ">"
    if re.search(r"(?i)bearer|token|api[_-]?key|\b(?:sk-|xai-)|[/\\\x00-\x1f\x7f]", value):
        return "<redacted>"
    return value[:160]


def _servers(value: Any) -> Any:
    if not isinstance(value, list):
        return "<" + type(value).__name__ + ">"
    return [
        {key: _scalar(item.get(key)) for key in ("name", "status")} if isinstance(item, dict) else "<" + type(item).__name__ + ">"
        for item in value[:8]
    ]


def diagnostic(event: Any, provider: str, version: Any, reason: str, kind: str = "error") -> str:
    """Describe a rejected envelope without rendering its content or tool payloads."""
    summary: Dict[str, Any] = {"provider": _scalar(provider), "cli_version": _scalar(version)}
    if isinstance(event, dict):
        keys = ("type",) if provider == "codex" else ("type", "subtype")
        summary.update({key: _scalar(event[key]) for key in keys if key in event})
        if provider == "codex" and type(event.get("exit_code")) is int and -255 <= event["exit_code"] <= 255:
            summary["exit_code"] = event["exit_code"]
        if provider == "grok" and event.get("type") == "result":
            if summary.get("subtype") not in (
                None,
                "success",
                "error_during_execution",
                "error_max_turns",
                "error_max_structured_output_retries",
            ):
                summary["subtype"] = "<unknown>"
            stop = event.get("stop_reason")
            if stop in ("end_turn", "max_tokens", "refusal", "cancelled", "stop_sequence"):
                summary["stop_reason"] = stop
            if type(event.get("num_turns")) is int and 0 <= event["num_turns"] <= 2**31 - 1:
                summary["num_turns"] = event["num_turns"]
        if provider == "grok" and "mcp_servers" in event:
            summary["mcp_servers"] = _servers(event["mcp_servers"])
    else:
        summary["event"] = "<" + type(event).__name__ + ">"
    details = json.dumps(summary, ensure_ascii=False)
    # Bound encoded bytes as well as characters; keep the summary valid JSON.
    while len(details.encode("utf-8")) > 4096:
        summary["mcp_servers"].pop()
        details = json.dumps(summary, ensure_ascii=False)
    return activity_entry(kind, reason, details)


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
    item = event.get("item") if kind in ("progress", "item.started", "item.updated", "item.completed") else {}
    item = item if isinstance(item, dict) else {}
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
    elif kind in ("assistant", "user") and isinstance(event.get("message"), dict):
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
                {
                    **{key: event[key] for key in ("subtype", "model", "permissionMode", "tools") if key in event},
                    **({"mcp_servers": _servers(event["mcp_servers"])} if "mcp_servers" in event else {}),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    elif kind in ("thread.started", "turn.started", "turn.completed", "result"):
        # The Grok result repeats assistant output and includes usage/session metadata.
        add(
            "progress", "Agent response received; validating output" if kind in ("turn.completed", "result") else "Generation started", kind
        )
    else:
        add("details", "Agent event: " + str(kind))
    return "ARISU_ACTIVITY " + json.dumps({"version": 1, "entries": entries}, ensure_ascii=False)


class ActivityStream:
    """Render bounded partial text snapshots with the completed message's stable IDs."""

    def __init__(self):
        self.message = ""
        self.completed_message = ""
        self.dirty: Set[int] = set()
        self.blocks: Dict[int, Dict[str, Any]] = {}
        self.updated: Dict[int, float] = {}

    def render(self, event: Dict[str, Any], provider: str) -> Optional[str]:
        if event.get("type") != "stream_event":
            if event.get("type") == "result" and self.message:
                raise EventValidationError("Grok completed with an unfinished partial message")
            if event.get("type") == "assistant" and self.completed_message:
                # Some backends learn the provider ID only at completion. Keep
                # the ID already used by the partial display, not the per-line UUID.
                event = {**event, "message": {**event["message"], "id": self.completed_message}}
                self.completed_message = ""
            return activity(event, provider)
        partial = event["event"]
        kind = partial["type"]
        if kind == "message_start":
            if self.message:
                raise EventValidationError("Grok overlapping partial messages")
            self.message = partial["message"]["id"]
            self.completed_message = ""
            self.dirty.clear()
            self.blocks.clear()
            self.updated.clear()
            return None
        if not self.message:
            raise EventValidationError("Grok partial event without a message")
        if kind == "message_stop":
            if self.blocks:
                raise EventValidationError("Grok partial message has unfinished blocks")
            self.completed_message = self.message
            self.message = ""
            return None
        if kind == "message_delta":
            return None
        index = partial["index"]
        if kind == "content_block_start":
            if index in self.blocks:
                raise EventValidationError("Grok duplicate partial block")
            self.blocks[index] = dict(partial["content_block"])
        block = self.blocks.get(index)
        if block is None:
            raise EventValidationError("Grok partial event without a block")
        field = {"thinking": "thinking", "text": "text"}.get(block["type"])
        if kind == "content_block_delta":
            delta = partial["delta"]
            expected = {"thinking": ("thinking_delta", "signature_delta"), "text": ("text_delta",), "tool_use": ("input_json_delta",)}
            if delta["type"] not in expected[block["type"]]:
                raise EventValidationError("Grok partial delta does not match its block")
            if field and field in delta:
                block[field] += delta[field]
                if len(block[field].encode("utf-8")) > 1024 * 1024:
                    raise EventValidationError("Grok partial text exceeds limit")
        if kind == "content_block_stop":
            del self.blocks[index]
        if not field or not block[field]:
            return None
        self.dirty.add(index)
        return self.snapshot(index, block, provider, force=kind == "content_block_stop")

    def flush(self, provider: str) -> List[str]:
        """Flush coalesced text even when a provider pauses before the next event."""
        records = [self.snapshot(index, self.blocks[index], provider) for index in list(self.dirty)]
        return [record for record in records if record is not None]

    def snapshot(self, index: int, block: Dict[str, Any], provider: str, force: bool = False) -> Optional[str]:
        field = block["type"]
        now = time.monotonic()
        # Snapshots preserve credential redaction across delta boundaries. Limit
        # repeated text/log overhead while staying below the UI's polling interval.
        if not force and now - self.updated.get(index, float("-inf")) < 0.25:
            return None
        self.updated[index] = now
        self.dirty.discard(index)
        return "ARISU_ACTIVITY " + json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": provider + ":" + self.message + ":" + str(index),
                        "kind": "analysis" if field == "thinking" else "agent",
                        "text": block[field],
                        "details": "",
                    }
                ],
            },
            ensure_ascii=False,
        )
