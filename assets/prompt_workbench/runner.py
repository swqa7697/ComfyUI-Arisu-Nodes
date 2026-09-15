"""Fixed container entrypoint: native agents, device login and readable events."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

BASIC = ("low", "medium", "high")
MCP = '[mcp_servers.workbench]\ncommand = "python"\nargs = ["/opt/workbench/mcp_server.py"]\n'


def run(arguments: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Capture bounded-duration CLI discovery without exposing credentials."""
    return subprocess.run(arguments, text=True, capture_output=True, timeout=timeout, check=False)


def rpc(agent: str, method: str) -> Any:
    """Read a catalog RPC with a hard process deadline and no inference request."""
    arguments = ["codex", "app-server"] if agent == "codex" else ["grok", "--no-auto-update", "agent", "stdio"]
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    timer = threading.Timer(25, process.kill)
    timer.start()
    try:
        initialize = {"clientInfo": {"name": "arisu", "version": "1.0"}}
        if agent == "grok":
            initialize.update(protocolVersion=1, clientCapabilities={})
        messages = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": initialize}]
        if agent == "codex":
            messages.append({"method": "initialized", "params": {}})
        messages.append({"jsonrpc": "2.0", "id": 1, "method": method, "params": {"includeHidden": False} if agent == "codex" else {}})
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" not in message:
                continue
            while line := process.stdout.readline(1024 * 1024):
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
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def configuration(agent: str):
    """Install only the fixed MCP and Auto policy into the isolated agent home."""
    home = Path("/home/agent") / ("." + agent)
    home.mkdir(parents=True, exist_ok=True)
    if agent == "codex":
        text = 'approval_policy = "on-request"\n' + MCP
    else:
        text = '[ui]\npermission_mode = "auto"\n[cli]\nauto_update = false\n' + MCP
    (home / "config.toml").write_text(text)


def inspect(agent: str) -> Dict[str, Any]:
    """Report executable, authentication, Auto compatibility and account models."""
    version = run([agent, "--version"])
    help_text = run([agent, "exec", "--help"] if agent == "codex" else [agent, "--help"])
    if version.returncode:
        raise ValueError("agent executable is unavailable")
    models = []
    if agent == "codex":
        auto = "--approve-for-me" in help_text.stdout
        authenticated = run(["codex", "login", "status"]).returncode == 0
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
        auto = "--permission-mode" in help_text.stdout and "auto," in help_text.stdout
        listed = run(["grok", "--no-auto-update", "models"])
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
    return {"version": version.stdout.strip(), "authenticated": authenticated, "auto": auto, "models": models}


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
    if not isinstance(model, str) or not model or len(model) > 160 or effort not in ("", *BASIC):
        raise ValueError("invalid model selection")
    prompt = (
        "Use the selected skill in /skill/SKILL.md to draft the MiniMax H3 prompt. "
        "First call workbench.get_context, then read its images with workbench.read_image. "
        "Media is read-only under /inputs. Return exactly one fenced markdown block, with no text outside it."
    )
    if agent == "codex":
        arguments = [
            "codex",
            "exec",
            "--approve-for-me",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--model",
            model,
            "--output-last-message",
            "/work/final.md",
        ]
        if effort:
            arguments += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
        arguments += [prompt]
    else:
        arguments = [
            "grok",
            "--no-auto-update",
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "auto",
            "--no-subagents",
        ]
        if effort:
            arguments += ["--effort", effort]
    final = ""
    with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=None, text=True) as process:
        while line := process.stdout.readline(1024 * 1024 + 1):
            if len(line) > 1024 * 1024:
                process.terminate()
                raise ValueError("agent event exceeds limit")
            try:
                event = json.loads(line)
            except ValueError:
                print("[agent] " + line.rstrip(), flush=True)
                continue
            kind = event.get("type", "progress")
            if kind == "result":
                final = event.get("result", event.get("text", ""))
            if agent == "grok" and kind == "assistant":
                content = event.get("message", {}).get("content", [])
                final = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
            print(activity(event), flush=True)
        if process.wait() != 0:
            raise ValueError("agent execution failed")
    if agent == "codex":
        final = Path("/work/final.md").read_text()
    if not isinstance(final, str) or len(final) > 70000:
        raise ValueError("invalid final response")
    print("ARISU_RESULT " + json.dumps({"final": final}), flush=True)


def main():
    """Dispatch fixed management actions; no user command strings are executed."""
    agent, action = sys.argv[1:3]
    if agent not in ("codex", "grok"):
        raise ValueError("unsupported agent")
    configuration(agent)
    if action == "inspect":
        print(json.dumps(inspect(agent)))
    elif action == "login":
        raise SystemExit(subprocess.call([agent, *(["--no-auto-update"] if agent == "grok" else []), "login", "--device-auth"]))
    elif action == "logout":
        raise SystemExit(subprocess.call([agent, *(["--no-auto-update"] if agent == "grok" else []), "logout"]))
    elif action == "generate":
        generate(agent, json.loads(sys.stdin.buffer.read(65536)))
    elif action == "check":
        details = inspect(agent)
        if not details["auto"]:
            raise ValueError("this CLI does not expose compatible Auto mode")
        print(json.dumps(details))
    else:
        raise ValueError("unsupported action")


if __name__ == "__main__":
    main()
