"""Workbench execution and media boundaries, with no live files, accounts or GPU."""

from __future__ import annotations

import importlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import pytest
import torch
from PIL import Image

from src.arisu_nodes.minimax_h3 import media, nodes, workbench
from src.arisu_nodes.minimax_h3.core import Resource, ResourceBundle, VideoSettings, workbench_options
from src.arisu_nodes.minimax_h3.media import revision_for
from src.arisu_nodes.minimax_h3.workbench import Generation, Workbench, job_context, skill_catalog
from src.arisu_nodes.minimax_h3.workbench_media import stage
from tests.support.media import make_audio, make_av, make_video
from tests.support.workers import assert_worker_isolated, poison_parent

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
        length = 22

        def decode(self, latent: torch.Tensor) -> torch.Tensor:
            self.calls += 1
            steps = 2 + ((self.length - 5) // 17) * 5
            assert latent.shape == (1, 1, steps, 2, 2)
            assert latent[0, 0, 0, 0, 0] == 22 - steps
            return torch.linspace(0, 1, self.length)[:, None, None, None].expand(self.length, 4, 4, 3).unsqueeze(0)

    vae = Vae()
    latent = {"samples": [torch.arange(22).view(1, 1, 22, 1, 1).expand(1, 1, 22, 2, 2), object()]}
    # Ordinary execution never asks for dependencies or decodes even supplied tensors.
    assert node.check_lazy_status() == []
    assert node.execute(**inputs(context_latent=latent, vae=vae)).result == ("original prompt",)
    assert vae.calls == 0

    def job(identifier: str, length: int = 22) -> Generation:
        directory = owner.temp / identifier
        directory.mkdir(parents=True)
        value = Generation(
            identifier,
            "w",
            "workflow",
            {"context_length": length},
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
    assert vae.calls == 1 and len(continued.motion) == 4
    with Image.open(continued.directory / continued.motion[0]["file"]) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
    with Image.open(continued.directory / continued.motion[-1]["file"]) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
    repeated = job("repeated")
    node.execute(**inputs(prepare_job="repeated", context_latent=latent, vae=vae))
    assert len(repeated.motion) == 4 and vae.calls == 1
    for length, count in ((5, 2), (39, 6), (56, 8)):
        vae.length = length
        selected = job("motion-" + str(length), length)
        node.execute(**inputs(prepare_job=selected.id, context_latent=latent, vae=vae))
        assert len(selected.motion) == count
        assert selected.motion[0]["timestamp"] == 0 and selected.motion[-1]["timestamp"] == (length - 1) / 24
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
    # Video sampling ignores soundtrack inclusion; audio is notes only.
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
        assert len(prepared) == 8 and all(asset["mime"] == "image/webp" for asset in prepared)
        assert all(asset["resource_id"] == "video" for asset in prepared)
        stills = prepared
        with Image.open(destination / stills[0]["file"]) as still:
            assert still.getpixel((0, 0))[0] == 12
        with Image.open(destination / stills[-1]["file"]) as still:
            assert still.getpixel((0, 0))[0] == 35
        assert stills[0]["timestamp"] == 0 and stills[-1]["source_timestamp"] < 1.5
        assert [asset["sequence_index"] for asset in stills] == list(range(8))

    # Presentation timestamps, short intervals and exclusive endpoints determine samples.
    variable = source / "variable.mkv"
    make_video(variable, timestamps=[0, 100, 200, 900, 1000, 1100, 1600, 1700, 1900])
    for number, clip in enumerate(((0.1, 1.7), (0.11, 0.19), (0.1, 0.2))):
        destination = tmp_path / ("vfr-" + str(number))
        destination.mkdir()
        selected = replace(video, path=variable.name, clip=clip, revision=revision_for(variable.stat()))
        sampled = stage({**payload, "directory": str(destination), "resources": [{"role": "reference", "item": selected.__dict__}]})
        stamps = [asset["source_timestamp"] for asset in sampled]
        assert stamps == sorted(set(stamps)) and len(stamps) <= 8
        assert stamps[0] == 0.1 and stamps[-1] == (1.6 if number == 0 else 0.1)

    # Cap only oversized pixels, preserve alpha, and retain lossless small pixels.
    for number, size in enumerate(((39, 17), (4000, 20), (5000, 100))):
        alpha = source / ("alpha-" + str(number) + ".png")
        Image.new("RGBA", size, (123, 45, 67, 89)).save(alpha)
        selected = replace(image, path=alpha.name, crop=None, revision=revision_for(alpha.stat()))
        destination = tmp_path / ("alpha-" + str(number))
        destination.mkdir()
        asset = stage({**payload, "directory": str(destination), "resources": [{"role": "reference", "item": selected.__dict__}]})[0]
        with Image.open(destination / asset["file"]) as result:
            assert result.format == "WEBP" and result.size == ((4000, 80) if number == 2 else size)
            if number < 2:
                assert result.getpixel((0, 0)) == (123, 45, 67, 89)
    oriented = source / "oriented.png"
    portrait = Image.new("RGBA", (6, 4), (7, 8, 9, 255))
    exif = portrait.getexif()
    exif[274] = 6
    portrait.save(oriented, exif=exif)
    selected = replace(image, path=oriented.name, crop=(0, 2, 4, 4), revision=revision_for(oriented.stat()))
    destination = tmp_path / "orientation"
    destination.mkdir()
    oriented_asset = stage({**payload, "directory": str(destination), "resources": [{"role": "reference", "item": selected.__dict__}]})[0]
    with Image.open(destination / oriented_asset["file"]) as result:
        assert result.size == (4, 4) and not result.getexif()
    with pytest.raises(ValueError, match="capacity"):
        stage({**payload, "max_bytes": 1})

    # Exercise the encoder's actual bounded sink without allocating noisy megapixel fixtures.
    with monkeypatch.context() as patches:
        for size in (16 * 1024 * 1024 + 1, 32 * 1024 * 1024, 32 * 1024 * 1024 + 1):

            def sized_encode(self: Any, output: Any, size: int = size, **kwargs: Any):
                chunk = b"x" * (1024 * 1024)
                for _ in range(size // len(chunk)):
                    output.write(chunk)
                output.write(chunk[: size % len(chunk)])

            patches.setattr(Image.Image, "save", sized_encode)
            destination = tmp_path / f"image-budget-{size}"
            destination.mkdir()
            bounded = {**payload, "directory": str(destination), "max_bytes": 64 * 1024 * 1024}
            if size <= 32 * 1024 * 1024:
                prepared = stage(bounded)
                assert (destination / prepared[0]["file"]).stat().st_size == size
            else:
                with pytest.raises(ValueError, match="capacity"):
                    stage(bounded)
                assert all(path.stat().st_size <= 32 * 1024 * 1024 for path in destination.iterdir())

    # Notes-only audio never opens a decoder, even for duration probing.
    with monkeypatch.context() as patches:

        def forbidden_decoder(*args: Any, **kwargs: Any):
            raise AssertionError("audio must not open a decoder")

        patches.setattr(media, "open_media", forbidden_decoder)
        assert stage({**payload, "resources": [{"role": "reference", "item": sound.__dict__}]}) == []
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
    marker = poison_parent(tmp_path / "hostile", monkeypatch)
    real_spawn = workbench.subprocess.Popen

    def isolated(arguments: Any, **kwargs: Any) -> Any:
        assert_worker_isolated(arguments, kwargs["env"], real_spawn)
        return real_spawn(arguments, **kwargs)

    monkeypatch.setattr(workbench.subprocess, "Popen", isolated)
    ready = {"docker": True, "agents": {"codex": {"ready": True, "selection": {"model": "test", "effort": "medium"}}}}
    monkeypatch.setattr(owner.agents, "status", lambda: ready)

    def generated(agent: str, directory: Path, skill: Path, *args: Any) -> str:
        context = json.loads((directory / "context.json").read_text())
        assert context["version"] == 3 and context["keyframes"] == {"first": None, "last": None}
        assert context["motion"]["present"] is False and context["motion"]["stills"] == []
        assert context["references"][0]["note"] == ("red coat" if index == 0 else "blue coat")
        assert context["assets"][0]["note"] == context["references"][0]["note"]
        assert context["assets"][0]["attachment_index"] == 1
        assert context["references"][0]["inspect"]["type"] == "image"
        assert context["assets"][0]["id"] in context["references"][0]["inspect"]["asset_ids"]
        with Image.open(directory / context["assets"][0]["file"]) as prepared:
            assert prepared.size == (8, 6)
        assert (skill / "SKILL.md").is_file()
        return "```markdown\nA red coat in the rain.\n```"

    monkeypatch.setattr(owner.agents, "generate", generated)
    for index in range(2):
        options = workbench_options(
            {"source_id": "studio", "reference_notes": {"studio:ref:input:reference.png": "red coat" if index == 0 else "blue coat"}}
        )
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
    assert not marker.exists()
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
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    grouped_job.directory = mixed
    first_image = replace(image, id="first")
    second_video = replace(video, id="second-video")
    mixed_assets = stage(
        {
            **payload,
            "directory": str(mixed),
            "max_bytes": 1000000,
            "resources": [
                {"role": role, "item": item.__dict__}
                for role, item in (("first_keyframe", first_image), ("reference", image), ("reference", video), ("reference", second_video))
            ],
        }
    )
    owner.cache_motion(grouped_job, "mixed-motion", [Image.new("RGB", (16, 16), "blue") for _ in range(4)])
    grouped_job.options["source_id"] = "studio"
    grouped_job.options["reference_notes"] = {
        "studio:ref:input:reference.png": "red coat",
        "studio:video:input:clip.mkv": "slow camera",
        "studio:second-video:input:clip.mkv": "fast camera",
    }
    grouped = job_context(
        grouped_job, mixed_assets + grouped_job.motion, ResourceBundle(first=first_image, images=(image,), videos=(video, second_video))
    )
    (mixed / "context.json").write_text(json.dumps(grouped))
    monkeypatch.syspath_prepend(str(workbench.ASSETS))
    validated = importlib.import_module("contract").context(mixed)
    assert len(validated["assets"]) == 22 and len({a["id"] for a in validated["assets"]}) == 22
    for asset in validated["assets"]:
        assert asset["file"] == asset["id"] + ".webp"
        assert (
            asset["note"]
            == {"first": "", "ref": "red coat", "video": "slow camera", "second-video": "fast camera", "motion": "camera still pushing"}[
                asset["resource_id"]
            ]
        )
    assert grouped["keyframes"]["first"]["asset_id"] == mixed_assets[0]["id"] and grouped["keyframes"]["last"] is None
    assert grouped["motion"]["present"] and len(grouped["motion"]["stills"]) == 4
    assert grouped["duration_seconds"] == 145 / 24
    assert grouped["motion"]["delivered_duration_seconds"] == (145 - 22) / 24
    owner.release("active")
    assert not owner.cache
    with pytest.raises(ValueError, match="closed"):
        owner.create("w", "active", {}, {"w": {"inputs": {}}})
    assert not owner.agents.guard.locked()
