"""Fixed container entrypoint: native agents, device login and readable events."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

BASIC = ("low", "medium", "high")
POLICY = Path("/opt/workbench/policy")
EXECUTABLES = {"codex": "/opt/agent/bin/codex", "grok": "/opt/agent/bin/grok"}
MAX_CAPTURE = 2 * 1024 * 1024


def stop(process: subprocess.Popen):
    """Kill and reap a container-local process group, including MCP children."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def prefix(agent: str) -> List[str]:
    """Use fixed executables and deny every Grok built-in tool."""
    executable = EXECUTABLES[agent]
    if agent == "codex":
        return [executable]
    # An empty --tools is parsed as "use defaults" by Grok. Keep this nonempty;
    # search_tool/use_tool only route to the fixed Workbench MCP catalog.
    return [
        executable,
        "--no-auto-update",
        "--tools",
        "search_tool,use_tool,workbench__get_context,workbench__read_image,workbench__read_skill",
        "--disable-web-search",
        "--no-subagents",
        "--permission-mode",
        "dontAsk",
        "--sandbox",
        "read-only",
    ]


def run(arguments: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Capture bounded-duration CLI discovery without exposing credentials."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    output = [bytearray(), bytearray()]
    overflow = threading.Event()

    def read(pipe: Any, target: bytearray):
        while chunk := pipe.read(65536):
            if len(target) + len(chunk) > MAX_CAPTURE:
                overflow.set()
                stop(process)
                break
            target.extend(chunk)

    readers = [
        threading.Thread(target=read, args=(pipe, target), daemon=True) for pipe, target in zip((process.stdout, process.stderr), output)
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    finally:
        stop(process)
        for reader in readers:
            reader.join()
        process.stdout.close()
        process.stderr.close()
    if overflow.is_set():
        raise ValueError("agent discovery output exceeds limit")
    return subprocess.CompletedProcess(arguments, process.returncode, *(bytes(part).decode("utf-8", "replace") for part in output))


def rpc(agent: str, method: str) -> Any:
    """Read a catalog RPC with a hard process deadline and no inference request."""
    arguments = prefix(agent) + (["app-server"] if agent == "codex" else ["agent", "stdio"])
    process = subprocess.Popen(
        arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True
    )
    timer = threading.Timer(25, stop, args=(process,))
    timer.start()
    try:
        initialize = {"clientInfo": {"name": "arisu", "version": "1.0"}}
        if agent == "codex":
            initialize["capabilities"] = {"experimentalApi": True}
        if agent == "grok":
            initialize.update(protocolVersion=1, clientCapabilities={})
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": initialize}]
        if agent == "codex":
            messages.append({"method": "initialized", "params": {}})
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {"includeHidden": False} if method == "model/list" else None if method == "configRequirements/read" else {},
            }
        )
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" not in message:
                continue
            while line := process.stdout.readline(1024 * 1024 + 1):
                if len(line) > 1024 * 1024:
                    raise ValueError("agent catalog event exceeds limit")
                response = json.loads(line)
                if response.get("id") == message["id"]:
                    if "error" in response:
                        raise ValueError("Agent catalog discovery failed")
                    if message["id"] == 1:
                        return response["result"]
                    break
        raise ValueError("Agent catalog discovery ended unexpectedly")
    finally:
        timer.cancel()
        stop(process)
        process.stdin.close()
        process.stdout.close()


def configuration(agent: str, home_root: Path = Path("/home/agent"), auth_root: Path = Path("/auth"), policy: Path = POLICY):
    """Start a fresh runtime home with immutable config and only saved auth JSON.

    The persistent volume is never a CLI home: old hooks, plugins, config and
    skills cannot be discovered. The caller owns the single-operation guard.
    """
    home = home_root / ("." + agent)
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").symlink_to(policy / (agent + ".toml"))
    source = auth_root / "auth.json"
    if source.exists() or source.is_symlink():
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise ValueError("invalid authentication storage")
        payload = source.read_bytes()
        if not isinstance(json.loads(payload), dict):
            raise ValueError("invalid authentication storage")
        with (home / "auth.json").open("xb") as output:
            output.write(payload)
        (home / "auth.json").chmod(0o600)


