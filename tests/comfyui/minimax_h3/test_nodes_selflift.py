"""Verify the SelfLift resolution transition with real Euler steps and small CPU latents."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

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
from comfy.ldm.minimax.model import PackedLayout
from comfy.nested_tensor import NestedTensor

from src.arisu_nodes.minimax_h3 import nodes as h3
from src.arisu_nodes.minimax_h3 import selflift_tiling

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

    # The outer-sampler double above exercises the transition. Drive the high-resolution
    # diffusion wrapper separately to inspect the conditioning actually seen by each tile.
    check_motion_context_tiles()


def check_motion_context_tiles():
    width = 13
    video = torch.arange(width, dtype=torch.float32).expand(1, 2, 3, 4, width).clone()
    audio = torch.linspace(-1, 1, 12).reshape(1, 1, 2, 6)
    context = torch.zeros(1, 2, 8)
    anchor = video[:, :, :1] + 10
    guide_audio, pinned_audio = audio[..., :2], audio[..., -3:]
    keyframes = [
        {"resolved_frame_index": 3, "latent": anchor, "audio_latent": guide_audio},
        {"resolved_frame_index": -2.4, "audio_latent": pinned_audio},
    ]
    ref_video, ref_audio = anchor[..., :2, :4], audio[..., :1]
    refs = [
        {
            "kind": "video_audio",
            "latent": ref_video,
            "latent_t": 1,
            "latent_h": 2,
            "latent_w": 4,
            "audio_latent": ref_audio,
            "ref_audio_t": 1,
        }
    ]
    full_layout = PackedLayout(2, 3, 4, 14, 6, keyframes=keyframes, refs=refs)
    payload = {
        "layout": full_layout,
        "keyframes": keyframes,
        "refs": refs,
        "cond_video_latents": [anchor, ref_video],
        "cond_audio_latents": [guide_audio, pinned_audio, ref_audio],
    }
    # Only the visual anchor shrinks with a tile. Audio guides and references still
    # need their full allocation, including keyframes that carry both modalities.
    elements = selflift_tiling._condition_elements({"minimax_keyframes": keyframes, "minimax_refs": refs}, 4, 8, 2)
    assert elements == 2 * 4 * 8 + guide_audio.numel() + pinned_audio.numel() + ref_video.numel() + ref_audio.numel()

    def predict(
        streams: Sequence[torch.Tensor],
        _time: torch.Tensor,
        _context: torch.Tensor,
        _options: Dict[str, Any],
        minimax_payload: Dict[str, Any],
    ) -> List[torch.Tensor]:
        tile, sound = streams
        start = int(tile[0, 0, 0, 0, 0])
        end = start + tile.shape[-1]
        if tile.shape == video.shape:
            assert minimax_payload is payload
        else:
            visual, ref = minimax_payload["cond_video_latents"]
            torch.testing.assert_close(visual[..., : end - start], anchor[..., start:end])
            assert ref is ref_video
            for actual, expected in zip(minimax_payload["cond_audio_latents"], (guide_audio, pinned_audio, ref_audio), strict=True):
                torch.testing.assert_close(actual, expected)
            layout = minimax_payload["layout"]
            for (a, b, kind), (fa, fb, full_kind) in zip(layout.segments, full_layout.segments, strict=True):
                assert kind == full_kind
                expected = full_layout.position_ids[fa:fb]
                if kind in ("cond", "video"):
                    expected = expected.reshape(-1, 2, 7, 3)[:, :, start // 2 : (end + 1) // 2].reshape(-1, 3)
                torch.testing.assert_close(layout.position_ids[a:b], expected)
        torch.testing.assert_close(sound, audio)
        return [tile + start, sound + start]

    args = (predict, [video, audio], torch.tensor(0.5), context, {})
    single_video, single_audio = selflift_tiling._tiled_forward(*args, minimax_payload=payload, n_tiles=1)
    torch.testing.assert_close(single_video, video)
    torch.testing.assert_close(single_audio, audio)
    joined_video, joined_audio = selflift_tiling._tiled_forward(*args, minimax_payload=payload, n_tiles=2)
    # The tiles span [0, 8) and [4, 13). The four shared cells feather the
    # second prediction in; the unmatched right edge belongs entirely to it.
    offset = torch.tensor([0, 0, 0, 0, 0.5, 1.5, 2.5, 3.5, 4, 4, 4, 4, 4])
    torch.testing.assert_close(joined_video, video + offset)
    torch.testing.assert_close(joined_audio, audio + offset.mean())
