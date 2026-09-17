"""Fixed Docker entrypoint with fresh CLI state and stream-only generation."""

from __future__ import annotations

import importlib
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

from contract import POLICY_REVISION, context, final_response
from events import activity
from gate import AUDIT
from runtime import Runtime, stop_on_signal

BASIC = ("low", "medium", "high")
PROMPT = "Read the selected skill and all video generation context through Workbench MCP, use the attached images and their matching notes, and return the MiniMax H3 prompt."


def adapter_for(agent: str) -> Any:
    if agent not in ("codex", "grok"):
        raise ValueError("unsupported agent")
    return importlib.import_module("agents." + agent + ".adapter")


def audit() -> List[Dict[str, Any]]:
    """Read bounded hook decisions; any denial invalidates the entire generation."""
    if not AUDIT.exists():
        return []
    if AUDIT.is_symlink() or AUDIT.stat().st_size > 1024 * 1024:
        raise ValueError("invalid tool audit")
    records = [json.loads(line) for line in AUDIT.read_text().splitlines()]
    if any(record.get("allowed") is not True for record in records):
        raise ValueError(
            "agent attempted an action outside the Workbench policy: " + json.dumps([r for r in records if not r.get("allowed")])
        )
    return records


def generate(agent: str, options: Dict[str, Any]):
    """Validate tools and final output while supervising the native CLI process."""
    model, effort = options.get("model"), options.get("effort", "")
    if not isinstance(model, str) or not model or model.startswith("-") or len(model) > 160 or effort not in ("", *BASIC):
        raise ValueError("invalid model selection")
    adapter = adapter_for(agent)
    details = adapter.inspect()
    if details.get("policy_revision") != POLICY_REVISION or not details.get("policy_ready"):
        raise ValueError("agent policy is incompatible; update its image")
    manifest = context()
    prompt = PROMPT + "\nAttachment identity index (image order is one-based):\n" + json.dumps(manifest["assets"], ensure_ascii=False)
    final = ""
    completed = False
    # Codex reads text from stdin to avoid the per-argument limit on large note sets.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as prompt_input:
        prompt_input.write(prompt)
        prompt_input.seek(0)
        process = subprocess.Popen(
            adapter.command(model, effort, prompt, manifest["assets"]),
            stdin=prompt_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    total = 0
    try:
        while selector.get_map():
            for key, _mask in selector.select(timeout=0.2):
                line = key.fileobj.readline(1024 * 1024 + 1)
                if not line:
                    selector.unregister(key.fileobj)
                    continue
                total += len(line)
                if len(line) > 1024 * 1024 or total > 16 * 1024 * 1024:
                    raise ValueError("agent event exceeds limit")
                if key.data == "stderr":
                    print("[cli] " + line.rstrip(), flush=True)
                    adapter.check_stderr(line)
                    if "hook" in line.lower() and any(word in line.lower() for word in ("fail", "error", "timeout", "timed out")):
                        raise ValueError("agent policy hook failed")
                    continue
                if completed:
                    raise ValueError("agent emitted events after completion")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise TypeError("invalid agent event")
                print(activity(event), flush=True)
                value = adapter.event(event)
                completed = adapter.is_complete(event)
                if value:
                    final = value
            audit()
        if process.wait() != 0 or not completed:
            raise ValueError("agent execution failed")
        final_response(final)
        records = audit()
        if not any(r["tool"] == "get_context" for r in records) or not any(
            r["tool"] == "read_skill" and r["arguments"] == {"path": "SKILL.md"} for r in records
        ):
            raise ValueError("agent did not read the required context and skill through the managed gate")
        print("ARISU_AUDIT " + json.dumps(records), flush=True)
        print("ARISU_RESULT " + json.dumps({"final": final}), flush=True)
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        process.stdout.close()
        process.stderr.close()


def main():
    """Dispatch fixed actions; never execute a user-supplied command."""
    agent, action = sys.argv[1:3]
    adapter = adapter_for(agent)
    signal.signal(signal.SIGTERM, stop_on_signal)
    with Runtime(agent) as runtime:
        if action in ("inspect", "check"):
            print(json.dumps(adapter.inspect()))
        elif action in ("login", "logout"):
            result = subprocess.call(adapter.management(action))
            if action == "logout" and result == 0:
                runtime.stop.set()
                runtime.thread.join()
                (runtime.auth / "auth.json").unlink(missing_ok=True)
            raise SystemExit(result)
        elif action == "generate":
            generate(agent, json.loads(sys.stdin.buffer.read(65536)))
        else:
            raise ValueError("unsupported action")


if __name__ == "__main__":
    main()
