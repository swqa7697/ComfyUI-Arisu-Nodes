"""Grok discovery, fixed invocation and event validation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List

from contract import INPUTS, POLICY_REVISION, contained_file, read_text
from events import EventValidationError
from gate import authorize
from process import rpc, run

from agents.grok.hook import normalize

BASIC = ("low", "medium", "high")
PROMPT_LIMIT = 384 * 1024 * 1024


def inspect() -> Dict[str, Any]:
    version = run(["grok", "--version"])
    help_text = run(["grok", "--help"])
    if version.returncode or not all(
        flag in help_text.stdout
        for flag in ("--tools", "--disable-web-search", "--system-prompt-override", "--prompt-file", "--include-partial-messages")
    ):
        raise ValueError("Grok policy controls are unavailable")
    result = run(["grok", "--no-auto-update", "inspect", "--json"])
    if result.returncode:
        raise ValueError("Grok policy discovery failed")
    configured = json.loads(result.stdout)
    # Inspect is also checked in the actual generation init event, after CLI flags.
    if not isinstance(configured, dict):
        raise TypeError("invalid Grok policy discovery")
    for key in ("skills", "plugins", "marketplaces", "lspServers", "projectInstructions"):
        if configured.get(key):
            raise ValueError("Grok discovered unauthorized " + key)
    servers = configured.get("mcpServers", [])
    if len(servers) != 1 or servers[0].get("name") != "workbench" or servers[0].get("target") != "/usr/local/bin/python":
        raise ValueError("Grok MCP configuration mismatch")
    hooks = configured.get("hooks", [])
    if len(hooks) != 1 or hooks[0].get("target") != "/usr/local/bin/python /opt/workbench/agents/grok/hook.py":
        raise ValueError("Grok managed hook mismatch")
    if hooks[0].get("event") != "pre_tool_use" or hooks[0].get("matcher") != ".*":
        raise ValueError("Grok managed hook coverage mismatch")
    listed = run(["grok", "--no-auto-update", "models"])
    authenticated = listed.returncode == 0 and ("You are logged in with " in listed.stdout or "You are using XAI_API_KEY." in listed.stdout)
    models = []
    if authenticated:
        data = rpc(
            ["grok", "--no-auto-update", "agent", "stdio"],
            "_x.ai/models/list",
            {"clientInfo": {"name": "arisu", "version": "1.0"}, "protocolVersion": 1, "clientCapabilities": {}},
            {},
        )
        data = data.get("result", data)
        for item in data.get("availableModels", []):
            meta = item.get("_meta", {})
            efforts = meta.get("supportedReasoningEfforts", meta.get("reasoningEfforts", []))
            efforts = [e.get("value", e.get("id")) if isinstance(e, dict) else e for e in efforts]
            models.append(
                {
                    "id": item["modelId"],
                    "name": item.get("name", item["modelId"]),
                    "efforts": [e for e in BASIC if e in efforts],
                    "default": item["modelId"] == data.get("currentModelId"),
                }
            )
    return {
        "version": version.stdout.strip(),
        "authenticated": authenticated,
        "policy_ready": True,
        "policy_revision": POLICY_REVISION,
        "models": models,
    }


def write_prompt(path: Path, prompt: str, assets: List[Dict[str, Any]]):
    """Stream the complete UTF-8 JSON payload within the temporary-file budget."""
    output = path.open("xb")
    try:
        with output:

            def write(text: str):
                data = text.encode("utf-8")
                if output.tell() + len(data) > PROMPT_LIMIT:
                    raise ValueError("Grok attachments exceed the bounded prompt budget")
                output.write(data)

            write("[" + json.dumps({"type": "text", "text": prompt}, ensure_ascii=False))
            for asset in assets:
                identity = {key: value for key, value in asset.items() if key != "file"}
                write("," + json.dumps({"type": "text", "text": json.dumps(identity, ensure_ascii=False)}, ensure_ascii=False))
                write(',{"type": "image", "mimeType": "image/webp", "data": "')
                with contained_file(INPUTS, asset["file"]).open("rb") as source:
                    # Multiples of three keep padding confined to the final Base64 chunk.
                    while chunk := source.read(3 * 65536):
                        write(base64.b64encode(chunk).decode("ascii"))
                write('"}')
            write("]")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def command(model: str, effort: str, prompt: str, assets: List[Dict[str, Any]]) -> List[str]:
    prompt_file = Path("/tmp/workbench-prompt.json")
    # File input avoids ARG_MAX; reserve 128 MiB of /tmp for other CLI files.
    write_prompt(prompt_file, prompt, assets)
    arguments = [
        "grok",
        "--no-auto-update",
        "--prompt-file",
        str(prompt_file),
        "--model",
        model,
        "--output-format",
        "streaming-messages-json",
        "--include-partial-messages",
        "--permission-mode",
        "dontAsk",
        "--no-subagents",
        "--no-plan",
        "--disable-web-search",
        "--tools",
        "search_tool,use_tool",
        "--system-prompt-override",
        read_text(Path("/opt/workbench/instructions.txt")),
    ]
    if effort:
        arguments += ["--effort", effort]
    return arguments


def _startup(value: Dict[str, Any]):
    """Validate authorization separately from the MCP startup snapshot."""
    tools = value.get("tools")
    if not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools):
        raise EventValidationError("Grok malformed tool list")
    permitted = {"search_tool", "use_tool", "workbench__get_context", "workbench__read_skill"}
    if set(tools) - permitted:
        raise EventValidationError("Grok advertised prohibited tools")
    if value.get("permissionMode") != "dontAsk":
        raise EventValidationError("Grok permission mode mismatch")
    servers = value.get("mcp_servers")
    if not isinstance(servers, list):
        raise EventValidationError("Grok malformed MCP server list")
    if len(servers) != 1:
        raise EventValidationError("Grok expected exactly one MCP server")
    server = servers[0]
    if not isinstance(server, dict) or any(not isinstance(server.get(key), str) for key in ("name", "status")):
        raise EventValidationError("Grok malformed MCP server entry")
    if server["name"] != "workbench":
        raise EventValidationError("Grok unauthorized MCP server")
    status = server["status"]
    # Grok snapshots MCP before its prompt-time startup wait. Pending is valid;
    # the runner still requires both managed MCP reads before accepting output.
    if status in ("pending", "connected"):
        return
    failures = {
        "failed": "Grok MCP connection failed",
        "disabled": "Grok MCP server disabled",
        "needs-auth": "Grok MCP authentication required",
    }
    raise EventValidationError(failures.get(status, "Grok unsupported MCP status"))


def _content(value: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check the message envelope before interpreting individual blocks."""
    message = value.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        raise EventValidationError("Grok malformed message content")
    content = message["content"]
    if any(not isinstance(block, dict) or not isinstance(block.get("type"), str) for block in content):
        raise EventValidationError("Grok malformed content block")
    return content


