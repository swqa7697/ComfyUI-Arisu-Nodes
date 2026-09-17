"""Grok discovery, fixed invocation and event validation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List

from contract import INPUTS, POLICY_REVISION, contained_file
from gate import authorize
from process import rpc, run

from agents.grok.hook import normalize

BASIC = ("low", "medium", "high")
PROMPT_LIMIT = 384 * 1024 * 1024


def inspect() -> Dict[str, Any]:
    version = run(["grok", "--version"])
    help_text = run(["grok", "--help"])
    if version.returncode or not all(
        flag in help_text.stdout for flag in ("--tools", "--disable-web-search", "--system-prompt-override", "--prompt-file")
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
        "--permission-mode",
        "dontAsk",
        "--no-subagents",
        "--no-plan",
        "--disable-web-search",
        "--tools",
        "search_tool,use_tool",
        "--system-prompt-override",
        Path("/opt/workbench/instructions.txt").read_text(),
    ]
    if effort:
        arguments += ["--effort", effort]
    return arguments


def event(value: Dict[str, Any]) -> str:
    kind = value.get("type")
    if kind == "system" and value.get("subtype") == "init":
        permitted = {"search_tool", "use_tool", "workbench__get_context", "workbench__read_skill"}
        if set(value.get("tools", [])) - permitted:
            raise ValueError("Grok advertised prohibited tools: " + str(sorted(set(value.get("tools", [])) - permitted)))
        if value.get("permissionMode") != "dontAsk":
            raise ValueError("Grok permission mode mismatch")
        servers = value.get("mcp_servers", [])
        if any(item.get("name") != "workbench" or item.get("status") != "connected" for item in servers):
            raise ValueError("Grok MCP policy mismatch")
        return ""
    if kind == "assistant":
        content = value.get("message", {}).get("content", [])
        for block in content:
            if block.get("type") == "tool_use":
                name, arguments = normalize({"toolName": block.get("name"), "toolInput": block.get("input", {})})
                if not authorize(name, arguments):
                    raise ValueError("Grok attempted a prohibited tool: " + str(block.get("name")))
            elif block.get("type") not in ("text", "thinking"):
                raise ValueError("unsupported Grok assistant content")
        return "\n".join(block["text"] for block in content if block.get("type") == "text")
    if kind == "user":
        for block in value.get("message", {}).get("content", []):
            if block.get("type") != "tool_result" or block.get("is_error"):
                raise ValueError("Grok reader failed")
        return ""
    if kind == "result":
        if value.get("is_error") or value.get("subtype") not in (None, "success"):
            raise ValueError("Grok generation failed")
        return value.get("result", "")
    raise ValueError("unsupported Grok event: " + str(kind))


def is_complete(value: Dict[str, Any]) -> bool:
    """Identify the terminal event after event validation succeeds."""
    return value.get("type") == "result"


def management(action: str) -> List[str]:
    return ["grok", "--no-auto-update", action, *(["--device-auth"] if action == "login" else [])]


def check_stderr(line: str):
    """Tool errors are reported in the validated JSON stream."""
