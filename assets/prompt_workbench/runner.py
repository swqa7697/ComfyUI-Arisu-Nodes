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
from typing import Any, Dict, Iterator, List, Tuple

from contract import POLICY_REVISION, DirectorBudgetError, DirectorResponseError, context, final_response, read_text
from events import (
    ActivityStream,
    EventValidationError,
    ProviderNotice,
    ProviderResultError,
    activity_entry,
    check_policy_hook,
    diagnostic,
    reports_token_limit,
)
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
    try:
        text = read_text(AUDIT)
    except FileNotFoundError:
        return []
    records = [json.loads(line) for line in text.splitlines()]
    if any(record.get("allowed") is not True for record in records):
        raise ValueError(
            "agent attempted an action outside the Workbench policy: " + json.dumps([r for r in records if not r.get("allowed")])
        )
    return records


def pipe_lines(process: subprocess.Popen) -> Iterator[Tuple[str, str]]:
    """Drain ready pipe bytes without TextIO read-ahead or blocking on partial lines."""
    selector = selectors.DefaultSelector()
    buffers: Dict[str, bytes] = {"stdout": b"", "stderr": b""}
    total = 0
    try:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            for key, _mask in selector.select(timeout=0.2):
                chunk = os.read(key.fd, 65536)
                total += len(chunk)
                if total > 16 * 1024 * 1024:
                    raise ValueError("agent event exceeds limit")
                data = buffers[key.data] + chunk
                lines = data.split(b"\n")
                buffers[key.data] = lines.pop()
                if not chunk:
                    selector.unregister(key.fileobj)
                    if buffers[key.data]:
                        lines.append(buffers[key.data])
                    buffers[key.data] = b""
                for line in lines:
                    if len(line) > 1024 * 1024:
                        raise ValueError("agent event exceeds limit")
                    yield key.data, line.decode("utf-8")
                if len(buffers[key.data]) > 1024 * 1024:
                    raise ValueError("agent event exceeds limit")
            # Keep policy audits running even when both pipes are idle.
            yield "", ""
    finally:
        selector.close()


