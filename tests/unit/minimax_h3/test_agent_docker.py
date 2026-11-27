"""Management regressions without Docker, accounts, ComfyUI, or torch."""

from __future__ import annotations

import base64
import builtins
import importlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest
from PIL import Image

from src.arisu_nodes.common.paths import CONFIG_TEMPLATE, parse_configuration
from src.arisu_nodes.minimax_h3 import agent_docker
from src.arisu_nodes.minimax_h3.agent_docker import POLICY_REVISION, AgentExitError, DockerAgents
from src.arisu_nodes.minimax_h3.core import (
    finalized_markdown,
    motion_samples,
    motion_tail,
    preparation_graph,
    workbench_options,
)


def test_generation_contract_prunes_side_effects_and_parses_only_final_markdown():
    prompt = {
        "w": {
            "class_type": "ArisuMiniMaxH3PromptWorkbench",
            "inputs": {"finalized_prompt": "keep", "context_latent": ["l", 0], "vae": ["v", 0]},
        },
        "l": {"class_type": "MiniMaxH3MotionContextLoadLatent", "inputs": {"clip_index": 0, "latent_path": "context"}},
        "v": {"class_type": "VAELoader", "inputs": {"vae_name": "video.safetensors"}},
        "s": {"class_type": "KSampler", "inputs": {"prompt": ["w", 0]}},
    }
    prompt["w"]["inputs"].update(motion_notes="camera turns", motion_audio_notes=["s", 0])
    disabled_graph = preparation_graph(prompt, "w", False)
    assert set(disabled_graph) == {"w"} and disabled_graph["w"]["inputs"] == {"finalized_prompt": "keep"}
    prompt["w"]["inputs"]["motion_audio_notes"] = "distant piano"
    assert workbench_options({})["motion_enabled"] is True
    disabled = workbench_options({"motion_enabled": False, "motion_notes": 123, "motion_audio_notes": 123})
    assert disabled["motion_notes"] == disabled["motion_audio_notes"] == ""
    for invalid in ("false", 0, None):
        with pytest.raises(ValueError, match="motion_enabled"):
            workbench_options({"motion_enabled": invalid})
    selected = preparation_graph(prompt, "w")
    assert set(selected) == {"w", "l", "v"}
    selected["w"]["inputs"]["prepare_job"] = "not persisted"
    assert "prepare_job" not in prompt["w"]["inputs"]
    for forbidden in ("KSampler", "SaveImage", "ArisuMiniMaxH3PromptWorkbench"):
        prompt["l"]["class_type"] = forbidden
        with pytest.raises(ValueError, match="source"):
            preparation_graph(prompt, "w")
    # Get/Set wires resolve to their producers in the API prompt. The bundled
    # workflow builds the loader path with text nodes even at clip zero.
    prompt["l"]["class_type"] = "MiniMaxH3MotionContextLoadLatent"
    prompt["l"]["inputs"]["latent_path"] = ["path", 0]
    prompt["path"] = {"class_type": "StringConcatenate", "inputs": {"string_a": ["prefix", 0], "string_b": "latents", "delimiter": "/"}}
    prompt["prefix"] = {"class_type": "ArisuPathBuilder", "inputs": {"segment_1": ["text", 0], "segment_2": "scene"}}
    prompt["text"] = {"class_type": "PrimitiveString", "inputs": {"value": "h3"}}
    for clip_index in (0, 1):
        prompt["l"]["inputs"]["clip_index"] = clip_index
        selected = preparation_graph(prompt, "w")
        assert set(selected) == {"w", "l", "v", "path", "prefix", "text"}
        assert selected["l"]["inputs"]["clip_index"] == clip_index
        assert selected["path"]["inputs"]["string_a"] == ["prefix", 0]
    # Safe text builders must not admit arbitrary upstream execution.
    for forbidden in ("KSampler", "SaveImage", "ArisuMiniMaxH3PromptWorkbench"):
        prompt["text"]["class_type"] = forbidden
        with pytest.raises(ValueError, match="dependency"):
            preparation_graph(prompt, "w")
    # One motion wire stays inert and cannot execute its producer.
    del prompt["w"]["inputs"]["vae"]
    assert set(preparation_graph(prompt, "w")) == {"w"}
    for steps in (0, 1, 23):
        with pytest.raises(ValueError, match="temporal phase"):
            motion_tail(steps)
    assert motion_tail(37) == (0, 124)
    assert motion_samples(124) == list(range(15, 124, 12))
    for label in ("markdown", "text", ""):
        assert finalized_markdown("```" + label + "\nA quiet dolly shot.\n```") == "A quiet dolly shot."
    for text in (
        "thinking\n```markdown\nprompt\n```",
        "```markdown\n\n```",
        "```python\nprint(1)\n```",
        "ARISU_POLICY_REFUSAL",
        "```markdown\nx\n```\n```markdown\ny\n```",
        "```text\n~~~markdown\nOther draft.\n~~~\n```",
        "~~~text\nRaw provider fence.\n~~~",
    ):
        with pytest.raises(ValueError):
            finalized_markdown(text)
    assert workbench_options({"audio_context_length": 0})["audio_context_length"] == 0
    for invalid in (
        {"agent": "shell"},
        {"audio_context_length": True},
        {"reference_notes": {"x": 2}},
        {"requirements": "\x00"},
        {"motion_audio_notes": 123},
    ):
        with pytest.raises(ValueError):
            workbench_options(invalid)


