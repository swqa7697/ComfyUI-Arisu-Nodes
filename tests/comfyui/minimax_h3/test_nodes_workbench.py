"""Workbench execution and media boundaries, with no live files, accounts or GPU."""

from __future__ import annotations

import json
import threading
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import av
import pytest
import torch
from PIL import Image

from src.arisu_nodes.minimax_h3 import nodes, workbench
from src.arisu_nodes.minimax_h3.core import Resource, ResourceBundle, VideoSettings, workbench_options
from src.arisu_nodes.minimax_h3.media import revision_for
from src.arisu_nodes.minimax_h3.workbench import Generation, Workbench, job_context, skill_catalog
from src.arisu_nodes.minimax_h3.workbench_media import stage
from tests.support.media import make_audio, make_av

pytestmark = pytest.mark.comfyui


def inputs(**kwargs: Any) -> Dict[str, Any]:
    return {
        "agent": "codex",
        "skill": "bundled:with-ref",
        "context_length": "22",
        "audio_context_length": 24,
        "motion_notes": "",
        "reference_notes": "{}",
        "trigger_words": "",
        "requirements": "",
        "finalized_prompt": "original prompt",
        **kwargs,
    }


def test_workbench_plain_string_first_clip_and_phase_aligned_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = Workbench(tmp_path / "user", tmp_path / "temp")
    monkeypatch.setattr(workbench, "_service", owner)
    monkeypatch.setattr(nodes, "_resource_roots", lambda: {"input": str(tmp_path)})
    node = nodes.ArisuMiniMaxH3PromptWorkbench

    class Vae:
        calls = 0

        def decode(self, latent: torch.Tensor) -> torch.Tensor:
            self.calls += 1
            assert latent.shape == (1, 1, 7, 2, 2)
            assert latent[0, 0, 0, 0, 0] == 15
            return torch.linspace(0, 1, 22)[:, None, None, None].expand(22, 4, 4, 3).unsqueeze(0)

    vae = Vae()
    latent = {"samples": [torch.arange(22).view(1, 1, 22, 1, 1).expand(1, 1, 22, 2, 2), object()]}
    # Ordinary execution never asks for dependencies or decodes even supplied tensors.
    assert node.check_lazy_status() == []
    assert node.execute(**inputs(context_latent=latent, vae=vae)).result == ("original prompt",)
    assert vae.calls == 0

    def job(identifier: str) -> Generation:
        directory = owner.temp / identifier
        directory.mkdir(parents=True)
        value = Generation(
            identifier,
            "w",
            "workflow",
            {"context_length": 22},
            {},
            directory,
            {"w": {"inputs": {"context_latent": ["l", 0], "vae": ["v", 0]}}, "l": {"class_type": "loader", "inputs": {}}},
        )
        owner.jobs[identifier] = value
        return value

    first = job("first")
    assert node.check_lazy_status(prepare_job="first", context_latent=None) == ["context_latent"]
    node.execute(**inputs(prepare_job="first", context_latent=None))
    assert first.prepared.is_set() and not first.motion and vae.calls == 0
    with pytest.raises(ValueError, match="expired"):
        node.execute(**inputs(prepare_job="first"))
    continued = job("continued")
    assert "vae" in node.check_lazy_status(prepare_job="continued", context_latent=latent)
    node.execute(**inputs(prepare_job="continued", context_latent=latent, vae=vae))
    assert vae.calls == 1 and len(continued.motion) == 12
    with Image.open(continued.directory / continued.motion[0]["file"]) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
    with Image.open(continued.directory / continued.motion[-1]["file"]) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
    repeated = job("repeated")
    node.execute(**inputs(prepare_job="repeated", context_latent=latent, vae=vae))
    assert len(repeated.motion) == 12 and vae.calls == 1
    malformed = job("malformed")
    with pytest.raises(ValueError, match="short|phase"):
        node.execute(**inputs(prepare_job="malformed", context_latent={"samples": [torch.zeros(1, 1, 2, 2, 2)]}, vae=vae))
    assert malformed.error and malformed.preparation_done.is_set()
    owner.release("workflow")
    assert all(value.cancelled.is_set() for value in owner.jobs.values()) and not owner.cache


