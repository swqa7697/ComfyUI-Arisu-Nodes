"""Management regressions without Docker, accounts, ComfyUI, or torch."""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List

import pytest
from PIL import Image

from src.arisu_nodes.common.paths import CONFIG_TEMPLATE, parse_configuration
from src.arisu_nodes.minimax_h3.agent_docker import DockerAgents
from src.arisu_nodes.minimax_h3.core import (
    finalized_markdown,
    motion_samples,
    motion_tail,
    preparation_graph,
    workbench_options,
    workbench_samples,
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
    for frames, steps in ((5, 2), (22, 7), (39, 12), (56, 17)):
        assert motion_tail(22, frames) == (22 - steps, 22)
        retained = workbench_samples(frames)
        assert len(retained) == min(frames, 8) and retained[0] == 0 and retained[-1] == frames - 1
        motion = motion_samples(frames)
        assert len(motion) == {5: 2, 22: 4, 39: 6, 56: 8}[frames] and motion[0] == 0 and motion[-1] == frames - 1
    for total, length in ((2, 22), (23, 22), (22, 1)):
        with pytest.raises(ValueError):
            motion_tail(total, length)
    for label in ("markdown", "text", ""):
        assert finalized_markdown("```" + label + "\nA quiet dolly shot.\n```") == "A quiet dolly shot."
    for text in (
        "thinking\n```markdown\nprompt\n```",
        "```markdown\n\n```",
        "```python\nprint(1)\n```",
        "ARISU_POLICY_REFUSAL",
        "```markdown\nx\n```\n```markdown\ny\n```",
    ):
        with pytest.raises(ValueError):
            finalized_markdown(text)
    assert workbench_options({"audio_context_length": 0})["audio_context_length"] == 0
    for invalid in ({"agent": "shell"}, {"audio_context_length": True}, {"reference_notes": {"x": 2}}, {"requirements": "\x00"}):
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

    # An obsolete image must never run its old entrypoint for discovery.
    with monkeypatch.context() as stale:
        stale.setattr(agents, "owned", lambda *args: True)
        stale.setattr(agents, "command", lambda args, **kwargs: "linux" if args[0] == "info" else '[{"Config":{"Labels":{}}}]')
        stale.setattr(agents, "invoke", lambda *args, **kwargs: pytest.fail("obsolete image executed"))
        old = agents.status(refresh=True)
        assert not old["agents"]["codex"]["ready"]
        with pytest.raises(ValueError, match="update"):
            agents.generate("codex", tmp_path, tmp_path, {}, agents.stopping, time.monotonic() + 1)

    def command(args: List[str], **kwargs: Any) -> str:
        if args[0] == "tag":
            tagged.append(args[-1])
        return ""

    monkeypatch.setattr(agents, "command", command)
    monkeypatch.setattr(agents, "stream", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents, "owned", lambda *args: True)

    def bad_candidate(*args: Any, **kwargs: Any):
        raise ValueError("incompatible policy")

    monkeypatch.setattr(agents, "invoke", bad_candidate)
    with pytest.raises(ValueError):
        agents.manage("codex", "update")
    assert not tagged and not agents.guard.locked() and agents.operation["state"] == "failed"
    monkeypatch.setattr(agents, "invoke", lambda *args, **kwargs: {"policy_ready": True, "policy_revision": 6})
    agents.manage("codex", "update")
    assert tagged == [agents.image("codex")] and agents.operation["state"] == "complete"
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

    # Provider text and reference details survive formatting, but image payloads do not enter logs.
    runner_path = Path(__file__).resolve().parents[3] / "assets/prompt_workbench/events.py"
    spec = importlib.util.spec_from_file_location("workbench_runner", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner.activity({"item": {"type": "reasoning", "text": first}}) == "[analysis] " + first
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

    for change in ({"attachment_index": 2}, {"resource_id": "wrong"}, {"note": "wrong"}, {"file": "unlisted.webp"}):
        invalid = json.loads(json.dumps(manifest))
        invalid["assets"][0].update(change)
        (root / "context.json").write_text(json.dumps(invalid))
        assert module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root, skill)["isError"]
    (root / "context.json").write_text(json.dumps(manifest))

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

    # Real subprocess pipes exercise final extraction, interrupted streams and forbidden events.
    runner_spec = importlib.util.spec_from_file_location("workbench_stream_runner", assets / "runner.py")
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    provider = importlib.import_module("agents.codex.adapter")
    monkeypatch.setattr(provider, "inspect", lambda: {"policy_ready": True, "policy_revision": 6})
    monkeypatch.setattr(runner, "adapter_for", lambda agent: provider)
    monkeypatch.setattr(runner, "context", lambda: {"assets": []})
    monkeypatch.setattr(
        runner, "audit", lambda: [{"tool": "get_context", "arguments": {}}, {"tool": "read_skill", "arguments": {"path": "SKILL.md"}}]
    )
    assistant = {"type": "item.completed", "item": {"type": "agent_message", "text": "```text\nA quiet dolly shot.\n```"}}
    complete = {"type": "turn.completed"}
    for events, accepted in (
        ([assistant, complete], True),
        ([assistant], False),
        ([assistant, complete, assistant], False),
        ([{"type": "item.started", "item": {"type": "command_execution", "command": "touch /tmp/forbidden"}}], False),
        ([{"type": "control_request"}], False),
        ([{"type": "item.completed", "item": {"type": "image_view", "path": "/inputs/image.webp"}}], False),
        ([{"type": "item.completed", "item": {"type": "agent_message", "text": "ARISU_POLICY_REFUSAL"}}, complete], False),
    ):
        wire = "".join(json.dumps(event) + "\n" for event in events)
        monkeypatch.setattr(
            provider, "command", lambda *args, wire=wire: [sys.executable, "-c", "import sys; sys.stdout.write(" + repr(wire) + ")"]
        )
        if accepted:
            runner.generate("codex", {"model": "test"})
            assert "ARISU_RESULT " in capsys.readouterr().out
        else:
            with pytest.raises(ValueError):
                runner.generate("codex", {"model": "test"})
            assert "ARISU_RESULT " not in capsys.readouterr().out
