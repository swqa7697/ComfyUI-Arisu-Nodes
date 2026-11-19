"""Verify the SelfLift resolution transition with real Euler steps and small CPU latents."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

import comfy.latent_formats
import comfy.model_management
import comfy.model_patcher
import comfy.model_sampling
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview
import pytest
import torch
from comfy.nested_tensor import NestedTensor

from src.arisu_nodes.minimax_h3 import nodes as h3

pytestmark = pytest.mark.comfyui


class VideoVae:
    """Expose each frame as pixels and give the re-encoded anchor a distinct value."""

    device = torch.device("cpu")
    vae_dtype = torch.float32

    def decode(self, latent: torch.Tensor) -> torch.Tensor:
        return latent.movedim(1, -1)

    def encode(self, pixels: torch.Tensor) -> torch.Tensor:
        self.anchor = pixels.movedim(-1, 0).unsqueeze(0) + 0.1
        return self.anchor


def patcher(offset: float) -> comfy.model_patcher.ModelPatcher:
    model = torch.nn.Module()
    model.model_sampling = comfy.model_sampling.CONST()
    model.latent_format = comfy.latent_formats.MiniMaxH3AV()
    model.process_latent_out = model.latent_format.process_out
    model.offset = offset
    return comfy.model_patcher.ModelPatcher(model, VideoVae.device, VideoVae.device)


def test_progressive_euler_lifts_video_and_continues_audio(monkeypatch: pytest.MonkeyPatch):
    video = torch.linspace(-1, 1, 2 * 2 * 4 * 8).reshape(1, 2, 2, 4, 8)
    audio = torch.linspace(0, 1, 10).reshape(1, 1, 2, 5)
    mask = torch.ones(1, 4, 8)
    mask[:, :, :2] = 0
    keep = (mask == 0).expand_as(video)
    latent = {"samples": NestedTensor([video, audio]), "noise_mask": mask, "batch_index": [0]}
    keyframe = video[:, :, :1].clone()
    cond = [(None, {"minimax_keyframes": [{"latent": keyframe}]})]
    sigmas = torch.tensor([1.0, 0.75, 0.5, 0.25, 0.0])
    evaluations = []
    progress = []

    def outer_sample(
        guider: Any,
        noise: torch.Tensor,
        latent_image: torch.Tensor,
        sampler: Any,
        sigmas: torch.Tensor,
        denoise_mask: Any,
        callback: Callable[..., Any],
        disable_pbar: bool,
        seed: int,
        latent_shapes: List[torch.Size],
    ) -> torch.Tensor:
        # Replace the heavyweight model evaluation. ComfyUI still packs the streams,
        # installs the mask hooks, runs Euler and unpacks its callbacks and output.
        model = guider.model_patcher.model
        key = guider.conds["positive"][0]["minimax_keyframes"][0]["latent"]
        assert key.shape[-2:] == latent_shapes[0][-2:]
        torch.testing.assert_close(key.mean(dim=(-2, -1)), keyframe.mean(dim=(-2, -1)))

        def denoise(state: torch.Tensor, _sigma: torch.Tensor) -> torch.Tensor:
            prediction = state * 0.5 + model.offset
            for hook in guider.model_options.get("sampler_post_cfg_function", []):
                prediction = hook({"denoised": prediction})
            evaluations.append(
                (model.offset, comfy.utils.unpack_latents(state, latent_shapes), comfy.utils.unpack_latents(prediction, latent_shapes))
            )
            return prediction

        def report(step: Dict[str, Any]):
            callback(step["i"], step["denoised"], step["x"], len(sigmas) - 1)

        state = model.model_sampling.noise_scaling(sigmas[0], noise, latent_image)
        return sampler.sampler_function(denoise, state, sigmas, callback=report, disable=True)

    def preview(step: int, x0: NestedTensor, _x: NestedTensor, total: int):
        assert x0.unbind()[0].shape == video.shape
        progress.append((step, total))

    monkeypatch.setattr(comfy.samplers.CFGGuider, "outer_sample", outer_sample)
    monkeypatch.setattr(latent_preview, "prepare_callback", lambda *_args: preview)
    monkeypatch.setattr(comfy.model_management, "intermediate_device", lambda: VideoVae.device)
    monkeypatch.delenv("SELFLIFT_DEBUG", raising=False)
    vae = VideoVae()
    kwargs = {
        "model": patcher(0.1),
        "positive": cond,
        "negative": cond,
        "vae": vae,
        "latent_image": latent,
        "sampler": comfy.samplers.sampler_object("euler"),
        "sigmas": sigmas,
        "seed": (1 << 64) - 1,
        "cfg": 5.0,
        "transition_step": 2,
        "lowres_scale": 0.5,
        "rho": 0.5,
        "w_min": 1.0,
        "w_max": 1.0,
        "upscaler_model": "none",
        "model_hires": patcher(0.2),
    }
    sample = h3.ArisuMiniMaxH3SelfLiftProgressiveSampler.execute
    result = sample(**kwargs)[0]
    assert progress == [(0, 4), (1, 4), (2, 4), (3, 4)]
    assert [offset for offset, _, _ in evaluations] == [0.1, 0.1, 0.2, 0.2]
    _, (_, low_audio), (low_x0, audio_x0) = evaluations[1]
    _, (video_resume, audio_resume), _ = evaluations[2]
    assert low_x0.shape == (1, 2, 2, 2, 4)

    # Reconstruct the expected transition independently. The most inconsistent half of
    # the generate region receives the pixel anchor and the keep region keeps its source.
    direct = low_x0.repeat_interleave(2, dim=-1).repeat_interleave(2, dim=-2)
    risk = (vae.anchor - direct).abs().mean(dim=1, keepdim=True)
    selected = risk >= torch.quantile(risk[~keep[:, :1]], 0.5)
    corrected = torch.where(keep, video, torch.where(selected, vae.anchor, direct))
    transition_noise = comfy.sample.prepare_noise(video, 0, [0])
    torch.testing.assert_close(video_resume, 0.5 * corrected + 0.5 * transition_noise)
    torch.testing.assert_close(audio_resume, audio_x0 + (low_audio - audio_x0) * (0.5 / 0.75))
    final_video, final_audio = result["samples"].unbind()
    torch.testing.assert_close(final_video[keep], video[keep])
    assert final_audio.shape == audio.shape and result["noise_mask"] is mask and result["batch_index"] == [0]
    assert cond[0][1]["minimax_keyframes"][0]["latent"] is keyframe

    for overrides, error in [
        ({"rho": 0.0}, "rho"),
        ({"highres_tiling": True}, "noise_mask"),
        ({"transition_step": 4}, "transition_step"),
        ({"sampler": comfy.samplers.sampler_object("heun")}, "Euler"),
    ]:
        with pytest.raises(ValueError, match=error):
            sample(**(kwargs | overrides))
