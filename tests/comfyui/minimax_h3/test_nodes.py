"""Execute-level tests for the MiniMax H3 hybrid nodes with stub CLIP and VAEs.

The stubs return zero tensors of the right shapes, so these tests check the
conditioning payload (keys, ordering, dict shapes) and the latent geometry
without loading any model. Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest
import torch
from comfy_api.latest import io
from PIL import Image

from src.arisu_nodes.minimax_h3 import nodes as h3
from src.arisu_nodes.minimax_h3.core import EMPTY_RESOURCES, video_latent_t
from src.arisu_nodes.minimax_h3.media import StaleResource
from src.arisu_nodes.minimax_h3.nodes import ArisuMiniMaxH3HybridToVideo, ArisuMiniMaxH3HybridToVideoAdvanced
from tests.support.comfy import StubAudioVae, StubClip, StubVae, audio_input, image

pytestmark = pytest.mark.comfyui


def _base_kwargs() -> Dict[str, Any]:
    return {
        "clip": StubClip(),
        "vae": StubVae(),
        "prompt": "a test",
        "width": 1344,
        "height": 768,
        "length": 124,
        "ref_image_size": "match",
        "frame_picture_tags": "after_refs",
    }


def _run(**overrides: Any) -> Tuple[Any, io.NodeOutput]:
    kwargs = _base_kwargs()
    kwargs.update(overrides)
    return kwargs["clip"], ArisuMiniMaxH3HybridToVideo.execute(**kwargs)


def _run_advanced(**overrides: Any) -> Tuple[Dict[str, Any], io.NodeOutput]:
    kwargs = _base_kwargs()
    kwargs.update({"target_width": 2688, "target_height": 1536})
    kwargs.update(overrides)
    return kwargs, ArisuMiniMaxH3HybridToVideoAdvanced.execute(**kwargs)


def _cond_values(result: Any, index: int = 0) -> Dict[str, Any]:
    cond = result[index]
    assert len(cond) == 1
    return cond[0][1]


def test_first_and_last_frames_only_pin_keyframes():
    clip, result = _run(first_frame=image(768, 1344), last_frame=image(1080, 1920), frame_picture_tags="none")

    values = _cond_values(result)
    assert [kf["resolved_frame_index"] for kf in values["minimax_keyframes"]] == [0, 123]
    for kf in values["minimax_keyframes"]:
        assert kf["latent"].shape == (1, 24, 1, 48, 84)
        assert "image" not in kf
    assert "minimax_refs" not in values
    assert clip.tokenize_kwargs == {"minimax_ref_items": []}

    samples = result[1]["samples"]
    assert samples.is_nested
    assert tuple(samples.tensors[0].shape) == (1, 24, 37, 48, 84)
    assert tuple(samples.tensors[1].shape) == (1, 32, 2, 207)


def test_frame_picture_tags_order_frames_around_references():
    first = image(768, 1344)
    ref_images = {"ref_image_0": image(512, 512), "ref_image_1": image(256, 1024)}
    clip, result = _run(first_frame=first, ref_images=ref_images, frame_picture_tags="after_refs")

    items = clip.tokenize_kwargs["minimax_ref_items"]
    assert [item["type"] for item in items] == ["image", "image", "image"]
    assert [tuple(item["data"].shape) for item in items] == [(1, 512, 512, 3), (1, 256, 1024, 3), (1, 768, 1344, 3)]

    values = _cond_values(result)
    refs = values["minimax_refs"]
    # frames never add reference blocks; they reach the model as keyframes only
    assert [ref["kind"] for ref in refs] == ["image", "image"]
    assert (refs[0]["latent_h"], refs[0]["latent_w"]) == (32, 32)
    assert (refs[1]["latent_h"], refs[1]["latent_w"]) == (16, 64)
    assert len(values["minimax_keyframes"]) == 1

    # "before_refs" numbers the frames first
    clip, _result = _run(first_frame=first, ref_images={"ref_image_0": image(512, 512)}, frame_picture_tags="before_refs")
    items = clip.tokenize_kwargs["minimax_ref_items"]
    assert [tuple(item["data"].shape) for item in items] == [(1, 768, 1344, 3), (1, 512, 512, 3)]


def test_ref_video_with_soundtrack_and_standalone_audio():
    clip, result = _run(
        audio_vae=StubAudioVae(),
        ref_videos={"ref_video_0": torch.rand(30, 360, 640, 3)},
        ref_video_audios={"ref_video_audio_0": audio_input()},
        ref_audios={"ref_audio_0": audio_input()},
    )

    items = clip.tokenize_kwargs["minimax_ref_items"]
    # soundtrack label before its video, standalone audio last
    assert [item["type"] for item in items] == ["audio", "video", "audio"]
    assert tuple(items[1]["data"].shape) == (2, 352, 640, 3)
    assert items[1]["timestamps"] == [0.0, 0.5]

    refs = _cond_values(result)["minimax_refs"]
    assert [ref["kind"] for ref in refs] == ["video_audio", "audio"]
    assert refs[0]["latent_t"] == video_latent_t(22)
    assert (refs[0]["latent_h"], refs[0]["latent_w"], refs[0]["ref_audio_t"]) == (22, 40, 40)
    assert "latent" not in refs[1]
    assert refs[1]["ref_audio_t"] == 40


def test_hybrid_rejects_missing_audio_vae_and_short_reference_videos():
    with pytest.raises(ValueError, match="audio_vae"):
        _run(ref_audios={"ref_audio_0": audio_input()})
    with pytest.raises(ValueError, match="at least 5 frames"):
        _run(ref_videos={"ref_video_0": torch.rand(3, 360, 640, 3)})


def test_matching_frames_are_not_resampled():
    # a frame already on the canvas goes to the VAE untouched (minus alpha); lanczos would quantize it
    kwargs = _base_kwargs()
    first = image(768, 1344, channels=4)
    result = ArisuMiniMaxH3HybridToVideo.execute(first_frame=first, **kwargs)

    assert _cond_values(result)["minimax_keyframes"][0]["latent"].shape == (1, 24, 1, 48, 84)
    assert torch.equal(kwargs["vae"].encoded[0], first[..., :3])


def test_advanced_encodes_keyframes_on_both_canvases_and_collapses_an_equal_target():
    first = image(768, 1344, channels=4)  # already on the generation canvas
    last = image(1536, 2688)  # already on the target canvas
    kwargs, result = _run_advanced(first_frame=first, last_frame=last, ref_images={"ref_image_0": image(512, 512)})
    vae: StubVae = kwargs["vae"]
    clip: StubClip = kwargs["clip"]

    positive, latent, upscaled = result
    assert upscaled is not positive
    assert positive[0][0] is upscaled[0][0]
    # a 512px reference is never upscaled under "match", so both passes share its block
    assert positive[0][1]["minimax_refs"][0] is upscaled[0][1]["minimax_refs"][0]
    assert tuple(latent["samples"].tensors[0].shape) == (1, 24, 37, 48, 84)

    base_kfs, target_kfs = positive[0][1]["minimax_keyframes"], upscaled[0][1]["minimax_keyframes"]
    assert [kf["resolved_frame_index"] for kf in base_kfs] == [0, 123]
    assert [kf["resolved_frame_index"] for kf in target_kfs] == [0, 123]
    assert all(kf["latent"].shape == (1, 24, 1, 48, 84) for kf in base_kfs)
    assert all(kf["latent"].shape == (1, 24, 1, 96, 168) for kf in target_kfs)

    # the text encoder only sees the generation-canvas frames
    items = clip.tokenize_kwargs["minimax_ref_items"]
    assert [tuple(item["data"].shape) for item in items] == [(1, 512, 512, 3), (1, 768, 1344, 3), (1, 768, 1344, 3)]

    # encode order: reference, then both keyframes per canvas; matching sizes bypass the resize
    assert len(vae.encoded) == 5
    assert torch.equal(vae.encoded[1], first[..., :3])
    assert tuple(vae.encoded[2].shape) == (1, 768, 1344, 3)
    assert tuple(vae.encoded[3].shape) == (1, 1536, 2688, 3)
    assert torch.equal(vae.encoded[4], last)

    # an equal target collapses to one conditioning and one pass through the VAE
    kwargs, result = _run_advanced(first_frame=image(768, 1344), last_frame=image(768, 1344), target_width=1344, target_height=768)
    positive, _latent, upscaled = result
    assert upscaled is positive
    assert len(kwargs["vae"].encoded) == 2


def test_advanced_sizes_a_large_reference_per_canvas_under_match_and_shares_it_under_max():
    kwargs, result = _run_advanced(ref_images={"ref_image_0": image(2048, 4096)})
    positive, _latent, upscaled = result

    base_ref, target_ref = positive[0][1]["minimax_refs"][0], upscaled[0][1]["minimax_refs"][0]
    assert (base_ref["latent_h"], base_ref["latent_w"]) == (44, 90)
    assert (target_ref["latent_h"], target_ref["latent_w"]) == (90, 180)
    assert [tuple(px.shape) for px in kwargs["vae"].encoded] == [(1, 704, 1440, 3), (1, 1440, 2880, 3)]
    # the text encoder sees the reference at the generation size only
    items = kwargs["clip"].tokenize_kwargs["minimax_ref_items"]
    assert [tuple(item["data"].shape) for item in items] == [(1, 704, 1440, 3)]

    # "max" sizes the reference once for both canvases, so both passes share its block
    kwargs, result = _run_advanced(ref_images={"ref_image_0": image(2048, 4096)}, ref_image_size="max")
    positive, _latent, upscaled = result
    assert positive[0][1]["minimax_refs"][0] is upscaled[0][1]["minimax_refs"][0]
    assert len(kwargs["vae"].encoded) == 1


def test_studio_bundles_originals_and_rejects_invalid_or_conflicting_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(h3, "_resource_roots", lambda: {"input": str(tmp_path)})
    Image.new("RGB", (81, 61), "red").save(tmp_path / "frame.png")
    state = json.loads(EMPTY_RESOURCES)
    first = {"id": "first", "kind": "image", "root": "input", "path": "frame.png", "muted": False, "crop": None, "crop_basis_ratio": None}
    state["keyframes"]["first"] = first
    state["references"] = [
        {"id": "missing", "kind": "image", "root": "input", "path": "missing.png", "muted": True, "crop": None},
        {"id": "ref", "kind": "image", "root": "input", "path": "frame.png", "muted": False, "crop": None},
    ]
    studio = h3.ArisuMiniMaxH3ResourceStudio
    text = json.dumps(state)
    result = studio.execute("16:9 (Widescreen)", False, text)
    bundle = result[0]
    assert bundle.first.crop == (0, 8, 81, 45)
    assert [item.id for item in bundle.images] == ["ref"]
    assert not hasattr(bundle.first, "tensor")
    clip, output = _run(resources=bundle, width=64, height=64)
    assert len(_cond_values(output)["minimax_refs"]) == 1
    assert len(clip.tokenize_kwargs["minimax_ref_items"]) == 2
    with pytest.raises(ValueError, match="combined"):
        _run(resources=bundle, first_frame=image(32, 32))
    # Ratio changes replace manual crops; repeating a ratio retains them.
    first.update(crop={"left": 1, "top": 2, "width": 10, "height": 9}, crop_basis_ratio="16:9 (Widescreen)")
    assert studio.execute("16:9 (Widescreen)", False, json.dumps(state))[0].first.crop == (1, 2, 10, 9)
    assert studio.execute("1:1 (Square)", False, json.dumps(state))[0].first.crop == (10, 0, 61, 61)
    for label, expected in (("2:3 (Portrait Photo)", (20, 0, 40, 61)), ("21:9 (Ultrawide)", (0, 13, 81, 34))):
        assert studio.execute(label, False, json.dumps(state))[0].first.crop == expected
    # Muted contents do not participate in filesystem fingerprinting.
    before = studio.fingerprint_inputs(text, "16:9 (Widescreen)")
    (tmp_path / "missing.png").write_bytes(b"not an image")
    assert studio.fingerprint_inputs(text, "16:9 (Widescreen)") == before
    Image.new("RGB", (81, 61), "blue").save(tmp_path / "frame.png")
    assert studio.fingerprint_inputs(text, "16:9 (Widescreen)") != before
    with pytest.raises(StaleResource):
        _run(resources=bundle)
    empty = studio.execute("16:9 (Widescreen)", False, EMPTY_RESOURCES)[0]
    assert not empty.sources()
    assert "minimax_refs" not in _cond_values(_run(resources=empty)[1])
    # Persisted version, duplicate identity, path syntax and active capacities are validated independently.
    for invalid in (
        {**state, "version": 2},
        {**state, "references": [state["references"][1]] * 10},
        {**state, "references": [{**state["references"][1], "path": "../outside.png"}]},
        {**state, "references": [{**state["references"][1], "id": str(i)} for i in range(10)]},
    ):
        with pytest.raises(ValueError):
            studio.execute("16:9 (Widescreen)", False, json.dumps(invalid))
