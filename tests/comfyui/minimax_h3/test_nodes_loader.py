"""Grouped loader scenarios: bounded preflight, then native storage and reload lifecycle."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import struct
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

import comfy.model_patcher
import pytest
import torch
from comfy_api.latest import _io
from safetensors.torch import save_file

from src.arisu_nodes.minimax_h3 import nodes as h3
from src.arisu_nodes.minimax_h3.core import H3Plan, H3Source, h3_header, h3_plan

pytestmark = pytest.mark.comfyui


def checkpoint(path: Path, pruned: bool = False, metadata: Optional[Dict[str, str]] = None) -> h3.H3Source:
    """Write a sparse, canonical header fixture; never materialize the large weights."""
    hidden, width = 5376, 8 if pruned else 2688
    shapes = {
        "video_patch_proj.weight": (hidden, 96),
        "video_patch_proj.bias": (hidden,),
        "audio_patch_proj.weight": (hidden, 32),
        "audio_patch_proj.bias": (hidden,),
        "condition_proj.weight": (hidden, 5120),
        "condition_proj.bias": (hidden,),
        "final_layer.video_out.weight": (96, hidden),
        "final_layer.video_out.bias": (96,),
        "final_layer.audio_out.weight": (32, hidden),
        "final_layer.audio_out.bias": (32,),
        "final_layer.norm.weight": (hidden,),
        "token_refiner.final_norm.weight": (hidden,),
        "rope.inv_freq": (16,),
        "final_layer.adaln_proj.linear.weight": (hidden * 2, width),
        "final_layer.adaln_proj.linear.bias": (hidden * 2,),
    }
    for prefix in [f"blocks.{i}" for i in range(50)] + [f"token_refiner.blocks.{i}" for i in range(2)]:
        for suffix, dims in {
            "attn.q_norm.weight": (128,),
            "attn.k_norm.weight": (128,),
            "attn.qkv_proj.weight": (21504, hidden),
            "attn.out_proj.weight": (hidden, 7168),
            "mlp.fc1.weight": (28672, hidden),
            "mlp.fc2.weight": (hidden, 14336),
            "norm1.weight": (hidden,),
            "norm2.weight": (hidden,),
        }.items():
            shapes[f"{prefix}.{suffix}"] = dims
        if prefix.startswith("blocks."):
            shapes[prefix + ".adaln_proj.linear.weight"] = (hidden * 18, width)
            shapes[prefix + ".adaln_proj.linear.bias"] = (hidden * 18,)
    if pruned:
        shapes["adaln_t_table"] = (1025, 8)
    else:
        shapes.update(
            {
                "time_embedder.proj_in.weight": (hidden, 256),
                "time_embedder.proj_in.bias": (hidden,),
                "time_embedder.proj_out.weight": (width, hidden),
                "time_embedder.proj_out.bias": (width,),
            }
        )
    header: Dict[str, Any] = {"__metadata__": metadata or {}}
    offset = 0
    for key, shape in shapes.items():
        length = 4 if key == "adaln_t_table" else 2
        for dim in shape:
            length *= dim
        header[key] = {"dtype": "F32" if key == "adaln_t_table" else "BF16", "shape": shape, "data_offsets": [offset, offset + length]}
        offset += length
    raw = json.dumps(header).encode()
    raw += b" " * (-len(raw) % 8)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(raw)))
        stream.write(raw)
        stream.truncate(8 + len(raw) + offset)
    return h3.read_h3_source(str(path))


def hybrid_mode(**kwargs: Any) -> Dict[str, Any]:
    return {
        "mode": "hybrid",
        "overlay_model": "overlay.safetensors",
        "block_start": 25,
        "block_end": 49,
        "include_final_adaln": False,
        **kwargs,
    }


def test_loader_preflight_and_active_branch_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = checkpoint(tmp_path / "base.safetensors")
    overlay = checkpoint(tmp_path / "overlay.safetensors", metadata={"description": "different descriptive metadata"})
    pruned = checkpoint(tmp_path / "pruned.sft", pruned=True)
    inventory = {"base.safetensors": base.path, "overlay.safetensors": overlay.path, "pruned.sft": pruned.path}
    monkeypatch.setattr(h3.folder_paths, "get_filename_list", lambda _name: list(inventory))
    monkeypatch.setattr(h3.folder_paths, "get_full_path", lambda _kind, name: inventory.get(name))
    native = object()
    monkeypatch.setattr(h3.comfy.sd, "load_diffusion_model", lambda *args, **kwargs: native)
    # Missing inactive overlay and malformed hidden controls do not participate in
    # resolution, fingerprinting, or execution. The native patcher/factory is untouched.
    inactive = {"mode": "native", "overlay_model": "missing", "block_start": False, "include_final_adaln": "bad"}
    # Reconstruct the flattened keys observed in the real frontend API export.
    for branch in ("native", "hybrid"):
        exported = {"base_model": "base.safetensors", "weight_dtype": "default", "mode": branch}
        if branch == "hybrid":
            exported.update({"mode." + k: v for k, v in hybrid_mode().items() if k != "mode"})
        inputs, _hidden, dynamic = _io.get_finalized_class_inputs(h3.ArisuMiniMaxH3Loader.INPUT_TYPES(), exported)
        assert set(inputs["required"]) == set(exported)
        nested = _io.build_nested_inputs(exported, dynamic)
        assert nested["mode"] == (hybrid_mode() if branch == "hybrid" else {"mode": "native"})
        assert h3.h3_selection(nested["mode"], nested["weight_dtype"])[0] == branch
    assert h3.ArisuMiniMaxH3Loader.execute("base.safetensors", "default", inactive)[0] is native
    assert h3.ArisuMiniMaxH3Loader.fingerprint_inputs(
        "base.safetensors", "default", inactive
    ) == h3.ArisuMiniMaxH3Loader.fingerprint_inputs("base.safetensors", "default", {"mode": "native"})
    for change in (
        {"block_start": True},
        {"block_end": 49.5},
        {"block_start": -1},
        {"block_end": 50},
        {"block_start": 49, "block_end": 25},
        {"include_final_adaln": 1},
        {"mode": "Auto"},
        {"overlay_model": "missing"},
    ):
        with pytest.raises(ValueError):
            h3.ArisuMiniMaxH3Loader.execute("base.safetensors", "default", hybrid_mode(**change))
    for name in ("../base.safetensors", base.path, "~base", "missing"):
        with pytest.raises(ValueError):
            h3.ArisuMiniMaxH3Loader.execute(name, "default", inactive)
    with pytest.raises(ValueError, match="weight_dtype"):
        h3.ArisuMiniMaxH3Loader.execute("base.safetensors", "invalid", inactive)
    for start, end, final in ((45, 49, False), (25, 49, False), (0, 49, False), (17, 17, False), (17, 17, True)):
        plan = h3_plan(base, overlay, start, end, final, "default")
        expected = {f"blocks.{i}.adaln_proj.linear.{suffix}" for i in range(start, end + 1) for suffix in ("weight", "bias")}
        if final:
            expected.update({"final_layer.adaln_proj.linear.weight", "final_layer.adaln_proj.linear.bias"})
        assert {key for family in plan.families for key in family} == expected
        assert plan.overlay_bytes == sum(t.end - t.start for t in overlay.tensors if t.name in expected)
        assert plan == h3_plan(base, overlay, start, end, final, "default")
    with pytest.raises(ValueError, match="representation mismatch"):
        h3_plan(base, pruned, 0, 49, False, "default")
    # Pruned curves may differ numerically. A single nonfinite value is refused.
    other = checkpoint(tmp_path / "other.sft", pruned=True)
    table = next(t for t in other.tensors if t.name == "adaln_t_table")
    with open(other.path, "r+b") as stream:
        stream.seek(other.data_start + table.start)
        stream.write(struct.pack("<f", 0.125))
    other = h3.read_h3_source(other.path)
    assert h3_plan(pruned, other, 25, 49, False, "default").overlay_bytes == 25 * 96768 * 9 * 2
    with open(other.path, "r+b") as stream:
        stream.seek(other.data_start + table.start)
        stream.write(struct.pack("<f", float("nan")))
    with pytest.raises(ValueError, match="finite"):
        h3.read_h3_source(other.path)
    # Declared baked models remain eligible for Native but never composition.
    baked = checkpoint(tmp_path / "baked.sft", pruned=True, metadata={"minimax_h3_delta": "baked"})
    for invalid, message in (
        (baked, "pre-composed"),
        (replace(pruned, metadata=(("_quantization_metadata", '{"layers":{}}'),)), "quantized"),
    ):
        with pytest.raises(ValueError, match=message):
            h3_plan(pruned, invalid, 25, 49, False, "default")
    changed = tuple(replace(t, dtype="F16") if t.name == "blocks.25.adaln_proj.linear.bias" else t for t in overlay.tensors)
    with pytest.raises(ValueError, match="dtype mismatch"):
        h3_plan(base, replace(overlay, tensors=changed), 25, 49, False, "default")
    for metadata in (
        {"config": '{"transformer":{"hidden_size":5}}'},
        {"config": '{"transformer":{"gate_compress":true}}'},
        {"config": '{"transformer":[]}'},
        {"config": '{"transformer":{"norm_eps":1e999}}'},
        {"_quantization_metadata": '{"layers":[]}'},
        {"_quantization_metadata": '{"layers":{"blocks.25.adaln_proj.linear":{}}}'},
    ):
        with pytest.raises(ValueError):
            checkpoint(tmp_path / "invalid.sft", metadata=metadata)
    # Header boundaries are checked before any official tensor reader runs.
    good = {"a": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    malformed = [b'{"a":{},"a":{}}', b"[]", b"{", json.dumps({**good, "__metadata__": {"bad": 1}}).encode()]
    for field, value in (("shape", [True]), ("shape", [-1]), ("shape", [2]), ("data_offsets", [-1, 3]), ("dtype", "unknown")):
        malformed.append(json.dumps({"a": {**good["a"], field: value}}).encode())
    malformed.append(json.dumps({**good, "b": good["a"]}).encode())
    for raw in malformed:
        with pytest.raises(ValueError):
            h3_header(raw, 4)
    for raw in (b"", struct.pack("<Q", 2**30), struct.pack("<Q", 100) + b"{}"):
        path = tmp_path / "truncated.sft"
        path.write_bytes(raw)
        with pytest.raises(ValueError):
            h3.read_h3_source(str(path))
    # Canonical aliases refer to the same source, while changed files invalidate plans.
    alias = tmp_path / "alias.safetensors"
    alias.symlink_to(base.path)
    inventory[alias.name] = str(alias)
    assert h3._resolve_h3(alias.name, "overlay") == base
    original = h3_plan(base, overlay, 17, 17, False, "default")
    os.utime(overlay.path, ns=(0, overlay.identity[3] + 1))
    with pytest.raises(ValueError, match="changed"):
        h3.load_h3_hybrid(original)


def tiny_source(path: Path, value: float) -> H3Source:
    tensors = {
        "kept.weight": torch.full((2, 2), float(value)),
        "blocks.17.adaln_proj.linear.weight": torch.full((2, 2), float(value)),
        "blocks.17.adaln_proj.linear.bias": torch.full((2,), float(value)),
        "final_layer.adaln_proj.linear.weight": torch.full((2, 2), float(value)),
    }
    save_file(tensors, str(path), metadata={"description": "tiny lifecycle fixture"})
    raw, identity = h3._h3_header_bytes(str(path))
    entries, metadata = h3_header(raw, identity[2] - 8 - len(raw))
    return H3Source(str(path), identity, hashlib.sha256(raw).hexdigest(), 8 + len(raw), entries, metadata, "full", "tiny fixture")


def test_loader_native_storage_composition_and_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base, overlay = tiny_source(tmp_path / "base.sft", 1), tiny_source(tmp_path / "overlay.sft", 2)
    keys = ("blocks.17.adaln_proj.linear.bias", "blocks.17.adaln_proj.linear.weight")
    plan = H3Plan(base, overlay, (keys,), 17, 17, False, "default", 24, "tiny-storage-plan")
    tensors_seen: Dict[str, torch.Tensor] = {}
    readers = h3.comfy.utils.load_torch_file
    weak_tensors = []

    def native_reader(path: str, **kwargs: Any) -> Any:
        result = readers(path, **kwargs)
        state = result[0] if kwargs.get("return_metadata") else result
        tensors_seen.update({("base:" if path == base.path else "overlay:") + k: t for k, t in state.items()})
        weak_tensors.extend(weakref.ref(t) for t in state.values())
        return result

    def construct(state: Dict[str, torch.Tensor], **kwargs: Any) -> comfy.model_patcher.ModelPatcher:
        # Real torch assignment + real ModelPatcher, without a full 60 GiB H3.
        model = torch.nn.ParameterDict(
            {k.replace(".", "_"): torch.nn.Parameter(torch.empty_like(t, device="meta")) for k, t in state.items()}
        )
        model.load_state_dict({k.replace(".", "_"): t for k, t in state.items()}, assign=True)
        assert kwargs["metadata"]["description"] == "tiny lifecycle fixture"
        return comfy.model_patcher.ModelPatcher(model, torch.device("cpu"), torch.device("cpu"))

    def prohibited(*args: Any, **kwargs: Any):
        pytest.fail("loader must not evict unrelated models or initialize AIMDO")

    monkeypatch.setattr(h3.comfy.utils, "load_torch_file", native_reader)
    monkeypatch.setattr(h3.comfy.sd, "load_diffusion_model_state_dict", construct)
    monkeypatch.setattr(h3.comfy.model_management, "unload_all_models", prohibited)
    monkeypatch.setattr(h3.comfy.memory_management, "aimdo_enabled", False)
    for no_mmap in (False, True):
        tensors_seen.clear()
        monkeypatch.setattr(h3.comfy.utils, "DISABLE_MMAP", no_mmap)
        loaded = h3.load_h3_hybrid(plan)
        state = loaded.model
        assert torch.equal(state["kept_weight"], torch.ones(2, 2))
        assert torch.equal(state["blocks_17_adaln_proj_linear_weight"], torch.full((2, 2), 2.0))
        assert torch.equal(state["blocks_17_adaln_proj_linear_bias"], torch.full((2,), 2.0))
        assert torch.equal(state["final_layer_adaln_proj_linear_weight"], torch.ones(2, 2))
        assert state["kept_weight"].untyped_storage() is tensors_seen["base:kept.weight"].untyped_storage()
        if not no_mmap:
            assert state["blocks_17_adaln_proj_linear_weight"].untyped_storage() is tensors_seen["overlay:" + keys[1]].untyped_storage()
        assert state["blocks_17_adaln_proj_linear_weight"].untyped_storage()._comfy_source_path == overlay.path
        tensors_seen.clear()
        gc.collect()
        assert float(state["blocks_17_adaln_proj_linear_weight"].detach().sum()) == 8
        clone = loaded.clone()
        assert clone.model is loaded.model
        factory, args = loaded.cached_patcher_init
        rebuilt = factory(*args, disable_dynamic=True)
        assert rebuilt.model is not loaded.model
        assert torch.equal(rebuilt.model["blocks_17_adaln_proj_linear_weight"], state["blocks_17_adaln_proj_linear_weight"])
        # Exercise the real delegate callback path, including keyword binding.
        monkeypatch.setattr(loaded, "is_dynamic", lambda: True)
        delegate = loaded.clone(disable_dynamic=True)
        assert delegate.model is not loaded.model
        deep = rebuilt.deepclone_multigpu(new_load_device=torch.device("cpu"))
        assert deep.model is not rebuilt.model
        assert torch.equal(deep.model["blocks_17_adaln_proj_linear_weight"], state["blocks_17_adaln_proj_linear_weight"])
        del loaded, state, clone, rebuilt, delegate, deep
    # Native construction failures and interruption release this invocation's tensors.
    tensors_seen.clear()
    weak_tensors.clear()
    monkeypatch.setattr(h3.comfy.sd, "load_diffusion_model_state_dict", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="detection failed"):
        h3.load_h3_hybrid(plan)
    tensors_seen.clear()
    gc.collect()
    assert all(ref() is None for ref in weak_tensors)
    calls = 0

    def interrupt():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise h3.comfy.model_management.InterruptProcessingException()

    monkeypatch.setattr(h3.comfy.model_management, "throw_exception_if_processing_interrupted", interrupt)
    with pytest.raises(h3.comfy.model_management.InterruptProcessingException):
        h3.load_h3_hybrid(plan)
    tensors_seen.clear()
    gc.collect()
    assert all(ref() is None for ref in weak_tensors)
    # Even an equal-sized replacement cannot silently alter a cached Hybrid.
    replacement = tiny_source(tmp_path / "replacement.sft", 9)
    os.replace(replacement.path, overlay.path)
    with pytest.raises(ValueError, match="changed"):
        h3.load_h3_hybrid(plan)