def save_auth(agent: str, home_root: Path = Path("/home/agent"), auth_root: Path = Path("/auth")):
    """Persist only provider token refresh/login state, never config or results."""
    source = home_root / ("." + agent) / "auth.json"
    target = auth_root / "auth.json"
    if source.is_symlink() or target.is_symlink():
        raise ValueError("invalid authentication storage")
    if not source.exists():
        target.unlink(missing_ok=True)
        return
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        raise ValueError("invalid authentication storage")
    payload = source.read_bytes()
    if not isinstance(json.loads(payload), dict):
        raise TypeError("invalid authentication storage")
    # Only this fixed credential file is copied back, after the CLI has exited.
    temporary = auth_root / ("auth-" + uuid.uuid4().hex + ".pending")
    with temporary.open("xb") as output:
        output.write(payload)
    temporary.chmod(0o600)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def restricted(agent: str) -> Dict[str, Any]:
    """Check required CLI controls and native sandbox startup without inference."""
    help_text = run([EXECUTABLES[agent], "exec", "--help"] if agent == "codex" else [EXECUTABLES[agent], "--help"])
    required = (
        ("--sandbox", "--json", "--ephemeral")
        if agent == "codex"
        else (
            "--tools",
            "--disable-web-search",
            "--no-subagents",
            "dontAsk",
            "--sandbox",
            "--system-prompt-override",
        )
    )
    if help_text.returncode or any(flag not in help_text.stdout for flag in required):
        return {"restricted": False, "restriction_error": "Update required: this CLI lacks Workbench's required permission controls."}
    # Exercise the sandbox itself, not just a help string or version number.
    if agent == "grok":
        result = run([*prefix(agent), "inspect", "--json"])
        if result.returncode == 0:
            discovered = json.loads(result.stdout)
            servers = discovered.get("mcpServers", [])
            if (
                discovered.get("hooks")
                or discovered.get("plugins")
                or discovered.get("skills")
                or {server.get("name") for server in servers} != {"workbench"}
            ):
                return {"restricted": False, "restriction_error": "Unexpected agent extensions are enabled."}
    else:
        config = rpc(agent, "config/read")["config"]
        requirements = rpc(agent, "configRequirements/read").get("requirements") or {}
        if (
            config.get("sandbox_mode") != "read-only"
            or config.get("approval_policy") != "never"
            or config.get("web_search") != "disabled"
            or any(
                config.get("features", {}).get(key) is not False
                for key in ("shell_tool", "multi_agent", "apps", "plugins", "browser_use", "computer_use", "view_image")
            )
            or set(config.get("mcp_servers", {})) != {"workbench"}
            or requirements.get("allowedApprovalPolicies") != ["never"]
            or requirements.get("allowedSandboxModes") != ["read-only"]
            or requirements.get("allowedWebSearchModes") != ["disabled"]
            or requirements.get("allowManagedHooksOnly") is not True
            or requirements.get("featureRequirements", {}).get("hooks") is not True
            or requirements.get("hooks", {}).get("managedDir") != "/opt/workbench"
            or not any(
                group.get("matcher") == ".*"
                and any(
                    hook.get("command") == "/usr/local/bin/python /opt/workbench/policy.py"
                    and hook.get("type") == "command"
                    and not hook.get("async")
                    for hook in group.get("hooks", [])
                )
                for group in requirements.get("hooks", {}).get("PreToolUse", [])
            )
        ):
            return {"restricted": False, "restriction_error": "Required agent policy was not applied."}
        result = run([*prefix(agent), "sandbox", "linux", "/usr/local/bin/python", "/opt/workbench/policy.py", "--sandbox-probe"])
        # A native permission refusal is required. Startup failures are not proof.
        if result.returncode == 0 and result.stdout.strip() == "ARISU_SANDBOX_DENIED":
            return {"restricted": True, "restriction_error": ""}
        return {"restricted": False, "restriction_error": "Native read-only sandbox verification failed; check host sandbox support."}
    if result.returncode:
        return {
            "restricted": False,
            "restriction_error": "Native read-only sandbox could not start; check Bubblewrap and host namespace support.",
        }
    return {"restricted": True, "restriction_error": ""}


def inspect(agent: str) -> Dict[str, Any]:
    """Report executable, authentication, restricted-mode compatibility and models."""
    version = run([EXECUTABLES[agent], "--version"])
    capability = restricted(agent)
    if version.returncode:
        raise ValueError("agent executable is unavailable")
    models = []
    if agent == "codex":
        authenticated = run([*prefix(agent), "login", "status"]).returncode == 0
        if authenticated:
            for item in rpc("codex", "model/list").get("data", []):
                efforts = [e.get("reasoningEffort") for e in item.get("supportedReasoningEfforts", [])]
                models.append(
                    {
                        "id": item["id"],
                        "name": item.get("displayName", item["id"]),
                        "efforts": [e for e in BASIC if e in efforts],
                        "default": item.get("isDefault", False),
                    }
                )
    else:
        listed = run([*prefix(agent), "models"])
        authenticated = listed.returncode == 0 and (
            "You are logged in with " in listed.stdout or "You are using XAI_API_KEY." in listed.stdout
        )
        if authenticated:
            data = rpc("grok", "_x.ai/models/list")
            data = data.get("result", data)
            for item in data.get("availableModels", []):
                model = item["modelId"]
                meta = item.get("_meta", {})
                efforts = meta.get("supportedReasoningEfforts", meta.get("reasoningEfforts", []))
                efforts = [e.get("value", e.get("id")) if isinstance(e, dict) else e for e in efforts]
                models.append(
                    {
                        "id": model,
                        "name": item.get("name", model),
                        "efforts": [e for e in BASIC if e in efforts],
                        "default": model == data.get("currentModelId"),
                    }
                )
    return {"version": version.stdout.strip(), "authenticated": authenticated, **capability, "models": models}


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


