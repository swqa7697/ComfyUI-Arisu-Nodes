"""Regression flow: the pack loads the way ComfyUI loads it.

Nothing else verifies that the node pack imports until a clone is dropped into
a live ComfyUI and the service restarted, so this lane is the early warning.
Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import folder_paths
import pytest
import torch
from comfy_api.latest import ComfyExtension

from tests.support.comfy import StubAudioVae

pytestmark = pytest.mark.comfyui

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_NODE_IDS = [
    "ArisuMiniMaxH3ModelLoader",
    "ArisuMiniMaxH3PromptWorkbench",
    "ArisuMiniMaxH3ResourceStudio",
    "ArisuMiniMaxH3HybridToVideo",
    "ArisuMiniMaxH3HybridToVideoAdvanced",
    "ArisuMiniMaxH3VideoSettings",
    "ArisuMiniMaxH3VideoSettingsUpscale",
    "ArisuPathBuilder",
    "ArisuExtractLastImages",
    "ArisuPreviewSaveImage",
    "ArisuPreviewSaveImageUpscale",
    "ArisuLoadImage",
    "ArisuResizeImage",
]


def load_pack(name: str) -> ModuleType:
    """Import the repo root as a package exactly like ComfyUI's ``load_custom_node``.

    ComfyUI never puts the pack on ``sys.path``; it builds a spec from the
    directory's ``__init__.py`` under a module name derived from the path, so
    the entry file's relative imports (``from .src... import``) must work that
    way.
    """
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pack() -> ModuleType:
    return load_pack(str(REPO_ROOT).replace(".", "_x_"))


def test_pack_loads_like_comfyui(pack: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    extension = asyncio.run(pack.comfy_entrypoint())
    assert isinstance(extension, ComfyExtension)
    # Startup must honor the configured user directory without touching the live install.
    monkeypatch.setattr(folder_paths, "user_directory", str(tmp_path))
    monkeypatch.setattr(pack.PromptServer, "instance", None, raising=False)
    monkeypatch.setattr(sys.modules[pack.initialize_roots.__module__], "_roots", None)
    asyncio.run(extension.on_load())
    config = tmp_path / "__arisu_nodes" / "config.arisu.jsonc"
    assert config.is_file()
    original = config.read_bytes()
    skills = config.parent / "skills"
    assert skills.is_dir() and not list(skills.iterdir())
    custom = skills / "my-skill"
    custom.mkdir()
    definition = custom / "SKILL.md"
    definition.write_text("Keep my custom skill")
    monkeypatch.setattr(sys.modules[pack.initialize_roots.__module__], "_roots", None)
    asyncio.run(extension.on_load())
    assert config.read_bytes() == original
    assert definition.read_text() == "Keep my custom skill"

    nodes = asyncio.run(extension.get_node_list())
    # Browser fixtures must describe the same nodes that the real loader registers.
    browser_definitions = json.loads((REPO_ROOT / "tests/browser/fixtures/object_info.json").read_text())
    # Browser fixtures have no host model inventory.
    monkeypatch.setattr(folder_paths, "get_filename_list", lambda _name: [])
    assert set(browser_definitions) == set(EXPECTED_NODE_IDS)
    for node in nodes:
        info = node.GET_NODE_INFO_V1()
        # ComfyUI assigns this during registration; the fixture uses a portable module name.
        info["python_module"] = "custom_nodes.arisu"
        assert json.loads(json.dumps(info)) == browser_definitions[info["name"]]

    # GET_SCHEMA is what ComfyUI calls at startup: it checks that define_schema
    # and execute are overridden and that input/output ids are unique.
    schemas = [node.GET_SCHEMA() for node in nodes]
    assert [schema.node_id for schema in schemas] == EXPECTED_NODE_IDS

    # V3 passes inputs to execute as keyword arguments named by input id, so a
    # mismatch only surfaces as a TypeError once a workflow runs.
    for node, schema in zip(nodes, schemas):
        assert {i.id for i in schema.inputs} == set(inspect.signature(node.execute).parameters), schema.node_id

    # Every node ships a help page under the docs contract path.
    for schema in schemas:
        assert (REPO_ROOT / "web" / "docs" / schema.node_id / "en.md").is_file(), schema.node_id

    # The loader resolves WEB_DIRECTORY relative to the pack and silently skips
    # a missing directory.
    web_root = REPO_ROOT / pack.WEB_DIRECTORY
    assert web_root.is_dir()

    # The directory is served at /extensions/<pack dir>/, and the browser resolves
    # each script's relative imports against that URL: they must land on the
    # frontend core under /scripts/ or on a file in the directory. A miss is only
    # a console error in the browser, and the whole script is skipped.
    prefix = f"/extensions/{REPO_ROOT.name}/"
    for script in sorted(web_root.glob("js/**/*.js")):
        served = f"http://comfy{prefix}{script.relative_to(web_root).as_posix()}"
        for spec in re.findall(r"^import .+ from ['\"]([^'\"]+)['\"];$", script.read_text(encoding="utf-8"), flags=re.MULTILINE):
            path = urlsplit(urljoin(served, spec)).path
            local = web_root / path[len(prefix) :] if path.startswith(prefix) else None
            assert path.startswith("/scripts/") or (local is not None and local.is_file()), f"{script.name}: {spec} -> {path}"

    # Fresh pack namespaces exercise provider selection without reloading modules
    # other tests use. The modern API remains available when torchaudio is absent;
    # only an absent comfy.audio permits the legacy provider.
    audio_api = ModuleType("comfy.audio")
    audio_api.resample = sys.modules[f"{pack.__name__}.src.arisu_nodes.minimax_h3.nodes"]._resample_audio
    legacy_api = ModuleType("torchaudio.functional")

    def legacy_resample(waveform: torch.Tensor, orig_freq: int, new_freq: int) -> torch.Tensor:
        return waveform[..., :: orig_freq // new_freq]

    legacy_api.resample = legacy_resample
    real_import = builtins.__import__

    def audio_importer(failure: Optional[ImportError], allow_legacy: bool) -> Callable[..., ModuleType]:
        def import_audio(
            name: str,
            globals: Optional[Dict[str, Any]] = None,
            locals: Optional[Dict[str, Any]] = None,
            fromlist: Sequence[str] = (),
            level: int = 0,
        ) -> ModuleType:
            if name == "comfy.audio":
                if failure is not None:
                    raise failure
                return audio_api
            if name == "torchaudio.functional" and allow_legacy:
                return legacy_api
            if name == "torchaudio" or name.startswith("torchaudio."):
                raise AssertionError("torchaudio must only be imported for an absent comfy.audio")
            return real_import(name, globals, locals, fromlist, level)

        return import_audio

    for case, failure in (
        ("modern", None),
        ("legacy", ModuleNotFoundError("No module named 'comfy.audio'", name="comfy.audio")),
        ("dependency", ModuleNotFoundError("No module named 'scipy'", name="scipy")),
        ("export", ImportError("cannot import name 'resample' from 'comfy.audio'")),
    ):
        fresh_name = f"{pack.__name__}_audio_{case}"
        with monkeypatch.context() as scoped:
            scoped.setattr(builtins, "__import__", audio_importer(failure, case == "legacy"))
            try:
                if case in ("modern", "legacy"):
                    fresh = load_pack(fresh_name)
                    fresh_extension = asyncio.run(fresh.comfy_entrypoint())
                    fresh_nodes = asyncio.run(fresh_extension.get_node_list())
                    assert [node.GET_SCHEMA().node_id for node in fresh_nodes] == EXPECTED_NODE_IDS
                    h3 = sys.modules[f"{fresh_name}.src.arisu_nodes.minimax_h3.nodes"]
                    waveform = torch.arange(128, dtype=torch.float32).reshape(1, 2, 64) / 128
                    audio_vae = StubAudioVae()
                    latent, latent_t = h3.encode_ref_audio(audio_vae, {"waveform": waveform, "sample_rate": 64000})
                    assert tuple(latent.shape) == (1, 32, 2, 40) and latent_t == 40
                    assert tuple(audio_vae.encoded[0].shape) == (1, 32, 2)
                    assert torch.isfinite(audio_vae.encoded[0]).all()
                    if case == "legacy":
                        assert torch.equal(audio_vae.encoded[0], waveform[:, :, ::2].movedim(1, -1))
                else:
                    assert failure is not None
                    with pytest.raises(type(failure)) as raised:
                        load_pack(fresh_name)
                    assert raised.value is failure
            finally:
                for name in tuple(sys.modules):
                    if name == fresh_name or name.startswith(f"{fresh_name}."):
                        del sys.modules[name]