def test_workbench_stages_crops_refuses_escapes_and_cancellation_retains_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "input"
    source.mkdir()
    image_path = source / "reference.png"
    Image.new("RGB", (20, 12), "red").save(image_path)
    original = image_path.read_bytes()
    image = Resource("ref", "image", "input", "reference.png", crop=(2, 2, 8, 6), revision=revision_for(image_path.stat()))
    directory = tmp_path / "stage"
    directory.mkdir()
    payload = {
        "directory": str(directory),
        "roots": {"input": str(source)},
        "frame_count": 22,
        "max_bytes": 100000,
        "resources": [{"role": "reference", "item": image.__dict__}],
    }
    assets = stage(payload)
    with Image.open(directory / assets[0]["file"]) as cropped:
        assert cropped.size == (8, 6) and cropped.getpixel((0, 0)) == (255, 0, 0)
    assert image_path.read_bytes() == original
    # Clip contents and soundtrack inclusion are applied to staged files, not originals.
    video_path = source / "clip.mkv"
    make_av(video_path)
    sound_path = source / "sound.wav"
    make_audio(sound_path)
    video_original = video_path.read_bytes()
    video = Resource("video", "video", "input", "clip.mkv", clip=(0.5, 1.5), include_audio=False, revision=revision_for(video_path.stat()))
    sound = Resource("sound", "audio", "input", "sound.wav", clip=(0.2, 0.7), revision=revision_for(sound_path.stat()))
    for include in (False, True):
        destination = tmp_path / ("sound-on" if include else "sound-off")
        destination.mkdir()
        prepared = stage(
            {
                **payload,
                "directory": str(destination),
                "max_bytes": 1000000,
                "resources": [
                    {"role": "reference", "item": item.__dict__}
                    for item in (replace(video, include_audio=include), sound, replace(image, muted=True))
                ],
            }
        )
        assert not any(asset.get("resource_id") == "ref" for asset in prepared)
        assert sum(asset["role"] == "reference_soundtrack" for asset in prepared) == int(include)
        selected_video = next(asset for asset in prepared if asset["mime"] == "video/webm")
        with av.open(str(destination / selected_video["file"])) as container:
            assert not container.streams.audio
            frames = list(container.decode(video=0))
            assert len(frames) == 22
        stills = [asset for asset in prepared if asset["role"] == "reference_video_frame"]
        with Image.open(destination / stills[0]["file"]) as still:
            assert still.getpixel((0, 0))[0] == 12
        selected_audio = next(asset for asset in prepared if asset.get("resource_id") == "sound")
        with wave.open(str(destination / selected_audio["file"])) as encoded:
            assert encoded.getnframes() == 4000 and encoded.getframerate() == 8000
    assert video_path.read_bytes() == video_original
    outside = tmp_path / "outside.png"
    outside.write_bytes(original)
    (source / "escape.png").symlink_to(outside)
    for invalid in (replace(image, path="../outside.png"), replace(image, path="escape.png"), replace(image, revision="stale")):
        payload["resources"] = [{"role": "reference", "item": invalid.__dict__}]
        with pytest.raises((ValueError, OSError)):
            stage(payload)
    assert outside.read_bytes() == original
    user = tmp_path / "user"
    custom = user / "skills" / "director"
    custom.mkdir(parents=True)
    (custom / "SKILL.md").write_text("---\nname: director\ndescription: test\n---\nDraft a prompt.")
    assert "custom:director" in skill_catalog(user)
    (custom / "escape").symlink_to(outside)
    assert "custom:director" not in skill_catalog(user)

    owner = Workbench(user, tmp_path / "jobs")
    owner.temp.mkdir()
    job = Generation("cancel", "w", "workflow", {}, {}, owner.temp / "cancel", {})
    job.directory.mkdir()
    job.taken = True
    queue_done = threading.Event()
    job.queue_finished = queue_done.is_set
    job.cancelled.set()
    owner.jobs[job.id] = job
    owner.agents.guard.acquire()
    worker = threading.Thread(target=owner.execute, args=(job,))
    worker.start()
    # The request is cancelled but the execution worker still owns its VAE.
    assert not job.preparation_done.wait(0.05) and owner.agents.guard.locked()
    job.preparation_done.set()
    assert owner.agents.guard.locked()
    queue_done.set()
    worker.join(2)
    assert not worker.is_alive() and not owner.agents.guard.locked() and job.state == "cancelled"
    assert not job.directory.exists()

    # Complete the real orchestration with a CPU worker, then reuse its staged-media cache.
    ready = {"docker": True, "agents": {"codex": {"ready": True, "selection": {"model": "test", "effort": "medium"}}}}
    monkeypatch.setattr(owner.agents, "status", lambda: ready)

    def generated(agent: str, directory: Path, skill: Path, *args: Any) -> str:
        context = json.loads((directory / "context.json").read_text())
        assert context["version"] == 2 and context["keyframes"] == {"first": None, "last": None}
        assert context["motion"]["present"] is False and context["motion"]["stills"] == []
        assert context["references"][0]["note"] == "red coat"
        assert context["references"][0]["inspect"]["type"] == "image"
        assert context["assets"][0]["id"] in context["references"][0]["inspect"]["asset_ids"]
        with Image.open(directory / context["assets"][0]["file"]) as prepared:
            assert prepared.size == (8, 6)
        assert (skill / "SKILL.md").is_file()
        return "```markdown\nA red coat in the rain.\n```"

    monkeypatch.setattr(owner.agents, "generate", generated)
    for index in range(2):
        options = workbench_options({"source_id": "studio", "reference_notes": {"studio:ref:input:reference.png": "red coat"}})
        prepared_job = owner.create("w", "active", options, {"w": {"inputs": {}}})
        prepared_job.resources = ResourceBundle(images=(image,))
        prepared_job.roots = {"input": str(source)}
        prepared_job.prepared.set()
        owner.execute(prepared_job)
        assert prepared_job.state == "complete" and prepared_job.draft == "A red coat in the rain."
        assert not prepared_job.directory.exists() and not owner.agents.guard.locked()
        if index == 0:

            def unexpected_worker(*args: Any, **kwargs: Any):
                raise AssertionError("cached references started another conversion worker")

            monkeypatch.setattr(workbench.subprocess, "Popen", unexpected_worker)
    assert len(owner.cache) == 1 and image_path.read_bytes() == original
    grouped_job = Generation(
        "grouped",
        "w",
        "active",
        workbench_options({"source_id": "studio", "motion_notes": "camera still pushing"}),
        {},
        owner.temp,
        {},
    )
    grouped_job.settings = VideoSettings(1280, 720, 145, "16:9 (Widescreen)")
    grouped_job.motion = [{"id": "motion-00", "file": "motion-00.png", "mime": "image/png", "role": "motion", "timestamp": 0.91}]
    grouped = job_context(
        grouped_job,
        [
            {
                "id": "0",
                "file": "0.png",
                "mime": "image/png",
                "resource_id": "ref",
                "role": "first_keyframe",
                "name": "reference.png",
            },
            {
                "id": "1",
                "file": "1.png",
                "mime": "image/png",
                "resource_id": "video",
                "role": "reference_video_frame",
                "name": "clip.mkv",
                "timestamp": 0.0,
            },
        ],
        ResourceBundle(first=image, videos=(replace(video, include_audio=False),)),
    )
    assert grouped["keyframes"]["first"]["asset_id"] == "0" and grouped["keyframes"]["last"] is None
    assert grouped["references"][0]["kind"] == "video" and grouped["references"][0]["inspect"]["frames"][0]["asset_id"] == "1"
    assert grouped["motion"]["present"] and grouped["motion"]["stills"][0]["asset_id"] == "motion-00"
    assert grouped["duration_seconds"] == 145 / 24
    assert grouped["motion"]["delivered_duration_seconds"] == (145 - 22) / 24
    owner.release("active")
    assert not owner.cache
    with pytest.raises(ValueError, match="closed"):
        owner.create("w", "active", {}, {"w": {"inputs": {}}})
    assert not owner.agents.guard.locked()