def generate(agent: str, options: Dict[str, Any]):
    """Stream readable progress and return the final assistant message separately."""
    model = options["model"]
    effort = options.get("effort", "")
    if (
        not isinstance(model, str)
        or not model
        or model.startswith("-")
        or "\x00" in model
        or len(model) > 160
        or effort not in ("", *BASIC)
    ):
        raise ValueError("invalid model selection")
    capability = restricted(agent)
    if not capability["restricted"]:
        raise ValueError(capability["restriction_error"])
    prompt = "Draft the MiniMax H3 audiovisual prompt from the Workbench context and selected skill."
    if agent == "codex":
        arguments = [
            *prefix(agent),
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--model",
            model,
        ]
        if effort:
            arguments += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
        arguments += [prompt]
    else:
        arguments = [
            *prefix(agent),
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "streaming-messages-json",
            "--system-prompt-override",
            (POLICY / "instructions.txt").read_text(),
        ]
        if effort:
            arguments += ["--effort", effort]
    final: Optional[str] = None
    completed = False
    initialized = agent == "codex"
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=None, text=True, start_new_session=True)
    try:
        total = 0
        while line := process.stdout.readline(1024 * 1024 + 1):
            total += len(line)
            if len(line) > 1024 * 1024 or total > 16 * 1024 * 1024:
                raise ValueError("agent event exceeds limit")
            event = json.loads(line)
            if not isinstance(event, dict):
                raise TypeError("invalid agent event")
            kind = event.get("type", "progress")
            if completed:
                raise ValueError("agent emitted data after its final result")
            if kind in ("error", "turn.failed") or event.get("is_error"):
                raise ValueError("agent execution failed")
            if agent == "grok" and kind == "system" and event.get("subtype") == "init":
                allowed = {"search_tool", "use_tool", "workbench__get_context", "workbench__read_image", "workbench__read_skill"}
                if (
                    initialized
                    or not isinstance(event.get("tools"), list)
                    or not set(event["tools"]).issubset(allowed)
                    or {server.get("name") for server in event.get("mcp_servers", [])} != {"workbench"}
                    or event.get("skills")
                    or event.get("plugins")
                    or event.get("permissionMode") != "dontAsk"
                ):
                    raise ValueError("agent advertised tools outside the Workbench policy")
                initialized = True
            if agent == "codex":
                if kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                    candidate = event["item"].get("text")
                    # Commentary may precede the final answer; only fenced output is a candidate.
                    if isinstance(candidate, str) and candidate.lstrip().startswith("```markdown"):
                        if final is not None:
                            raise ValueError("agent returned multiple final responses")
                        final = candidate
                if kind == "turn.completed":
                    completed = True
            elif kind == "assistant":
                message = event.get("message", {})
                content = message.get("content", [])
                candidate = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
                if candidate.lstrip().startswith("```markdown") and not any(block.get("type") == "tool_use" for block in content):
                    if final is not None:
                        raise ValueError("agent returned multiple final responses")
                    final = candidate
            elif kind == "result":
                if event.get("subtype") != "success" or event.get("stop_reason") != "end_turn" or event.get("is_error") is not False:
                    raise ValueError("agent execution did not complete successfully")
                candidate = event.get("result")
                if candidate is not None:
                    if final is not None and final != candidate:
                        raise ValueError("conflicting final agent responses")
                    final = candidate
                completed = True
            print(activity(event), flush=True)
        if process.wait() != 0 or not completed or not initialized:
            raise ValueError("agent execution did not complete")
    finally:
        stop(process)
        process.stdout.close()
    if not isinstance(final, str) or not final.strip() or len(final) > 70000:
        raise ValueError("invalid final response")
    print("ARISU_RESULT " + json.dumps({"final": final}), flush=True)


def main():
    """Dispatch fixed management actions; no user command strings are executed."""
    agent, action = sys.argv[1:3]
    if agent not in ("codex", "grok"):
        raise ValueError("unsupported agent")
    configuration(agent)
    try:
        if action == "inspect":
            print(json.dumps(inspect(agent)))
        elif action in ("login", "logout"):
            arguments = [*prefix(agent), action, *(["--device-auth"] if action == "login" else [])]
            raise SystemExit(subprocess.call(arguments))
        elif action == "generate":
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError("agent request exceeds limit")
            generate(agent, json.loads(raw))
        elif action == "check":
            details = inspect(agent)
            if not details["restricted"]:
                raise ValueError(details["restriction_error"])
            print(json.dumps(details))
        else:
            raise ValueError("unsupported action")
    finally:
        save_auth(agent)


if __name__ == "__main__":
    main()