def test_agent_update_preserves_working_image_and_settings_reject_unavailable_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "config.arisu.jsonc"
    config.write_text(CONFIG_TEMPLATE)
    agents = DockerAgents(tmp_path)
    # Startup leaves the shared configuration unchanged until preferences are saved.
    assert agents.preferences == {}
    assert config.read_text() == CONFIG_TEMPLATE
    tagged: List[str] = []
    # Docker is usable before either image exists; inspect represents absence with [].
    monkeypatch.setattr(shutil, "which", lambda value: "/test/docker")
    monkeypatch.setattr(agents, "command", lambda args, **kwargs: "linux" if args[0] == "info" else "[]")
    status = agents.status(refresh=True)
    assert status["docker"] and all(not provider["installed"] and not provider["ready"] for provider in status["agents"].values())

    # Even a matching source fingerprint cannot authorize a retired policy.
    with monkeypatch.context() as stale:
        stale.setattr(agents, "owned", lambda *args: True)
        stale_labels = {
            agents.image(provider): {
                "org.arisu.workbench.policy": "5",
                agent_docker.IMAGE_SOURCE_LABEL: agent_docker.image_source_digest(provider),
            }
            for provider in ("codex", "grok")
        }
        stale.setattr(
            agents,
            "command",
            lambda args, **kwargs: "linux" if args[0] == "info" else json.dumps([{"Config": {"Labels": stale_labels[args[-1]]}}]),
        )
        stale.setattr(agents, "invoke", lambda *args, **kwargs: pytest.fail("obsolete image executed"))
        old = agents.status(refresh=True)
        assert old["agents"]["codex"]["update_required"] and not old["agents"]["codex"]["ready"]
        with pytest.raises(ValueError, match="Update CLI"):
            agents.generate("codex", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1)

    # Format failures must reach the host as format failures, not budget advice.
    with monkeypatch.context() as generation:
        generation.setattr(agents, "require_current_image", lambda agent: None)
        for agent, marker, expected in (
            ("codex", "ARISU_WORKBENCH_ERROR format", "nonempty fenced prompt"),
            ("grok", "ARISU_WORKBENCH_ERROR length", "65,536-character limit"),
            ("grok", "ARISU_WORKBENCH_ERROR refused", "request refused by the prompt-only policy"),
            ("codex", "ARISU_WORKBENCH_ERROR private-unknown", "Workbench response failed validation"),
            ("codex", 'ARISU_DIRECTOR_ERROR {"reason":"format"}', "invalid format"),
            ("codex", 'ARISU_DIRECTOR_ERROR {"reason":"json"}', "malformed JSON"),
            ("codex", 'ARISU_DIRECTOR_ERROR {"reason":"structure"}', "segment object"),
            ("grok", 'ARISU_DIRECTOR_ERROR {"reason":"skill"}', "skill from the catalog"),
            ("grok", 'ARISU_DIRECTOR_ERROR {"reason":"skill_unread"}', "did not read"),
            ("grok", 'ARISU_DIRECTOR_ERROR {"reason":"budget"}', "exceeded"),
            ("codex", "ARISU_DIRECTOR_INCOMPLETE", "incomplete or exceeds"),
            ("codex", "ARISU_CODEX_ERROR auth", "(?i)authenticat|sign in|log in"),
            ("codex", "ARISU_CODEX_ERROR connection", "(?i)connect"),
            ("codex", "ARISU_CODEX_ERROR private-unknown", "(?i)execution fail"),
            ("grok", "ARISU_GROK_ERROR rate_limit", "rate-limited"),
            ("grok", "ARISU_GROK_ERROR private-unknown", "execution failure"),
        ):

            def failed_stream(*args: Any, marker: str = marker):
                args[-1](marker)
                raise AgentExitError("agent operation failed")

            generation.setattr(agents, "stream", failed_stream)
            with pytest.raises(ValueError, match=expected) as failure:
                agents.generate(agent, tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1)
            if marker.startswith(("ARISU_CODEX_ERROR", "ARISU_GROK_ERROR", "ARISU_WORKBENCH_ERROR")):
                assert agents.read_logs()["lines"][-1] == "[error] " + str(failure.value)
                assert "private-" not in str(agents.read_logs())

        def conflicting_stream(*args: Any):
            args[-1]("ARISU_GROK_ERROR refusal")
            args[-1]('ARISU_RESULT {"final":"partial draft"}')

        generation.setattr(agents, "stream", conflicting_stream)
        with pytest.raises(ValueError, match="declined"):
            agents.generate("grok", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1)

    context = tmp_path / "image-context"
    shutil.copytree(agent_docker.ASSETS, context)
    monkeypatch.setattr(agent_docker, "ASSETS", context)
    labels: Dict[str, Dict[str, str]] = {}

    def command(args: List[str], **kwargs: Any) -> str:
        if args[0] == "tag":
            labels[args[2]] = labels[args[1]]
            tagged.append(args[-1])
        elif args[:2] == ["image", "inspect"]:
            return json.dumps([{"Config": {"Labels": labels[args[-1]]}}])
        elif args[:2] == ["image", "rm"]:
            del labels[args[-1]]
        return ""

    def stream(args: List[str], *rest: Any):
        if args[0] == "build":
            image_labels = {"org.arisu.workbench.policy": str(POLICY_REVISION)}
            for index, arg in enumerate(args):
                if arg == "--label":
                    key, value = args[index + 1].split("=", 1)
                    image_labels[key] = value
            labels[args[args.index("-t") + 1]] = image_labels
        elif args[-1] == "generate":
            rest[-1]('ARISU_RESULT {"final":"new draft"}')

    monkeypatch.setattr(agents, "command", command)
    monkeypatch.setattr(agents, "stream", stream)
    monkeypatch.setattr(agents, "owned", lambda kind, name: kind == "volume" or name in labels)

    def bad_candidate(*args: Any, **kwargs: Any):
        raise ValueError("incompatible policy")

    monkeypatch.setattr(agents, "invoke", bad_candidate)
    with pytest.raises(ValueError):
        agents.manage("codex", "update")
    assert not tagged and not agents.guard.locked() and agents.operation["state"] == "failed"
    assert any("Candidate image validation failed" in line for line in agents.read_logs()["lines"])
    ready = {"authenticated": True, "policy_ready": True, "policy_revision": POLICY_REVISION, "models": [{"id": "available"}]}
    monkeypatch.setattr(agents, "invoke", lambda *args, **kwargs: ready)
    agents.manage("codex", "update")
    assert tagged == [agents.image("codex")] and agents.operation["state"] == "complete"
    agents.manage("grok", "build")

    # Skills are mounted per job. Only the provider whose installed code changed needs a rebuild.
    (context / "skills" / "no-ref" / "SKILL.md").write_text("Updated writing instructions")
    assert all(provider["ready"] for provider in agents.status(refresh=True)["agents"].values())
    (context / "agents" / "codex" / "adapter.py").write_text("# updated provider adapter")
    providers = agents.status(refresh=True)["agents"]
    assert providers["grok"]["ready"] and not providers["codex"]["ready"] and providers["codex"]["update_required"]
    with pytest.raises(ValueError, match="Update CLI"):
        agents.generate("codex", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1)
    for action in ("login", "logout"):
        with pytest.raises(ValueError, match="Update CLI"):
            agents.manage("codex", action)
    activated = list(tagged)
    with monkeypatch.context() as racing_build:

        def build_during_pack_update(*args: Any):
            stream(*args)
            (context / "agents" / "codex" / "adapter.py").write_text("# another update before activation")

        racing_build.setattr(agents, "stream", build_during_pack_update)
        with pytest.raises(ValueError, match="Update CLI"):
            agents.manage("codex", "update")
        assert tagged == activated
    agents.manage("codex", "update")
    assert agents.status()["agents"]["codex"]["ready"]
    assert agents.generate("codex", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1) == "new draft"
    (context / "instructions.txt").write_text("Updated shared instructions")
    assert all(provider["update_required"] for provider in agents.status(refresh=True)["agents"].values())

    # Grok reports the immutable hook once per configuration source. Validate every
    # entry before activation, including unexpected hooks after a valid first entry.
    assets = Path(__file__).resolve().parents[3] / "assets" / "prompt_workbench"
    monkeypatch.syspath_prepend(str(assets))
    grok_provider = importlib.import_module("agents.grok.adapter")
    hook = {
        "event": "pre_tool_use",
        "hookType": "command",
        "target": "/usr/local/bin/python /opt/workbench/agents/grok/hook.py",
        "matcher": ".*",
        "source": {"type": "requirements", "path": "/etc/grok/requirements.toml"},
    }
    configured = {"mcpServers": [{"name": "workbench", "target": "/usr/local/bin/python"}]}
    authenticated = False

    def discover(args: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, "grok 1.0.52")
        if args[-1] == "--help":
            return subprocess.CompletedProcess(
                args, 0, "--tools --disable-web-search --system-prompt-override --prompt-file --include-partial-messages"
            )
        if args[-1] == "--json":
            return subprocess.CompletedProcess(args, 0, json.dumps(configured))
        if args[-1] == "models":
            if authenticated:
                return subprocess.CompletedProcess(args, 0, "You are using XAI_API_KEY.")
            return subprocess.CompletedProcess(args, 1, "Login required")
        raise AssertionError(f"unexpected discovery command: {args!r}")

    with monkeypatch.context() as discovery:
        discovery.setattr(grok_provider, "run", discover)
        discovery.setattr(agents, "invoke", lambda *args, **kwargs: grok_provider.inspect())
        for hooks in (
            [hook],
            [hook, {**hook, "source": {"type": "configToml", "path": "/home/agent/.grok/config.toml"}}],
        ):
            configured["hooks"] = hooks
            agents.manage("grok", "build")
            assert tagged[-1] == agents.image("grok") and agents.operation["state"] == "complete"
        authenticated = True
        discovery.setattr(
            grok_provider,
            "rpc",
            lambda *args: {
                "availableModels": [
                    {
                        "modelId": "multi",
                        "_meta": {"totalContextTokens": 256000, "contextWindows": [500000, 256000, 500000, True, 1.5, -1]},
                    },
                    {"modelId": "single", "_meta": {"totalContextTokens": 128000}},
                    {"modelId": "unknown", "_meta": {"totalContextTokens": True, "contextWindows": "500k"}},
                ]
            },
        )
        multi, single, unknown = grok_provider.inspect()["models"]
        assert (multi["default_context_window"], multi["context_windows"]) == (256000, [500000, 256000])
        assert (single["default_context_window"], single["context_windows"]) == (128000, [])
        assert (unknown["default_context_window"], unknown["context_windows"]) == (None, [])
        activated = list(tagged)
        for hooks in (
            None,
            {},
            [],
            [None],
            [hook, {}],
            [hook, {**hook, "target": "/tmp/unapproved-hook.py"}],
            [hook, {**hook, "hookType": "http"}],
            [hook, {**hook, "event": "post_tool_use"}],
            [hook, {**hook, "matcher": "bash"}],
        ):
            configured["hooks"] = hooks
            with pytest.raises(ValueError, match="Grok managed hook"):
                agents.manage("grok", "update")
            assert tagged == activated and not agents.guard.locked() and agents.operation["state"] == "failed", hooks

    monkeypatch.setattr(
        agents, "status", lambda: {"agents": {"codex": {"models": [{"id": "available", "efforts": ["low", "medium", "high"]}]}}}
    )
    agents.configure("codex", "available", "medium")
    assert parse_configuration(config.read_text())["workbench"]["codex"] == {"model": "available", "effort": "medium"}
    assert DockerAgents(tmp_path).preferences == agents.preferences
    saved = config.read_text()
    config.write_text("{ broken")
    with pytest.raises(ValueError):
        agents.configure("codex", "available", "high")
    assert agents.preferences["codex"]["effort"] == "medium"
    assert config.read_text() == "{ broken"
    config.write_text(saved)
    for model, effort in (("invented", "medium"), ("available", "ultra"), ("available", "max")):
        with pytest.raises(ValueError):
            agents.configure("codex", model, effort)
    agents.log("access_token=secret\nBearer token\nxai-abcdefghijklmnopqrstuvwxyz")
    assert "secret" not in "\n".join(agents.logs) and "abcdefghijklmnopqrstuvwxyz" not in "\n".join(agents.logs)
    # One current session retains long output and pages it without dropping earlier lines.
    agents.begin_logs("codex", "generate", "job-a")
    first = "analysis " + "reference detail " * 1000
    agents.log(first)
    for index in range(1100):
        agents.log(f"step {index}")
    page = agents.read_logs(job="job-a")
    assert page["lines"][0] == first and page["more"]
    retained = list(page["lines"])
    while page["more"]:
        page = agents.read_logs(page["session"], page["cursor"], "job-a")
        retained.extend(page["lines"])
    assert len(retained) == 1101 and retained[-1] == "step 1099"
    assert not agents.read_logs(job="different-job")["lines"]
    agents.finish_logs("complete")
    assert agents.read_logs()["state"] == "complete"
    agents.begin_logs("grok", "login")
    agents.log("Go to https://example.test/device and enter ABCD-EFGH")
    replaced = agents.read_logs(page["session"], page["cursor"])
    assert len(replaced["lines"]) == 1 and replaced["session"] != page["session"]
    agents.log_bytes = 16 * 1024 * 1024
    with pytest.raises(ValueError, match="without truncating"):
        agents.log("over budget")
    assert agents.read_logs()["lines"] == replaced["lines"]

    # An output-budget failure reaps its child without poisoning future management operations.
    popen = subprocess.Popen
    with monkeypatch.context() as local:
        local.setattr(subprocess, "Popen", lambda *args, **kwargs: popen([sys.executable, "-c", "print('over budget')"], **kwargs))
        with pytest.raises(ValueError, match="without truncating"):
            DockerAgents.stream(agents, [], time.monotonic() + 5, agents.stopping)
    assert not agents.stopping.is_set()

    # Both stop conditions reap a live child and report the actual reason.
    children = []
    cancelled = threading.Event()

    def sleeping_child(*args: Any, **kwargs: Any) -> subprocess.Popen:
        child = popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(30)"], **kwargs)
        children.append(child)
        return child

    with monkeypatch.context() as local:
        agents.begin_logs("codex", "generate", "stalled")
        local.setattr(subprocess, "Popen", sleeping_child)
        with pytest.raises(TimeoutError):
            DockerAgents.stream(agents, [], time.monotonic() + 0.1, cancelled)
        assert children[-1].returncode is not None and not cancelled.is_set()
        with pytest.raises(ValueError, match="cancelled") as stopped:
            DockerAgents.stream(agents, [], time.monotonic() + 5, cancelled, receive=lambda _: cancelled.set())
        assert "timed out" not in str(stopped.value) and children[-1].returncode is not None

    # Provider text and reference details survive formatting, but image payloads do not enter logs.
    runner_path = Path(__file__).resolve().parents[3] / "assets/prompt_workbench/events.py"
    spec = importlib.util.spec_from_file_location("workbench_runner", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def records(event: Dict[str, Any], provider: str = "codex") -> List[Dict[str, Any]]:
        wire = runner.activity(event, provider)
        assert len(wire.splitlines()) == 1
        return json.loads(wire.removeprefix("ARISU_ACTIVITY "))["entries"]

    thought = records({"item": {"id": "thought-1", "type": "reasoning", "text": first}})[0]
    assert thought["text"] == first and thought["kind"] == "analysis"
    updated = records({"type": "item.completed", "item": {"id": "thought-1", "type": "reasoning", "text": "Revised thought"}})[0]
    assert updated["id"] == thought["id"] and updated["text"] == "Revised thought"
    tool = runner.activity(
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "workbench",
                "tool": "read_image",
                "arguments": {"asset_id": "reference-1"},
                "result": {"content": [{"type": "image", "data": "private-image-bytes"}, {"type": "text", "text": first}]},
            },
        }
    )
    assert "read_image" in tool and "reference-1" in tool and first in tool and "private-image-bytes" not in tool
    assert "offline" in runner.activity({"type": "error", "message": "offline"})
    loaded = '# Skill\n[analysis] This is file content, not a thought\n{"references": []}'
    for provider, event in (
        (
            "codex",
            {
                "item": {
                    "id": "call-1",
                    "type": "mcp_tool_call",
                    "server": "workbench",
                    "tool": "read_skill",
                    "result": {"content": [{"type": "text", "text": loaded}, {"type": "image", "data": "private-bytes"}]},
                }
            },
        ),
        (
            "grok",
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": [{"type": "text", "text": loaded}, {"type": "image", "data": "private-bytes"}],
                        }
                    ]
                },
            },
        ),
    ):
        record = records(event, provider)[0]
        assert record["kind"] == "tool" and loaded in record["details"] and "private-bytes" not in record["details"]
        assert "[analysis]" not in record["text"]
    grok = records(
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "content": [{"type": "thinking", "thinking": first}, {"type": "text", "text": "Visible answer"}],
            },
        },
        "grok",
    )
    assert [entry["kind"] for entry in grok] == ["analysis", "agent"] and grok[0]["text"] == first
    result = records({"type": "result", "result": "Repeated answer", "usage": {"tokens": 100}}, "grok")
    assert len(result) == 1 and result[0]["kind"] == "progress" and "Repeated answer" not in str(result)
    startup = {"type": "system", "subtype": "init", "mcp_servers": [{"name": "workbench", "status": "pending"}]}
    session = records(startup, "grok")[0]
    assert json.loads(session["details"])["mcp_servers"] == startup["mcp_servers"]
    # Only selected envelope metadata enters rejection diagnostics, bounded in UTF-8 bytes.
    for servers in (
        [{"name": "workbench", "status": "pending", "credentials": "private-secret"}],
        [{"name": "雪" * 200, "status": "🎬" * 200}] * 20,
        [None, {"name": {"secret": "private-secret"}, "status": "Bearer private-token"}],
        {"secret": "private-secret"},
        [{"name": "/private/path", "status": "\x1b[31mprivate-control"}],
    ):
        wire = runner.diagnostic({**startup, "mcp_servers": servers, "prompt": "private-prompt"}, "grok", "grok 1.0.40", "Rejected")
        assert len(wire.splitlines()) == 1 and "private-" not in wire and "/private" not in wire
        entry = json.loads(wire.removeprefix("ARISU_ACTIVITY "))["entries"][0]
        assert len(entry["details"].encode("utf-8")) <= 4096
        summary = json.loads(entry["details"])
        assert summary["provider"] == "grok" and summary["cli_version"] == "grok 1.0.40"
        if isinstance(summary["mcp_servers"], list):
            assert len(summary["mcp_servers"]) <= 8
            for server in summary["mcp_servers"]:
                if isinstance(server, dict):
                    assert all(len(value) <= 160 for value in server.values())
    agents.begin_logs("codex", "generate", "framed")
    agents.log(runner.activity({"item": {"id": "secret", "type": "reasoning", "text": 'api_key="secret"\nBearer token\nSafe text'}}))
    redacted = json.loads(agents.read_logs()["lines"][0].removeprefix("ARISU_ACTIVITY "))["entries"][0]["text"]
    assert "secret" not in redacted and "token" not in redacted and "Safe text" in redacted
    agents.log("ARISU_ACTIVITY {broken")
    assert "Invalid activity record" in agents.read_logs()["lines"][-1]
    # The subprocess transport consumes protocol records without exposing audits or duplicate results.
    wire = (
        "ARISU_AUDIT private-audit\n"
        + runner.activity({"item": {"id": "thought", "type": "reasoning", "text": "Visible thought"}})
        + '\nARISU_RESULT {"final":"final"}\n'
    )
    received = []
    agents.begin_logs("codex", "generate", "transport")
    with monkeypatch.context() as local:
        local.setattr(
            subprocess,
            "Popen",
            lambda *args, **kwargs: popen([sys.executable, "-c", "import sys; sys.stdout.write(" + repr(wire) + ")"], **kwargs),
        )
        DockerAgents.stream(agents, [], time.monotonic() + 5, agents.stopping, receive=received.append)
    assert len(received) == 3 and len(agents.read_logs()["lines"]) == 1
    assert "Visible thought" in agents.read_logs()["lines"][0] and "private-audit" not in str(agents.read_logs())

    # A long thought contains little new text even when Grok or Codex repeatedly
    # emits its entire prefix. Exercise the real pipe, not only the log store.
    for provider in ("grok", "codex"):
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(assets)!r})\n"
            "from events import ActivityStream, activity\n"
            "import events\n"
            "display = ActivityStream()\n"
            "events.time.monotonic = lambda: tick / 4\n"
            "def partial(kind, **fields):\n"
            "    return display.render({'type': 'stream_event', 'event': {'type': kind, **fields}}, 'grok')\n"
            "partial('message_start', message={'id': 'long'})\n"
            "partial('content_block_start', index=0, content_block={'type': 'thinking', 'thinking': ''})\n"
            "for tick in range(1900):\n"
            + (
                "    line = partial('content_block_delta', index=0, delta={'type': 'thinking_delta', 'thinking': 'abcdefghij'})\n"
                if provider == "grok"
                else "    line = activity({'type': 'item.updated', 'item': {'type': 'reasoning', 'id': 'long', 'text': 'abcdefghij' * (tick + 1)}}, 'codex')\n"
            )
            + "    if line: print(line)\n"
            + "print('ARISU_RESULT ' + json.dumps({'final': 'complete'}))\n"
        )
        agents.begin_logs(provider, "generate", "long")
        sizes, final = [], []

        def receive(line: str, sizes: List[int] = sizes, final: List[str] = final):
            sizes.append(len(line.encode("utf-8")))
            if line.startswith("ARISU_RESULT "):
                final.append(json.loads(line.removeprefix("ARISU_RESULT "))["final"])

        with monkeypatch.context() as local:
            local.setattr(subprocess, "Popen", lambda *args, script=script, **kwargs: popen([sys.executable, "-c", script], **kwargs))
            DockerAgents.stream(agents, [], time.monotonic() + 30, agents.stopping, receive=receive)
        assert sum(sizes) > 16 * 1024 * 1024 and final == ["complete"]
        assert agents.log_bytes < 1024 * 1024
        replay = {}
        page = agents.read_logs(job="long")
        while True:
            for line in page["lines"]:
                for entry in json.loads(line.removeprefix("ARISU_ACTIVITY "))["entries"]:
                    key = entry["kind"], entry["id"]
                    replay[key] = (replay[key] if entry.get("append") else "") + entry["text"]
            if not page["more"]:
                break
            page = agents.read_logs(page["session"], page["cursor"], "long")
        assert list(replay.values()) == ["abcdefghij" * 1900]
        # A newly opened viewer receives the same first page, not only the tail.
        assert agents.read_logs()["lines"][0] == agents.logs[0]

    # Compact only complete redacted snapshots; preserve revisions, anonymous
    # records, and tool arguments/results even when IDs recur in one envelope.
    agents.begin_logs("codex", "generate", "updates")

    def framed(*entries: Dict[str, Any]) -> str:
        return "ARISU_ACTIVITY " + json.dumps({"version": 1, "entries": entries}, ensure_ascii=False)

    entry = {"id": "thought", "kind": "analysis", "text": "雪🌅 Bearer ", "details": ""}
    agents.log(framed(entry))
    changed = {**entry, "text": entry["text"] + "private-token"}
    agents.log(framed(changed))
    changed["text"] += "\nContinue 雪"
    agents.log(framed(changed))
    assert "private-token" not in str(agents.logs) and "private-token" not in str(agents.log_items)
    update = json.loads(agents.logs[-1].removeprefix("ARISU_ACTIVITY "))["entries"][0]
    assert update["append"] and update["text"] == "\nContinue 雪"
    assert agents.log(framed(changed)) == 0
    replacement = {**entry, "text": "Revised thought"}
    agents.log(framed(replacement))
    assert "append" not in json.loads(agents.logs[-1].removeprefix("ARISU_ACTIVITY "))["entries"][0]
    tool = {**entry, "kind": "tool", "text": "workbench.read_skill", "details": "arguments"}
    agents.log(framed(tool, {**tool, "details": "arguments\nresult 雪"}, {**entry, "id": ""}, {**entry, "id": ""}))
    entries = json.loads(agents.logs[-1].removeprefix("ARISU_ACTIVITY "))["entries"]
    assert len(entries) == 4 and entries[1]["append"] and entries[1]["details"] == "\nresult 雪"
    assert "append" not in entries[0] and "append" not in entries[2] and entries[2] == entries[3]
    # An image cannot forge the host's append protocol; invalid frames remain charged.
    for invalid in (
        framed({**tool, "append": True, "details": "x" * 4096}),
        'ARISU_ACTIVITY {"version":true,"entries":[]}',
        'ARISU_ACTIVITY {"version":1,"entries":[],"extra":"' + "x" * 4096 + '"}',
    ):
        assert agents.log(invalid) >= len(invalid.encode("utf-8"))
        assert agents.logs[-1] == "[details] Invalid activity record"
    retained = list(agents.logs)
    agents.log_bytes = 16 * 1024 * 1024
    with pytest.raises(ValueError, match="without truncating"):
        agents.log(framed({**replacement, "text": "Revised thought continued"}))
    assert agents.logs == retained and agents.log_items[("analysis", "thought")] == replacement
    agents.begin_logs("codex", "generate", "fresh")
    agents.log(framed(replacement))
    assert "append" not in json.loads(agents.logs[0].removeprefix("ARISU_ACTIVITY "))["entries"][0]

    # Grok can return context and skill text together in one user event. Keep
    # both complete across the Docker pipe, including escaped text near the limit.
    excerpt = '分镜"\n' * 50000
    results = [
        {"type": "tool_result", "tool_use_id": call, "content": "\x01" * 640000 + excerpt + tail}
        for call, tail in (("context", "Bearer private-token\ncontext end"), ("skill", "skill end"))
    ]
    wire_path = tmp_path / "grok-events"
    script = "from pathlib import Path; import sys; sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())"
    with monkeypatch.context() as local:
        local.setattr(subprocess, "Popen", lambda *args, **kwargs: popen([sys.executable, "-c", script, str(wire_path)], **kwargs))
        local.setattr(agents, "stream", DockerAgents.stream.__get__(agents))
        local.setattr(agents, "require_current_image", lambda agent: None)
        local.setattr(agents, "owned", lambda *args: False)
        activity = runner.activity({"type": "user", "message": {"content": results}}, "grok")
        assert len(activity.encode("utf-8")) > 8 * 1024 * 1024
        wire_path.write_text(activity + '\nARISU_RESULT {"final":"complete"}\n', encoding="utf-8")
        agents.begin_logs("grok", "generate", "full-read")
        assert agents.generate("grok", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 10) == "complete"
        logged = json.loads(agents.read_logs()["lines"][-1].removeprefix("ARISU_ACTIVITY "))["entries"]
        assert [item["details"] for item in logged] == [excerpt + "Bearer [redacted]\ncontext end", excerpt + "skill end"]

        for args, oversized in (
            (["grok", "login"], activity),
            (["codex", "generate"], activity),
            (["grok", "generate"], framed(tool, {**entry, "text": excerpt * 3})),
            (["grok", "generate"], framed({**tool, "text": "Tool result", "details": excerpt * 3, "append": True})),
            (["grok", "generate"], framed({**tool, "text": "Tool result", "id": excerpt * 3})),
            (["grok", "generate"], framed({**tool, "text": "Tool result", "details": "x" * (16 * 1024 * 1024)})),
            (["grok", "generate"], excerpt * 3),
        ):
            wire_path.write_text(oversized.replace("\n", "\\n") + "\n", encoding="utf-8")
            with pytest.raises(ValueError, match="without truncating"):
                agents.stream(args, time.monotonic() + 10, agents.stopping)

    # Native diagnostics, hidden audit/result records, and large physical lines
    # still stop and reap the process instead of silently truncating output.
    for prefix, character, length, repeats in (("plain ", "x", 65536, 257), ("ARISU_AUDIT ", "x", 65536, 257), ("", "雪", 350000, 1)):
        agents.begin_logs("codex", "generate", "bounded")
        script = f"for _ in range({repeats}): print({prefix!r} + {character!r} * {length})"
        with monkeypatch.context() as local:
            local.setattr(subprocess, "Popen", lambda *args, script=script, **kwargs: popen([sys.executable, "-c", script], **kwargs))
            with pytest.raises(ValueError, match="without truncating"):
                DockerAgents.stream(agents, [], time.monotonic() + 30, agents.stopping)
    agents.guard.acquire()
    try:
        with pytest.raises(ValueError, match="busy"):
            agents.manage("grok", "login")
    finally:
        agents.guard.release()


