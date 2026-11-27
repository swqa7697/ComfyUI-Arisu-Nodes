"""Codex discovery, fixed invocation and event validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from contract import POLICY_REVISION, read_text
from events import EventValidationError, ProviderNotice, ProviderResultError, check_policy_hook, failure_reason
from gate import authorize
from process import rpc, run

BASIC = ("low", "medium", "high")
RECONNECT = re.compile(r"Reconnecting\.\.\. (?:([1-9][0-9]{0,19})/([1-9][0-9]{0,19})|waiting for network)(?: \(.*\))?", re.DOTALL)


def catalog(method: str, params: Dict[str, Any]) -> Any:
    return rpc(["codex", "app-server"], method, {"clientInfo": {"name": "arisu", "version": "1.0"}}, params, True)


def inspect() -> Dict[str, Any]:
    """Check effective policy before reporting a provider as compatible."""
    version = run(["codex", "--version"])
    if version.returncode:
        raise ValueError("Codex executable is unavailable")
    configured = catalog("config/read", {"includeLayers": False})["config"]
    if configured.get("approval_policy") != "never" or configured.get("sandbox_mode") != "danger-full-access":
        raise ValueError("Codex permission policy mismatch")
    if configured.get("web_search") != "disabled":
        raise ValueError("Codex web search is not disabled")
    features = configured.get("features", {})
    for name in (
        "shell_tool",
        "multi_agent",
        "apps",
        "plugins",
        "memories",
        "browser_use",
        "computer_use",
        "code_mode",
        "image_generation",
    ):
        if features.get(name) is not False:
            raise ValueError("Codex feature policy mismatch: " + name)
    if features.get("hooks") is not True or features.get("view_image") is not False:
        raise ValueError("Codex read gate is unavailable")
    if set(configured.get("mcp_servers", {})) != {"workbench"}:
        raise ValueError("Codex MCP policy mismatch")
    authenticated = run(["codex", "login", "status"]).returncode == 0
    models = []
    if authenticated:
        for item in catalog("model/list", {"includeHidden": False}).get("data", []):
            efforts = [entry.get("reasoningEffort") for entry in item.get("supportedReasoningEfforts", [])]
            models.append(
                {
                    "id": item["id"],
                    "name": item.get("displayName", item["id"]),
                    "efforts": [e for e in BASIC if e in efforts],
                    "default": item.get("isDefault", False),
                }
            )
    return {
        "version": version.stdout.strip(),
        "authenticated": authenticated,
        "policy_ready": True,
        "policy_revision": POLICY_REVISION,
        "models": models,
    }


def command(model: str, effort: str, prompt: str, assets: List[Dict[str, Any]]) -> List[str]:
    cache = Path("/home/agent/.codex/models_cache.json")
    data = json.loads(read_text(cache, 16 * 1024 * 1024))
    models = data.get("models", [])
    if not any(item.get("slug") == model for item in models):
        raise ValueError("selected Codex model is absent from its authenticated catalog")
    for item in models:
        # Provider model metadata can force Code Mode even when its feature is off.
        # Explicit direct mode also lets us remove patching from the tool registry.
        item["tool_mode"] = "direct"
        item["apply_patch_tool_type"] = None
        item["experimental_supported_tools"] = []
        item["supports_search_tool"] = False
    catalog_path = Path("/home/agent/workbench-models.json")
    catalog_path.write_text(json.dumps({"models": models}))
    arguments = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--json", "--ignore-rules", "--model", model]
    arguments += ["-c", "model_catalog_json=" + json.dumps(str(catalog_path))]
    if effort:
        arguments += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
    for asset in assets:
        arguments += ["--image", asset["path"]]
    return [*arguments, "--", "-"]


def _message(envelope: Any) -> str:
    """Read a native notification without exposing its potentially private details."""
    message = envelope.get("message") if isinstance(envelope, dict) else None
    if not isinstance(message, str) or not message.strip():
        raise EventValidationError("Codex malformed error notification")
    return message


def event(value: Dict[str, Any]) -> Optional[Union[str, ProviderNotice]]:
    """Validate the event and return completed assistant text or a safe progress notice."""
    kind = value.get("type")
    if kind in ("error", "turn.failed"):
        message = _message(value if kind == "error" else value.get("error"))
        # exec --json drops the native will_retry flag. A reconnect is a progress
        # notification even if its parenthesized detail mentions a 401 or a timeout.
        if kind == "error" and (retry := RECONNECT.fullmatch(message)):
            attempt, limit = retry.groups()
            if attempt is None:
                return ProviderNotice("Codex is waiting for the network to reconnect.")
            if int(attempt) <= int(limit):
                return ProviderNotice(f"Codex is reconnecting (attempt {attempt} of {limit}).")
        raise ProviderResultError(failure_reason(value, message[:4096]))
    if kind in ("thread.started", "turn.started", "turn.completed"):
        return None
    if kind not in ("item.started", "item.updated", "item.completed"):
        raise ValueError("unsupported Codex event: " + str(kind))
    item = value.get("item", {})
    item_type = item.get("type")
    if kind == "item.completed" and item_type == "error":
        # The CLI uses this passive item for config warnings and transport changes.
        message = _message(item)
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise EventValidationError("Codex malformed warning item")
        check_policy_hook(message)
        check_stderr(message)
        if message.startswith("Falling back from WebSockets to HTTPS transport."):
            return ProviderNotice("Codex is switching from WebSockets to HTTPS.")
        return ProviderNotice("Codex CLI reported a warning.")
    if item_type == "agent_message":
        if kind != "item.completed":
            return ""
        text = item.get("text")
        if not isinstance(text, str):
            raise EventValidationError("Codex malformed assistant text")
        return text
    if item_type == "reasoning":
        return None
    if item_type == "mcp_tool_call":
        if item.get("server") != "workbench" or not authorize(item.get("tool", ""), item.get("arguments", {})):
            raise ValueError("Codex attempted a prohibited MCP call")
        if item.get("status") == "failed" or item.get("error") or (item.get("result") or {}).get("isError"):
            raise ValueError("Workbench reader failed")
        # A tool call continues the turn. Any earlier assistant text preceded its result.
        return ""
    raise ValueError("Codex attempted a prohibited tool: " + str(item_type))


def is_complete(value: Dict[str, Any]) -> bool:
    """Identify the terminal event after event validation succeeds."""
    return value.get("type") == "turn.completed"


def management(action: str) -> List[str]:
    return ["codex", action, *(["--device-auth"] if action == "login" else [])]


def check_stderr(line: str):
    """Native image errors must invalidate the result even without a JSON event."""
    if "ERROR codex_core::tools::router" in line:
        raise EventValidationError("Codex native tool failed")