def generate(agent: str, options: Dict[str, Any]):
    """Validate tools and final output while supervising the native CLI process."""
    model, effort = options.get("model"), options.get("effort", "")
    if not isinstance(model, str) or not model or model.startswith("-") or len(model) > 160 or effort not in ("", *BASIC):
        raise ValueError("invalid model selection")
    adapter = adapter_for(agent)
    details = adapter.inspect()
    if details.get("policy_revision") != POLICY_REVISION or not details.get("policy_ready"):
        raise ValueError("agent policy is incompatible; update its image")
    command_options = {}
    window = options.get("context_window")
    if window is not None:
        selected = next((item for item in details.get("models", []) if item["id"] == model), {}) if agent == "grok" else {}
        if type(window) is not int or window <= 0 or window not in selected.get("context_windows", []):
            raise ValueError("context window is unavailable for the selected model")
        command_options["context_window"] = window
    manifest = context()
    director = manifest.get("director")
    instruction = (
        "Read the complete Director task and skills via Workbench MCP. Return the structured film or segment draft in one json fence."
        " Use director.library[].id for bindings and stable prompt tags. Match each non-motion attachment by resource_id."
        " Use motion stills only to inspect the predecessor."
        if director
        else PROMPT
    )
    prompt = instruction + "\nAttachment identity index (image order is one-based):\n" + json.dumps(manifest["assets"], ensure_ascii=False)
    final = ""
    completed = False
    # Codex reads text from stdin to avoid the per-argument limit on large note sets.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as prompt_input:
        prompt_input.write(prompt)
        prompt_input.seek(0)
        process = subprocess.Popen(
            adapter.command(model, effort, prompt, manifest["assets"], **command_options),
            stdin=prompt_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    display = ActivityStream()
    lines = pipe_lines(process)
    pending_failure = ""
    event = None
    try:
        for source, line in lines:
            if not source:
                audit()
                for rendered in display.flush(agent):
                    print(rendered, flush=True)
                continue
            if source == "stderr":
                # A carriage return from the CLI must stay inside its prefixed line.
                print("[cli] " + line.rstrip().replace("\r", " "), flush=True)
                adapter.check_stderr(line)
                check_policy_hook(line)
                continue
            event = None
            try:
                event = json.loads(line)
                if completed:
                    raise EventValidationError("Agent emitted events after completion")
                if not isinstance(event, dict):
                    raise EventValidationError("Malformed agent event envelope")
                if director and agent == "grok" and event.get("type") in ("error", "turn.failed") and reports_token_limit(event):
                    raise DirectorBudgetError("Director task exceeded the provider context or output budget")
                value = adapter.event(event)
                if isinstance(value, ProviderNotice):
                    print(activity_entry("progress", value.text), flush=True)
                    continue
                rendered = display.render(event, agent)
            except ProviderResultError as error:
                # Codex may supply a more specific cause in turn.failed. Retain
                # a standalone error if the stream ends without that final frame.
                if agent == "codex" and event["type"] == "error":
                    if not pending_failure or str(error) != "execution":
                        pending_failure = str(error)
                    continue
                if pending_failure and str(error) == "execution":
                    raise ProviderResultError(pending_failure) from None
                raise
            except DirectorBudgetError:
                raise
            except (ValueError, TypeError, AttributeError, KeyError) as error:
                reason = str(error) if isinstance(error, EventValidationError) else "Provider event rejected or malformed"
                print(diagnostic(event, agent, details.get("version"), reason), flush=True)
                raise ValueError(reason) from None
            if rendered is not None:
                print(rendered, flush=True)
            completed = adapter.is_complete(event)
            if value:
                final = value
        status = process.wait()
        if pending_failure:
            event = {"type": "error"}
            raise ProviderResultError(pending_failure)
        if status or not completed:
            if agent == "codex":
                event = {"exit_code": status}
                raise ProviderResultError("execution" if completed else "incomplete")
            raise ValueError("agent execution failed")
        content = final_response(final, director=bool(director))
        records = audit()
        if not any(r["tool"] == "get_context" for r in records) or not any(
            r["tool"] == "read_skill" and r["arguments"] == {"path": "SKILL.md"} for r in records
        ):
            raise ValueError("agent did not read the required context and skill through the managed gate")
        if director:
            # A writing skill may serve many segments. Audit each distinct selection once.
            try:
                payload = json.loads(content)
            except (ValueError, RecursionError):
                raise DirectorResponseError("json") from None
            if not isinstance(payload, dict):
                raise ValueError("Director response must be a structured plan or replacement.")
            segments = payload.get("segments") if director["task"] == "plan" else [payload.get("segment")]
            if not isinstance(segments, list) or not segments or not all(isinstance(s, dict) for s in segments):
                raise ValueError("Director response is incomplete.")
            paths = {row["id"]: row["path"] for row in director["writing_skills"]}
            read = {r["arguments"].get("path") for r in records if r["tool"] == "read_skill"}
            if any(paths.get(s.get("skill")) not in read for s in segments):
                raise ValueError("Director did not read each selected writing skill.")
            # Keep surrounding commentary out of the host's draft validator.
            final = "```json\n" + content + "\n```"
        print("ARISU_AUDIT " + json.dumps(records), flush=True)
        print("ARISU_RESULT " + json.dumps({"final": final}, ensure_ascii=False), flush=True)
    except ProviderResultError:
        print(diagnostic(event, agent, details.get("version"), agent.capitalize() + " result details", kind="details"), flush=True)
        raise
    finally:
        lines.close()
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
            try:
                generate(agent, json.loads(sys.stdin.buffer.read(65536)))
            except ProviderResultError as error:
                print("ARISU_" + agent.upper() + "_ERROR " + str(error), flush=True)
                raise SystemExit(1) from None
            except DirectorBudgetError:
                print('ARISU_DIRECTOR_ERROR {"reason": "budget"}', flush=True)
                raise
            except DirectorResponseError as error:
                print("ARISU_DIRECTOR_ERROR " + json.dumps({"reason": error.reason}), flush=True)
                raise
        else:
            raise ValueError("unsupported action")


if __name__ == "__main__":
    main()