def _assistant(content: List[Dict[str, Any]]) -> str:
    for block in content:
        kind = block["type"]
        if kind == "tool_use":
            if not isinstance(block.get("name"), str) or not isinstance(block.get("input"), dict):
                raise EventValidationError("Grok malformed tool call")
            name, arguments = normalize({"toolName": block["name"], "toolInput": block["input"]})
            if not authorize(name, arguments):
                raise EventValidationError("Grok attempted a prohibited tool")
        elif kind in ("text", "thinking"):
            field = "text" if kind == "text" else "thinking"
            if not isinstance(block.get(field), str):
                raise EventValidationError("Grok malformed assistant text")
        else:
            raise EventValidationError("Grok unsupported assistant content")
    return "\n".join(block["text"] for block in content if block["type"] == "text")


def _tool_results(content: List[Dict[str, Any]]):
    for block in content:
        if block["type"] != "tool_result":
            raise EventValidationError("Grok unsupported user content")
        if not isinstance(block.get("is_error", False), bool):
            raise EventValidationError("Grok malformed tool result")
        if block.get("is_error"):
            raise EventValidationError("Grok reader failed")
        result = block.get("content", [])
        if isinstance(result, str):
            continue
        if not isinstance(result, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("type"), str)
            or (item["type"] == "text" and not isinstance(item.get("text"), str))
            for item in result
        ):
            raise EventValidationError("Grok malformed tool result content")


def _partial(value: Dict[str, Any]):
    """Validate display deltas; completed messages still authorize every tool call."""
    partial = value.get("event")
    if not isinstance(partial, dict):
        raise EventValidationError("Grok malformed partial event")
    kind = partial.get("type")
    if kind == "message_start":
        message = partial.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not message["id"] or message.get("content") != []:
            raise EventValidationError("Grok malformed partial message")
    elif kind in ("content_block_start", "content_block_delta", "content_block_stop"):
        if type(partial.get("index")) is not int or partial["index"] < 0:
            raise EventValidationError("Grok malformed partial index")
        if kind == "content_block_start":
            block = partial.get("content_block")
            if not isinstance(block, dict):
                raise EventValidationError("Grok malformed partial block")
            if block.get("type") == "tool_use":
                if block.get("name") not in ("search_tool", "use_tool", "workbench__get_context", "workbench__read_skill"):
                    raise EventValidationError("Grok attempted a prohibited tool")
                if not isinstance(block.get("id"), str) or block.get("input") != {}:
                    raise EventValidationError("Grok malformed partial tool")
            else:
                _assistant([block])
        elif kind == "content_block_delta":
            delta = partial.get("delta")
            if not isinstance(delta, dict):
                raise EventValidationError("Grok malformed partial delta")
            field = {
                "text_delta": "text",
                "thinking_delta": "thinking",
                "signature_delta": "signature",
                "input_json_delta": "partial_json",
            }.get(delta.get("type"))
            if field is None or not isinstance(delta.get(field), str):
                raise EventValidationError("Grok unsupported partial delta")
    elif kind == "message_delta":
        if not isinstance(partial.get("delta"), dict):
            raise EventValidationError("Grok malformed partial message delta")
    elif kind != "message_stop":
        raise EventValidationError("Grok unsupported partial event")


def event(value: Dict[str, Any]) -> str:
    """Validate recognized events without treating extra metadata as actions."""
    kind = value.get("type")
    if not isinstance(kind, str):
        raise EventValidationError("Grok malformed event type")
    if kind == "system" and value.get("subtype") == "init":
        _startup(value)
        return ""
    if kind == "stream_event":
        _partial(value)
        return ""
    if kind == "assistant":
        return _assistant(_content(value))
    if kind == "user":
        _tool_results(_content(value))
        return ""
    if kind == "result":
        if not isinstance(value.get("is_error", False), bool) or not isinstance(value.get("result", ""), str):
            raise EventValidationError("Grok malformed generation result")
        if value.get("is_error") or value.get("subtype") not in (None, "success"):
            raise EventValidationError("Grok generation failed")
        return value.get("result", "")
    raise EventValidationError("Grok unsupported event")


def is_complete(value: Dict[str, Any]) -> bool:
    """Identify the terminal event after event validation succeeds."""
    return value.get("type") == "result"


def management(action: str) -> List[str]:
    return ["grok", "--no-auto-update", action, *(["--device-auth"] if action == "login" else [])]


def check_stderr(line: str):
    """Tool errors are reported in the validated JSON stream."""
