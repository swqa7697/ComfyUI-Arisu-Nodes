"""Management regressions without Docker, accounts, ComfyUI, or torch."""

from __future__ import annotations

import base64
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any, List

import pytest

from src.arisu_nodes.minimax_h3.agent_docker import DockerAgents
from src.arisu_nodes.minimax_h3.core import finalized_markdown, motion_tail, preparation_graph, workbench_options, workbench_samples


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
    # One motion wire stays inert and cannot execute its producer.
    del prompt["w"]["inputs"]["vae"]
    assert set(preparation_graph(prompt, "w")) == {"w"}
    for frames, steps in ((5, 2), (22, 7), (39, 12), (56, 17)):
        assert motion_tail(22, frames) == (22 - steps, 22)
        retained = workbench_samples(frames)
        assert len(retained) == min(frames, 12) and retained[0] == 0 and retained[-1] == frames - 1
    for total, length in ((2, 22), (23, 22), (22, 1)):
        with pytest.raises(ValueError):
            motion_tail(total, length)
    assert finalized_markdown("```markdown\nA quiet dolly shot.\n```") == "A quiet dolly shot."
    for text in (
        "thinking\n```markdown\nprompt\n```",
        "```markdown\n\n```",
        "```text\nprompt\n```",
        "```markdown\nx\n```\n```markdown\ny\n```",
    ):
        with pytest.raises(ValueError):
            finalized_markdown(text)
    assert workbench_options({"audio_context_length": 0})["audio_context_length"] == 0
    for invalid in ({"agent": "shell"}, {"audio_context_length": True}, {"reference_notes": {"x": 2}}, {"requirements": "\x00"}):
        with pytest.raises(ValueError):
            workbench_options(invalid)


def test_agent_update_preserves_working_image_and_settings_reject_unavailable_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    agents = DockerAgents(tmp_path)
    tagged: List[str] = []
    # Docker is usable before either image exists; inspect represents absence with [].
    monkeypatch.setattr(shutil, "which", lambda value: "/test/docker")
    monkeypatch.setattr(agents, "command", lambda args, **kwargs: "linux" if args[0] == "info" else "[]")
    status = agents.status(refresh=True)
    assert status["docker"] and all(not provider["installed"] and not provider["ready"] for provider in status["agents"].values())

    def command(args: List[str], **kwargs: Any) -> str:
        if args[0] == "tag":
            tagged.append(args[-1])
        return ""

    monkeypatch.setattr(agents, "command", command)
    monkeypatch.setattr(agents, "start_logs", lambda: None)
    monkeypatch.setattr(agents, "stream", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents, "owned", lambda *args: True)

    def bad_candidate(*args: Any, **kwargs: Any):
        raise ValueError("incompatible Auto mode")

    monkeypatch.setattr(agents, "invoke", bad_candidate)
    with pytest.raises(ValueError):
        agents.manage("codex", "update")
    assert not tagged and not agents.guard.locked() and agents.operation["state"] == "failed"
    monkeypatch.setattr(agents, "invoke", lambda *args, **kwargs: {"auto": True})
    agents.manage("codex", "update")
    assert tagged == [agents.image("codex")] and agents.operation["state"] == "complete"
    monkeypatch.setattr(
        agents, "status", lambda: {"agents": {"codex": {"models": [{"id": "available", "efforts": ["low", "medium", "high"]}]}}}
    )
    agents.configure("codex", "available", "medium")
    assert json.loads((tmp_path / "workbench.json").read_text())["codex"] == {"model": "available", "effort": "medium"}
    for model, effort in (("invented", "medium"), ("available", "ultra"), ("available", "max")):
        with pytest.raises(ValueError):
            agents.configure("codex", model, effort)
    agents.log("access_token=secret\nBearer token\nxai-abcdefghijklmnopqrstuvwxyz")
    assert "secret" not in "\n".join(agents.logs) and "abcdefghijklmnopqrstuvwxyz" not in "\n".join(agents.logs)
    agents.guard.acquire()
    try:
        with pytest.raises(ValueError, match="busy"):
            agents.manage("grok", "login")
    finally:
        agents.guard.release()


def test_mcp_manifest_images_and_unlisted_or_escaping_assets(tmp_path: Path):
    module_path = Path(__file__).resolve().parents[3] / "assets" / "prompt_workbench" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("workbench_mcp", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "inputs"
    root.mkdir()
    original = b"test fixture bytes"
    (root / "image.png").write_bytes(original)
    manifest = {"requirements": "selected shot", "assets": [{"id": "image", "file": "image.png", "mime": "image/png"}]}
    (root / "context.json").write_text(json.dumps(manifest))
    context = module.respond({"method": "tools/call", "params": {"name": "get_context", "arguments": {}}}, root)
    assert json.loads(context["content"][0]["text"]) == manifest
    image = module.call("read_image", {"asset_id": "image"}, root)
    assert base64.b64decode(image["content"][0]["data"]) == original
    for arguments in ({"asset_id": "../image.png"}, {"asset_id": "image", "path": "/etc/passwd"}, {}):
        result = module.respond({"method": "tools/call", "params": {"name": "read_image", "arguments": arguments}}, root)
        assert result["isError"]
    outside = tmp_path / "secret"
    outside.write_bytes(b"outside sentinel")
    (root / "image.png").unlink()
    (root / "image.png").symlink_to(outside)
    with pytest.raises(ValueError):
        module.call("read_image", {"asset_id": "image"}, root)
    assert outside.read_bytes() == b"outside sentinel"