def test_mcp_manifest_images_and_unlisted_or_escaping_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    assets = Path(__file__).resolve().parents[3] / "assets" / "prompt_workbench"
    monkeypatch.syspath_prepend(str(assets))
    module_path = assets / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("workbench_mcp", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gate_spec = importlib.util.spec_from_file_location("workbench_gate", assets / "gate.py")
    gate = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate)
    root, skill = tmp_path / "inputs", tmp_path / "skill"
    root.mkdir()
    skill.mkdir()
    (skill / "SKILL.md").write_text("Use the selected H3 grammar.")
    (skill / "script.py").write_text("raise RuntimeError('must never execute')")
    Image.new("RGB", (16, 16), "red").save(root / "image.webp", lossless=True)
    original = (root / "image.webp").read_bytes()
    (root / "unlisted.png").write_bytes(original)
    manifest = {
        "version": 3,
        "requirements": "selected shot",
        "assets": [
            {
                "id": "image",
                "file": "image.webp",
                "mime": "image/webp",
                "attachment_index": 1,
                "width": 16,
                "height": 16,
                "note": "coat",
                "role": "reference",
                "resource_id": "ref",
            }
        ],
    }
    manifest["references"] = [{"id": "ref", "kind": "image", "note": "coat", "inspect": {"asset_ids": ["image"]}}]
    (root / "context.json").write_text(json.dumps(manifest))
    context = module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)
    data = json.loads(context["content"][0]["text"])
    assert data["requirements"] == "selected shot" and data["assets"][0]["path"] == "/inputs/image.webp"
    assert all(block["type"] == "text" for block in context["content"])
    assert module.call("read_skill", {"path": "SKILL.md"}, root, skill)["content"][0]["text"] == "Use the selected H3 grammar."
    assert not gate.authorize("image", {"path": "/inputs/image.webp"}, root, skill)
    assert gate.authorize("get_context", {}, root, skill)
    assert gate.authorize("read_skill", {"path": "SKILL.md"}, root, skill)
    for name, arguments in (
        ("read_image", {"asset_id": "image"}),
        ("read_skill", {"path": "script.py"}),
        ("read_skill", {"path": "../secret"}),
        ("read_skill", {"path": "/etc/passwd"}),
        ("read_skill", {"path": "SKILL.md", "extra": True}),
        ("get_context", {"root": "/etc"}),
    ):
        result = module.respond({"method": "tools/call", "params": {"name": name, "arguments": arguments}}, root, skill)
        assert result["isError"], (name, arguments)
    for path in (
        "/auth/auth.json",
        "/home/agent/.codex/auth.json",
        "/inputs/unlisted.png",
        "/inputs/../secret",
        "/inputs/./image.webp",
        "/inputs/sub/../image.webp",
        "/inputs/image.webp:stream",
        "/inputs/..\\secret",
        "C:/inputs/image.webp",
        "/inputs/%2e%2e/secret",
    ):
        assert not gate.authorize("image", {"path": path}, root, skill), path
    for name in ("apply_patch", "bash", "web_search", "spawn_agent", "unknown"):
        assert not gate.authorize(name, {}, root, skill), name
    assert not gate.authorize("image", {"path": "/inputs/image.webp", "command": "touch /tmp/x"}, root, skill)
    outside = tmp_path / "secret"
    outside.write_bytes(b"outside sentinel")
    (root / "image.webp").unlink()
    (root / "image.webp").symlink_to(outside)
    assert not gate.authorize("image", {"path": "/inputs/image.webp"}, root, skill)
    assert module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)["isError"]
    (skill / "nested").symlink_to(tmp_path, target_is_directory=True)
    assert not gate.authorize("read_skill", {"path": "nested/secret"}, root, skill)
    assert outside.read_bytes() == b"outside sentinel"

    (root / "image.webp").unlink()
    (root / "image.webp").write_bytes(original)

    # Text limits apply to actual UTF-8 bytes, including exactly-full valid documents.
    contract = importlib.import_module("contract")
    document = skill / "SKILL.md"
    text = "雪" * (1024 * 1024 // 3) + "x"
    document.write_text(text, encoding="utf-8")
    assert module.call("read_skill", {"path": "SKILL.md"}, root, skill)["content"][0]["text"] == text
    for content in (text.encode("utf-8") + b"x", b"\xff"):
        document.write_bytes(content)
        assert module.respond({"method": "tools/call", "params": {"name": "read_skill", "arguments": {"path": "SKILL.md"}}}, root, skill)[
            "isError"
        ]
    document.unlink()
    document.symlink_to(outside)
    with pytest.raises(OSError):
        contract.read_text(document)
    document.unlink()
    document.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        contract.read_text(document)
    document.rmdir()
    document.write_text("Use the selected H3 grammar.")
    (root / "context.json").write_bytes(b" " * (1024 * 1024 + 1))
    assert module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)["isError"]
    (root / "context.json").write_text(json.dumps(manifest))

    for change in ({"attachment_index": 2}, {"resource_id": "wrong"}, {"note": "wrong"}, {"file": "unlisted.webp"}):
        invalid = json.loads(json.dumps(manifest))
        invalid["assets"][0].update(change)
        (root / "context.json").write_text(json.dumps(invalid))
        assert module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)["isError"]
    (root / "context.json").write_text(json.dumps(manifest))

    # Container validation accepts the enlarged image budget, including its exact boundary.
    for size in (16 * 1024 * 1024 + 1, 32 * 1024 * 1024, 32 * 1024 * 1024 + 1):
        with (root / "image.webp").open("r+b") as output:
            output.truncate(size)
        result = module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)
        if size <= 32 * 1024 * 1024:
            assert json.loads(result["content"][0]["text"])["assets"][0]["id"] == "image"
        else:
            assert result["isError"]
    (root / "image.webp").write_bytes(original)

    # Provider adapters normalize actual CLI envelopes, including Grok's resolved-name hook.
    codex_spec = importlib.util.spec_from_file_location("codex_hook", assets / "agents/codex/hook.py")
    codex = importlib.util.module_from_spec(codex_spec)
    codex_spec.loader.exec_module(codex)
    grok_spec = importlib.util.spec_from_file_location("grok_hook", assets / "agents/grok/hook.py")
    grok = importlib.util.module_from_spec(grok_spec)
    grok_spec.loader.exec_module(grok)
    assert not gate.authorize(*grok.normalize({"toolName": "read_file", "toolInput": {"target_file": "/inputs/image.webp"}}), root, skill)
    for name in ("use_tool", "workbench__read_skill"):
        normalized = grok.normalize(
            {"toolName": name, "toolInput": {"tool_name": "workbench__read_skill", "tool_input": {"path": "SKILL.md"}}}
        )
        assert gate.authorize(*normalized, root, skill)
    for message in (
        {"toolName": "workbench__get_context", "toolInput": {"tool_name": "workbench__read_skill", "tool_input": {"path": "SKILL.md"}}},
        {"toolName": "use_tool", "toolInput": {"tool_name": "other__read_skill", "tool_input": {"path": "SKILL.md"}}},
        {"toolName": "read_file", "toolInput": {"path": "/inputs/image.webp"}, "toolInputTruncated": True},
    ):
        assert not gate.authorize(*grok.normalize(message), root, skill), message
    assert not gate.authorize(*codex.normalize({"tool_name": "apply_patch", "tool_input": {"command": "arbitrary code"}}), root, skill)

    # Only authentication survives a fresh CLI home; old policy and plugins stay inert.
    runtime_spec = importlib.util.spec_from_file_location("workbench_runtime", assets / "runtime.py")
    runtime_module = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime_module)
    auth = tmp_path / "auth"
    auth.mkdir()
    (auth / "auth.json").write_text('{"token":"old"}')
    (auth / "config.toml").write_text("untrusted configuration")
    (auth / "hooks.json").write_text("untrusted hook")
    with runtime_module.Runtime("codex", auth, tmp_path / "fresh-home") as state:
        assert json.loads((state.home / "auth.json").read_text()) == {"token": "old"}
        assert not (state.home / "hooks.json").exists()
        (state.home / "auth.json").write_text('{"token":"refreshed"}')
        (state.home / "session.log").write_text("disposable state")
    assert json.loads((auth / "auth.json").read_text()) == {"token": "refreshed"}
    assert (auth / "config.toml").read_text() == "untrusted configuration" and not (auth / "session.log").exists()

    # Native provider input encodings preserve the exact attachment and its note identity.
    codex_provider = importlib.import_module("agents.codex.adapter")
    grok_provider = importlib.import_module("agents.grok.adapter")

    def local_path(value: str) -> Path:
        return tmp_path / Path(value).name

    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [{"slug": "test"}]}))
    (tmp_path / "instructions.txt").write_text("MCP and attachments only")
    with monkeypatch.context() as patches:
        patches.setattr(codex_provider, "Path", local_path)
        patches.setattr(grok_provider, "Path", local_path)
        patches.setattr(grok_provider, "INPUTS", root)
        command = codex_provider.command("test", "", "identity index", data["assets"])
        assert command[command.index("--image") + 1] == "/inputs/image.webp"
        grok_command = grok_provider.command("test", "", "identity index", data["assets"])
        blocks = json.loads(Path(grok_command[grok_command.index("--prompt-file") + 1]).read_text())
        assert json.loads(blocks[1]["text"])["note"] == "coat"
        assert blocks[2]["mimeType"] == "image/webp" and base64.b64decode(blocks[2]["data"]) == original
        assert grok_command[grok_command.index("--tools") + 1] == "search_tool,use_tool"
        assert "--include-partial-messages" in grok_command
        grok_defaults = tmp_path / "managed_config.toml"
        assert not grok_defaults.exists()
        (tmp_path / "workbench-prompt.json").unlink()
        for invalid_window in (True, "500000", 500000.5, 0, 2**53):
            with pytest.raises(ValueError, match="context window"):
                grok_provider.command("test", "", "identity index", [], invalid_window)
        quoted_model = 'test.v2"\n[other]\x7f'
        grok_command = grok_provider.command(quoted_model, "high", "identity index", [], 500000)
        assert grok_command[grok_command.index("--model") + 1] == quoted_model
        assert grok_defaults.read_text() == '[model."test.v2\\"\\n[other]\\u007f"]\ncontext_window = 500000\n'
        with pytest.raises(FileExistsError):
            grok_provider.command("other", "", "identity index", [], 256000)
        # The authenticated catalog remains usable at its bound; larger or linked files fail closed.
        catalog = tmp_path / "models_cache.json"
        valid = json.dumps({"models": [{"slug": "test"}]}).encode()
        catalog.write_bytes(valid + b" " * (16 * 1024 * 1024 - len(valid)))
        assert "--image" in codex_provider.command("test", "", "identity index", data["assets"])
        with catalog.open("ab") as output:
            output.write(b" ")
        with pytest.raises(ValueError, match="exceeds limit"):
            codex_provider.command("test", "", "identity index", data["assets"])
        catalog.unlink()
        catalog.symlink_to(outside)
        with pytest.raises(OSError):
            codex_provider.command("test", "", "identity index", data["assets"])
        catalog.unlink()
        catalog.write_bytes(valid)
        (tmp_path / "workbench-prompt.json").unlink()
        (tmp_path / "instructions.txt").write_bytes(b" " * (1024 * 1024 + 1))
        with pytest.raises(ValueError, match="exceeds limit"):
            grok_provider.command("test", "", "identity index", data["assets"])

    # The budget covers actual UTF-8, escaped JSON, metadata, and Base64 chunk boundaries.
    with monkeypatch.context() as patches:
        patches.setattr(grok_provider, "INPUTS", root)
        second = original + b"x" * (3 * 65536 + 1)
        (root / "second.webp").write_bytes(second)
        attachments = [data["assets"][0], {**data["assets"][0], "id": "second", "file": "second.webp", "note": '雪 "coat"\n🎬'}]
        prompt_path = tmp_path / "bounded-prompt.json"
        prompt = 'Camera: 雪 🎬 "pan"\n'
        grok_provider.write_prompt(prompt_path, prompt, attachments)
        serialized = prompt_path.read_bytes()
        blocks = json.loads(serialized)
        assert blocks[0]["text"] == prompt
        for index, (asset, expected) in enumerate(zip(attachments, (original, second))):
            assert json.loads(blocks[1 + index * 2]["text"]) == {key: value for key, value in asset.items() if key != "file"}
            assert base64.b64decode(blocks[2 + index * 2]["data"]) == expected
        # An existing destination is never removed or overwritten on failure.
        with pytest.raises(FileExistsError):
            grok_provider.write_prompt(prompt_path, prompt, attachments)
        assert prompt_path.read_bytes() == serialized
        prompt_path.unlink()
        with patches.context() as boundary:
            boundary.setattr(grok_provider, "PROMPT_LIMIT", len(serialized))
            grok_provider.write_prompt(prompt_path, prompt, attachments)
            assert prompt_path.read_bytes() == serialized
            prompt_path.unlink()
            boundary.setattr(grok_provider, "PROMPT_LIMIT", len(serialized) - 1)
            with pytest.raises(ValueError, match="prompt budget"):
                grok_provider.write_prompt(prompt_path, prompt, attachments)
            assert not prompt_path.exists()
        with pytest.raises(ValueError, match="unavailable"):
            grok_provider.write_prompt(prompt_path, prompt, [{**attachments[0], "file": "missing.webp"}])
        assert not prompt_path.exists()

        # Sparse source fixtures exercise acceptance beyond the former 90 MiB total.
        large_assets = []
        for index in range(3):
            name = f"large-{index}.webp"
            with (root / name).open("wb") as output:
                output.write(original)
                output.truncate(24 * 1024 * 1024)
            large_assets.append({**attachments[0], "id": f"large-{index}", "file": name})
        grok_provider.write_prompt(prompt_path, prompt, large_assets)
        assert 90 * 1024 * 1024 < prompt_path.stat().st_size < 384 * 1024 * 1024
        prompt_path.unlink()

    # Real subprocess pipes exercise final extraction, interrupted streams and forbidden events.
    runner_spec = importlib.util.spec_from_file_location("workbench_stream_runner", assets / "runner.py")
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(runner, "AUDIT", audit_path)
    assert runner.audit() == []
    record = {"allowed": True, "tool": "get_context", "arguments": {}}
    encoded = json.dumps(record).encode()
    audit_path.write_bytes(encoded + b" " * (1024 * 1024 - len(encoded) - 1) + b"\n")
    assert runner.audit() == [record]
    with audit_path.open("ab") as output:
        output.write(b" ")
    with pytest.raises(ValueError, match="exceeds limit"):
        runner.audit()
    audit_path.write_text(json.dumps({**record, "allowed": False}) + "\n")
    with pytest.raises(ValueError, match="outside the Workbench policy"):
        runner.audit()
    audit_path.unlink()
    audit_path.symlink_to(outside)
    with pytest.raises(OSError):
        runner.audit()
    audit_path.unlink()
    audit_path.symlink_to(tmp_path / "missing-audit")
    with pytest.raises(OSError):
        runner.audit()
    audit_path.unlink()
    audit_path.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        runner.audit()
    audit_path.rmdir()
    provider = importlib.import_module("agents.codex.adapter")
    monkeypatch.setattr(provider, "inspect", lambda: {"policy_ready": True, "policy_revision": 7})
    monkeypatch.setattr(provider, "authorize", lambda name, args: gate.authorize(name, args, root, skill))
    monkeypatch.setattr(runner, "adapter_for", lambda agent: provider)
    monkeypatch.setattr(runner, "context", lambda: {"assets": []})
    reads = [{"tool": "get_context", "arguments": {}}, {"tool": "read_skill", "arguments": {"path": "SKILL.md"}}]
    audit_path.write_text("".join(json.dumps({**row, "allowed": True}) + "\n" for row in reads))
    tool_reads = [
        {
            "type": "item.completed",
            "item": {"type": "mcp_tool_call", "id": row["tool"], "server": "workbench", "status": "completed", **row},
        }
        for row in reads
    ]
    prompt_body = "    雪中缓推。\r\n  Hold the shot. 🎬  \r"
    canonical_prompt = f"```text\n{prompt_body}\r\n```"
    codex_reply = f"The draft uses ``` below.\r\n\r\n```\r\n{prompt_body}\r\n```\r\n```Ready for review```."
    assistant = {"type": "item.completed", "item": {"type": "agent_message", "text": codex_reply}}
    empty_message = {"type": "item.completed", "item": {"type": "agent_message", "text": ""}}
    complete = {"type": "turn.completed"}
    reconnect = {"type": "error", "message": "Reconnecting... 1/5 (private-network-details: unexpected status 401)"}
    waiting = {"type": "error", "message": "Reconnecting... waiting for network (private-network-details: token limit)"}
    warning = {
        "type": "item.completed",
        "item": {"id": "notice", "type": "error", "message": "Falling back from WebSockets to HTTPS transport. private-transport-details"},
    }
    deprecation = {"type": "item.completed", "item": {"id": "config", "type": "error", "message": "private-old-option is deprecated"}}
    prohibited = {"type": "item.started", "item": {"type": "command_execution", "command": "touch /tmp/forbidden"}}
    failed_read = {**tool_reads[0], "item": {**tool_reads[0]["item"], "status": "failed"}}

    def codex_stream(events: List[Dict[str, Any]], exit_code: int = 0):
        wire = "\n".join(json.dumps(event) for event in events)
        script = "import sys; print(sys.argv[1]); sys.exit(int(sys.argv[2]))"
        monkeypatch.setattr(provider, "command", lambda *args: [sys.executable, "-c", script, wire, str(exit_code)])

    for events, accepted in (
        ([reconnect, waiting, warning, deprecation, empty_message, *tool_reads, assistant, complete], True),
        ([assistant], False),
        ([assistant, {"type": "item.completed", "item": {"type": "agent_message"}}, complete], False),
        ([assistant, reconnect], False),
        ([assistant, complete, assistant], False),
        ([reconnect, prohibited, assistant, complete], False),
        ([reconnect, failed_read, assistant, complete], False),
        ([{**warning, "item": {**warning["item"], "message": "PreToolUse hook timed out"}}, assistant, complete], False),
        ([{**reconnect, "message": "Reconnecting... 1/5 failed permanently: private-message"}, assistant, complete], False),
        ([{**warning, "item": {**warning["item"], "message": {"details": "private-warning"}}}, assistant, complete], False),
        ([{"type": "control_request"}], False),
        ([{"type": "item.completed", "item": {"type": "image_view", "path": "/inputs/image.webp"}}], False),
    ):
        codex_stream(events)
        if accepted:
            runner.generate("codex", {"model": "test"})
            output = capsys.readouterr().out
            assert "private-" not in output
            lines = output.splitlines()
            final = json.loads(lines[-1].removeprefix("ARISU_RESULT "))["final"]
            assert final == canonical_prompt and finalized_markdown(final) == prompt_body
            assert json.loads(lines[-2].removeprefix("ARISU_AUDIT ")) == runner.audit()
            entries = [entry for line in lines[:-2] for entry in json.loads(line.removeprefix("ARISU_ACTIVITY "))["entries"]]
            progress = [entry["text"].lower() for entry in entries if entry["kind"] == "progress"]
            assert any("connect" in text or "retry" in text for text in progress)
            assert any("warn" in entry["text"].lower() or "notice" in entry["text"].lower() for entry in entries)
            assert all(entry["kind"] != "error" for entry in entries)
        else:
            with pytest.raises(ValueError):
                runner.generate("codex", {"model": "test"})
            output = capsys.readouterr().out
            assert "private-" not in output and "ARISU_RESULT " not in output

    # A terminal failure invalidates even a fenced draft. The native CLI can
    # report a stream error first and send the provider's reason in turn.failed.
    unknown = {"type": "error", "message": "private-unknown-error"}

    def failed_turn(message: str) -> Dict[str, Any]:
        return {"type": "turn.failed", "error": {"message": message}}

    with monkeypatch.context() as cli:
        cli.setattr(runner, "Runtime", nullcontext)
        cli.setattr(runner.signal, "signal", lambda *args: None)
        cli.setattr(sys, "argv", ["runner.py", "codex", "generate"])
        for reply, reason in (
            (prompt_body, "format"),
            ('```json\n{"prompt":"A quiet room."}\n```', "format"),
            ("```text\n" + "x" * 65537 + "\n```", "length"),
            ("ARISU_POLICY_REFUSAL", "refused"),
            (canonical_prompt + "\nARISU_POLICY_REFUSAL", "refused"),
        ):
            codex_stream([{"type": "item.completed", "item": {"type": "agent_message", "text": reply}}, complete])
            cli.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"model":"test"}')))
            with pytest.raises(SystemExit) as stopped:
                runner.main()
            output = capsys.readouterr().out
            assert stopped.value.code == 1 and output.splitlines()[-1] == "ARISU_WORKBENCH_ERROR " + reason
            assert "ARISU_RESULT " not in output
        rate_limit = {"type": "error", "message": "unexpected status 429 Too Many Requests: private-team"}
        for events, exit_code, code in (
            ([assistant, empty_message, complete], 0, "empty_response"),
            ([assistant, {**empty_message, "type": "item.started"}, complete], 0, "empty_response"),
            ([assistant, *tool_reads, complete], 0, "empty_response"),
            ([empty_message, failed_turn("unexpected status 401 Unauthorized: private-body")], 1, "auth"),
            ([assistant, unknown, failed_turn("unexpected status 401 Unauthorized: private-body")], 1, "auth"),
            ([rate_limit], 1, "rate_limit"),
            ([rate_limit, failed_turn("private-unknown-error")], 1, "rate_limit"),
            ([failed_turn("You've hit your usage limit. private-account")], 1, "usage_limit"),
            ([assistant, failed_turn("request deadline exceeded: private-cause")], 1, "timeout"),
            ([assistant, reconnect, failed_turn("stream disconnected before completion: private-cause")], 1, "connection"),
            ([assistant, failed_turn("Your input exceeds the context window of this model. private-prompt")], 1, "token_limit"),
            ([unknown], 1, "execution"),
            ([assistant, unknown, complete], 0, "execution"),
            ([assistant, reconnect], 0, "incomplete"),
            ([assistant, complete], 1, "execution"),
        ):
            codex_stream(events, exit_code)
            cli.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"model":"test"}')))
            with pytest.raises(SystemExit) as stopped:
                runner.main()
            output, errors = capsys.readouterr()
            assert stopped.value.code == 1 and output.splitlines()[-1] == "ARISU_CODEX_ERROR " + code, events
            assert "ARISU_RESULT " not in output and "private-" not in output + errors and "Traceback" not in errors

    # Grok can emit init before MCP connects; required reads still gate final output.
    monkeypatch.setattr(
        grok_provider,
        "inspect",
        lambda: {"policy_ready": True, "policy_revision": 7, "models": [{"id": "test", "context_windows": [256000, 500000]}]},
    )
    monkeypatch.setattr(runner, "adapter_for", lambda agent: grok_provider)
    for agent, model_id, window in (
        ("grok", "test", 320000),
        ("grok", "other", 500000),
        ("grok", "test", 500000.0),
        ("codex", "test", 500000),
    ):
        with pytest.raises(ValueError, match="context window is unavailable"):
            runner.generate(agent, {"model": model_id, "context_window": window})
    init = {
        "type": "system",
        "subtype": "init",
        "permissionMode": "dontAsk",
        "tools": ["search_tool", "use_tool"],
        "mcp_servers": [{"name": "workbench", "status": "pending"}],
    }
    result = {"type": "result", "subtype": "success", "result": f"草稿如下。\r~~~~ markdown\r{prompt_body}\r~~~~~\r完成。"}
    interim = {"type": "assistant", "message": {"content": [{"type": "text", "text": "```text\nA preliminary draft.\n```"}]}}
    for status in ("pending", "connected", "failed", "disabled", "needs-auth", "unknown", None):
        startup = {**init, "mcp_servers": [{"name": "workbench", "status": status}], "extra": {"future": True}}
        if status in ("pending", "connected"):
            assert grok_provider.event(startup) is None
        else:
            with pytest.raises(ValueError, match="Grok .*MCP"):
                grok_provider.event(startup)
    for servers in (None, [], {}, [None], [{}], [{"name": "other", "status": "pending"}], init["mcp_servers"] * 2):
        with pytest.raises(ValueError, match="Grok .*MCP"):
            grok_provider.event({**init, "mcp_servers": servers})
    for events, records, accepted in (
        ([init, interim, result], reads, True),
        ([init, interim, {"type": "result", "text": result["result"]}], reads, True),
        ([init, interim, {**result, "result": "", "text": result["result"]}], reads, False),
        ([init, interim, {"type": "result", "subtype": "success"}], reads, False),
        ([init], reads, False),
        ([init, result, result], reads, False),
        ([init, result], [], False),
        ([init, result], reads[:1], False),
        ([init, result], reads[1:], False),
        ([init, {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True}]}}, result], reads, False),
        ([{**init, "tools": ["bash"]}, result], reads, False),
        ([{**init, "permissionMode": "default"}, result], reads, False),
        ([init, {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "bash", "input": {}}]}}], reads, False),
    ):
        wire = "".join(json.dumps(event) + "\n" for event in events)
        monkeypatch.setattr(runner, "audit", lambda records=records: records)

        grok_command = Mock(return_value=[sys.executable, "-c", "import sys; sys.stdout.write(" + repr(wire) + ")"])
        monkeypatch.setattr(grok_provider, "command", grok_command)
        if accepted:
            runner.generate("grok", {"model": "test", "context_window": 500000})
            assert grok_command.call_args.kwargs == {"context_window": 500000}
            final = json.loads(capsys.readouterr().out.splitlines()[-1].removeprefix("ARISU_RESULT "))["final"]
            assert final == canonical_prompt and finalized_markdown(final) == prompt_body
        else:
            with pytest.raises(ValueError):
                runner.generate("grok", {"model": "test"})
            assert "ARISU_RESULT " not in capsys.readouterr().out

    # Both adapters use the same extraction contract. The limit counts prompt
    # characters, and the policy refusal applies to the entire provider response.
    largest_prompt = "雪" * 65536
    assert contract.final_response(f"Here it is.\n```text\n{largest_prompt}\n```\nDone.") == largest_prompt
    for rejected in (
        "```text\n" + largest_prompt + "雪\n```",
        "Here is the prompt:\n```text\n \t\n```",
        "Here is the prompt:\n```text\nNo closing fence.",
        "```text\nFirst draft.\n```\nRevised:\n```markdown\nSecond draft.\n```",
        "```text\nStart.\n```markdown\nInner block.\n```\nEnd.\n```",
        "```text\nA literal ``` in the prompt.\n```",
        f"~~~markdown\n{canonical_prompt}\n~~~",
        f"{canonical_prompt}\n~~~text\nAnother draft.\n~~~",
        "~~~~text\nToo short.\n~~~",
        "~~~text\nMismatched delimiters.\n```",
    ):
        with pytest.raises(ValueError):
            contract.final_response(rejected)
    for refused in ("ARISU_POLICY_REFUSAL\n" + canonical_prompt, canonical_prompt + "\nARISU_POLICY_REFUSAL"):
        with pytest.raises(ValueError, match="refused"):
            contract.final_response(refused)

    # Grok's inline MCP limit applies to the decoded text. Its streaming event
    # can be much larger after the result is serialized inside another JSON string.
    brief = "画面描述" * 5100 + "End of brief."
    (root / "context.json").write_text(json.dumps({**manifest, "requirements": brief}, ensure_ascii=False), encoding="utf-8")
    text = "\t" * (contract.MAX_TEXT - 3) + "雪"
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    with monkeypatch.context() as native:
        native.setenv("GROK_MAX_MCP_OUTPUT_BYTES", "20000")
        native.setattr(runner, "audit", lambda: reads)
        script = (
            "import json, os, sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(assets)!r})\nfrom mcp_server import call\n"
            f"print(json.dumps({init!r}))\n"
            "for name, args in [('get_context', {}), ('read_skill', {'path': 'SKILL.md'})]:\n"
            f"    value = call(name, args, Path({str(root)!r}), Path({str(skill)!r}))['content'][0]['text']\n"
            "    value = value.encode()[:int(os.environ['GROK_MAX_MCP_OUTPUT_BYTES'])].decode()\n"
            "    reply = {'type': 'MCP', 'server_name': 'workbench', 'tool_name': name, 'output': {'OkayOutput': value}}\n"
            "    block = {'type': 'tool_result', 'tool_use_id': name, 'content': json.dumps(reply, ensure_ascii=False)}\n"
            "    print(json.dumps({'type': 'user', 'message': {'content': [block]}}, ensure_ascii=False))\n"
            f"print(json.dumps({result!r}))"
        )
        native.setattr(grok_provider, "command", lambda *args: [sys.executable, "-c", script])
        runner.generate("grok", {"model": "test"})
        output = capsys.readouterr().out
        replies = [
            json.loads(entry["details"])["output"]["OkayOutput"]
            for line in output.splitlines()
            if line.startswith("ARISU_ACTIVITY ")
            for entry in json.loads(line.removeprefix("ARISU_ACTIVITY "))["entries"]
            if entry["text"] == "Tool result"
        ]
        assert json.loads(replies[0])["requirements"] == brief and replies[1] == text and "ARISU_RESULT " in output

        # The larger allowance belongs to result text alone, including when
        # an otherwise valid tool result comes with oversized unrelated metadata.
        for event in (init, {"type": "user", "message": {"content": [{"type": "tool_result", "content": "small"}]}}):
            script = f"import json; print(json.dumps(dict({event!r}, extra='x' * {contract.MAX_TEXT})))"
            with pytest.raises(ValueError, match="agent event exceeds limit"):
                runner.generate("grok", {"model": "test"})
            assert "ARISU_RESULT " not in capsys.readouterr().out

    # Real Grok terminal errors omit result and can follow a complete-looking
    # assistant draft. Only the classified cause and safe metadata leave the runner.
    failure = {"type": "result", "subtype": "error_during_execution", "is_error": True, "stop_reason": None, "num_turns": 2}
    draft = {"type": "assistant", "message": {"content": [{"type": "text", "text": result["result"]}]}}
    for fields, expected in (
        ({"subtype": "error_max_turns", "stop_reason": "cancelled"}, "turn_limit"),
        ({"subtype": "error_max_structured_output_retries"}, "structured_output"),
        ({"stop_reason": "refusal"}, "refusal"),
        ({"stop_reason": "cancelled"}, "cancelled"),
        ({**result, "is_error": False, "stop_reason": "max_tokens"}, "token_limit"),
        ({"errors": ["context_length_exceeded"]}, "token_limit"),
        ({"error": {"code": "max_output_tokens"}}, "token_limit"),
        ({"errors": ["Not signed in. To authenticate without a browser, run:\n  grok login --device-code"]}, "auth"),
        ({"errors": ["You have reached your free Grok Build usage limit"]}, "usage_limit"),
        ({"errors": ["Too many requests for team private-team. Per-minute token limit reached."]}, "rate_limit"),
        ({"errors": ["The service is temporarily at capacity. Please retry your request shortly."]}, "unavailable"),
        ({"errors": ["The model stopped responding after 180s."]}, "timeout"),
        ({"errors": ["Connection closed unexpectedly"]}, "connection"),
        ({"errors": ["empty response from model (no content)"]}, "empty_response"),
        (
            {"subtype": "private-subtype", "stop_reason": "private-stop", "errors": ["private-prompt"], "result": "private-response"},
            "execution",
        ),
    ):
        wire = "\n".join(json.dumps(item) for item in (init, draft, {**failure, **fields}))
        monkeypatch.setattr(grok_provider, "command", lambda *args, wire=wire: [sys.executable, "-c", "print(" + repr(wire) + ")"])
        with pytest.raises(runner.ProviderResultError) as rejected:
            runner.generate("grok", {"model": "test"})
        output = capsys.readouterr().out
        assert str(rejected.value) == expected, fields
        assert "private-" not in output and "ARISU_RESULT " not in output
        entry = json.loads(output.splitlines()[-1].removeprefix("ARISU_ACTIVITY "))["entries"][0]
        assert entry["kind"] == "details" and json.loads(entry["details"])["num_turns"] == 2

    with monkeypatch.context() as cli:
        cli.setattr(runner, "Runtime", nullcontext)
        cli.setattr(runner.signal, "signal", lambda *args: None)
        cli.setattr(sys, "argv", ["runner.py", "grok", "generate"])
        cli.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"model":"test"}')))
        with pytest.raises(SystemExit) as stopped:
            runner.main()
        assert stopped.value.code == 1
        assert capsys.readouterr().out.splitlines()[-1] == "ARISU_GROK_ERROR execution"

    # A Director task shares one audited writing-skill read across a film whose
    # combined prompts exceed both 7000 characters and the single-prompt output cap.
    with monkeypatch.context() as director:
        path = "writing/1/SKILL.md"
        director.setattr(
            runner, "context", lambda: {"assets": [], "director": {"task": "plan", "writing_skills": [{"id": "base", "path": path}]}}
        )
        film = {"segments": [{"id": f"scene-{i}", "skill": "base", "prompt": "A quiet room. " * 300} for i in range(20)]}
        film["segments"][0]["prompt"] += "Look up.\u2028Stay still."
        payload = json.dumps(film, ensure_ascii=False)
        message = {**result, "result": "```json\n" + payload + "\n```"}
        wire = json.dumps(init) + "\n" + json.dumps(message)
        director.setattr(grok_provider, "command", lambda *args: [sys.executable, "-c", "print(" + repr(wire) + ")"])
        director.setattr(runner, "audit", lambda: reads)
        with pytest.raises(runner.DirectorResponseError) as unread:
            runner.generate("grok", {"model": "test"})
        assert unread.value.reason == "skill_unread" and "ARISU_RESULT " not in capsys.readouterr().out
        director.setattr(runner, "audit", lambda: [*reads, {"tool": "read_skill", "arguments": {"path": path}}])
        with director.context() as invalid:
            invalid.setattr(runner, "Runtime", nullcontext)
            invalid.setattr(runner.signal, "signal", lambda *args: None)
            invalid.setattr(sys, "argv", ["runner.py", "grok", "generate"])
            for task, draft, reason in (
                ("plan", [], "structure"),
                ("plan", {"segments": []}, "structure"),
                ("refine", {"segment": []}, "structure"),
                ("plan", {"segments": [{"skill": []}]}, "skill"),
                ("refine", {"segment": {"skill": {"id": "base"}}}, "skill"),
                ("plan", {"segments": [{"skill": ""}]}, "skill"),
                ("refine", {"segment": {"skill": "unknown"}}, "skill"),
            ):
                task_context = {"assets": [], "director": {"task": task, "writing_skills": [{"id": "base", "path": path}]}}
                invalid.setattr(runner, "context", lambda task_context=task_context: task_context)
                wire = json.dumps({**result, "result": "```json\n" + json.dumps(draft) + "\n```"})
                invalid.setattr(grok_provider, "command", lambda *args, wire=wire: [sys.executable, "-c", "print(" + repr(wire) + ")"])
                invalid.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"model":"test"}')))
                with pytest.raises(runner.DirectorResponseError):
                    runner.main()
                output = capsys.readouterr().out
                assert json.loads(output.splitlines()[-1].removeprefix("ARISU_DIRECTOR_ERROR ")) == {"reason": reason}, draft
                assert "ARISU_RESULT " not in output
        # The host receives the complete JSON even when the provider adds commentary.
        for agent, selected in (("grok", grok_provider), ("codex", provider)):
            director.setattr(runner, "adapter_for", lambda agent, selected=selected: selected)
            for label, before, after in (
                ("json", "I used ``` for the plan below.\n\n", "\n```Done```."),
                ("text", "", "\nThat completes the plan."),
                ("markdown", "分镜草稿如下。\r\n", "\r\n请审阅。"),
                ("", "", ""),
            ):
                response = before + "```" + label + " \t\r\n" + payload + "\r\n```" + after
                events = (
                    [init, {**result, "result": response}]
                    if agent == "grok"
                    else [waiting, {"type": "item.completed", "item": {"type": "agent_message", "text": response}}, complete]
                )
                wire = "\n".join(json.dumps(event) for event in events)
                director.setattr(selected, "command", lambda *args, wire=wire: [sys.executable, "-c", "print(" + repr(wire) + ")"])
                runner.generate(agent, {"model": "test"})
                output = next(
                    line.removeprefix("ARISU_RESULT ") for line in capsys.readouterr().out.split("\n") if line.startswith("ARISU_RESULT ")
                )
                assert json.loads(output)["final"] == "```json\n" + payload + "\n```"
        director.setattr(runner, "adapter_for", lambda agent: grok_provider)
        # Wrong labels, incomplete fences and invalid JSON remain distinct from
        # actual budget exhaustion. Never salvage or truncate an invalid result.
        for response, error_type, reason in (
            ("```python\n" + payload + "\n```", runner.DirectorResponseError, "format"),
            ("```json\n" + payload, runner.DirectorResponseError, "format"),
            ("```json\n\n```", runner.DirectorResponseError, "format"),
            ("First draft:\n```json\n{}\n```\nRevised draft:\n" + message["result"], runner.DirectorResponseError, "format"),
            ("ARISU_POLICY_REFUSAL\n" + message["result"], ValueError, "refused"),
            ('Draft:\n```json\n{"segments":\n```', runner.DirectorResponseError, "json"),
            ("```json\n" + "雪" * (256 * 1024 // 3 + 1) + "\n```", runner.DirectorBudgetError, "UTF-8 bytes"),
        ):
            # Use a fixture file so a size-limit case cannot hit the OS argv limit.
            stream = tmp_path / "director-events.jsonl"
            stream.write_text(json.dumps(init) + "\n" + json.dumps({**result, "result": response}) + "\n")
            director.setattr(
                grok_provider,
                "command",
                lambda *args, stream=stream: [sys.executable, "-c", "import sys; sys.stdout.write(open(sys.argv[1]).read())", str(stream)],
            )
            with pytest.raises(error_type, match=reason):
                runner.generate("grok", {"model": "test"})
            assert "ARISU_RESULT " not in capsys.readouterr().out
        exhausted = json.dumps({"type": "error", "error": {"code": "context_length_exceeded"}})
        director.setattr(grok_provider, "command", lambda *args: [sys.executable, "-c", "print(" + repr(exhausted) + ")"])
        with pytest.raises(runner.DirectorBudgetError, match="context or output budget"):
            runner.generate("grok", {"model": "test"})

    # A CLI burst must be visible before the provider is allowed to finish.
    # An incomplete stderr line must not block stdout, and UTF-8 may span reads.
    acknowledged = tmp_path / "thought-visible"
    continued = tmp_path / "thought-continued"

    def partial(kind: str, **fields: Any) -> Dict[str, Any]:
        return {"type": "stream_event", "event": {"type": kind, **fields}}

    start = partial("message_start", message={"id": "msg-live", "content": []})
    block = partial("content_block_start", index=0, content_block={"type": "thinking", "thinking": ""})
    delta = partial("content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": "Live thought 雪"})
    stop = partial("content_block_stop", index=0)
    message_stop = partial("message_stop")
    full = {
        "type": "assistant",
        "message": {"id": "provider-final-id", "content": [{"type": "thinking", "thinking": "Live thought 雪 continued"}]},
    }
    burst = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in (init, start, block, delta)).encode()
    continuation = json.dumps(partial("content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": " continued"})) + "\n"
    tail = "".join(json.dumps(item) + "\n" for item in (stop, message_stop, full, result))
    split = burst.index("雪".encode()) + 1
    script = (
        "import os, time\nfrom pathlib import Path\n"
        + "os.write(2, b'partial diagnostic')\n"
        + "os.write(1, "
        + repr(burst[:split])
        + ")\n"
        + "time.sleep(0.05)\n"
        + "os.write(1, "
        + repr(burst[split:])
        + ")\n"
        + "deadline = time.monotonic() + 5\n"
        + "while not Path("
        + repr(str(acknowledged))
        + ").exists():\n"
        + "    if time.monotonic() > deadline: raise SystemExit(9)\n"
        + "    time.sleep(0.01)\n"
        + "os.write(1, "
        + repr(continuation.encode())
        + ")\n"
        + "while not Path("
        + repr(str(continued))
        + ").exists():\n"
        + "    if time.monotonic() > deadline: raise SystemExit(10)\n"
        + "    time.sleep(0.01)\n"
        + "os.write(2, b' done\\n')\n"
        + "os.write(1, "
        + repr(tail.encode())
        + ")\n"
    )

    def visible_print(value: str, **kwargs: Any):
        builtins.print(value, **kwargs)
        if "Live thought 雪" in value:
            acknowledged.touch()
        if "Live thought 雪 continued" in value:
            continued.touch()

    with monkeypatch.context() as patches:
        patches.setattr(runner, "print", visible_print, raising=False)
        patches.setattr(runner, "audit", lambda: reads)
        patches.setattr(grok_provider, "command", lambda *args: [sys.executable, "-c", script])
        runner.generate("grok", {"model": "test"})
    output = capsys.readouterr().out
    assert acknowledged.exists() and continued.exists() and "ARISU_RESULT " in output
    thoughts = [
        json.loads(line.removeprefix("ARISU_ACTIVITY "))["entries"] for line in output.splitlines() if line.startswith("ARISU_ACTIVITY ")
    ]
    thoughts = [entry for entries in thoughts for entry in entries if entry["kind"] == "analysis"]
    assert thoughts[0]["text"] == "Live thought 雪"
    assert thoughts[-1]["text"] == "Live thought 雪 continued"
    assert {entry["id"] for entry in thoughts} == {"grok:msg-live:0"}
    assert "[cli] partial diagnostic done" in output

    # Partial tool payloads never become display text or bypass full-call policy checks.
    display = runner.ActivityStream()
    tool_start = partial("content_block_start", index=1, content_block={"type": "tool_use", "id": "call", "name": "use_tool", "input": {}})
    for item in (
        start,
        tool_start,
        partial("content_block_delta", index=1, delta={"type": "input_json_delta", "partial_json": '{"private":"payload"}'}),
        partial("content_block_stop", index=1),
        message_stop,
    ):
        assert grok_provider.event(item) is None
        assert display.render(item, "grok") is None
    with pytest.raises(runner.EventValidationError):
        grok_provider.event(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "use_tool", "input": {"private": "payload"}}]}}
        )
    for invalid in (
        partial("new_event"),
        partial("content_block_delta", index=-1, delta={}),
        partial("content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": []}),
        partial("content_block_start", index=0, content_block={"type": "tool_use", "name": "bash"}),
        partial("content_block_start", index=0, content_block={"type": "image", "data": "private-image"}),
    ):
        with pytest.raises(runner.EventValidationError):
            grok_provider.event(invalid)
    with pytest.raises(runner.EventValidationError):
        runner.ActivityStream().render(delta, "grok")

    # Malformed envelopes fail deliberately, and failure reasons distinguish the cause.
    reasons = set()
    for invalid in (
        {**init, "tools": None},
        {**init, "tools": [{}]},
        {**init, "mcp_servers": None},
        {**init, "mcp_servers": []},
        {**init, "mcp_servers": [None]},
        {**init, "mcp_servers": [{"name": "other", "status": "pending"}]},
        *({**init, "mcp_servers": [{"name": "workbench", "status": state}]} for state in ("failed", "disabled", "needs-auth", "new")),
        {"type": []},
        {"type": "new"},
        {"type": "assistant", "message": None},
        {"type": "assistant", "message": {"content": [None]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": {}}]}},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": []}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": [], "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": [None]}]}},
        {**result, "result": {}},
        {**result, "is_error": "false"},
    ):
        with pytest.raises(runner.EventValidationError) as rejected:
            grok_provider.event(invalid)
        reasons.add(str(rejected.value))
    assert {
        "Grok MCP connection failed",
        "Grok MCP server disabled",
        "Grok MCP authentication required",
        "Grok unsupported MCP status",
        "Grok unauthorized MCP server",
        "Grok malformed MCP server entry",
    } <= reasons

    # Neither provider's rejected payload reaches the normal activity renderer.
    def forbidden_activity(*args: Any) -> str:
        raise AssertionError("rejected event reached activity formatting")

    with monkeypatch.context() as patches:
        patches.setattr(runner.ActivityStream, "render", forbidden_activity)
        for selected, invalid in (
            (grok_provider, {**init, "tools": ["bash"], "prompt": "private-prompt"}),
            (provider, {"type": "item.started", "item": {"type": "command_execution", "command": "private-command"}}),
            (grok_provider, ["private-envelope"]),
        ):
            patches.setattr(runner, "adapter_for", lambda agent, selected=selected: selected)
            patches.setattr(selected, "inspect", lambda: {"policy_ready": True, "policy_revision": 7, "version": "test-cli 1.0"})
            wire = json.dumps(invalid) + "\n"
            patches.setattr(selected, "command", lambda *args, wire=wire: [sys.executable, "-c", "print(" + repr(wire) + ")"])
            with pytest.raises(ValueError):
                runner.generate("grok" if selected is grok_provider else "codex", {"model": "test"})
            output = capsys.readouterr().out
            assert "private-" not in output and "ARISU_RESULT" not in output
            entry = json.loads(output.removeprefix("ARISU_ACTIVITY "))["entries"][0]
            assert entry["kind"] == "error" and json.loads(entry["details"])["cli_version"] == "test-cli 1.0"
