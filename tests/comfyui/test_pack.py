"""Regression flow: the pack loads the way ComfyUI loads it.

Nothing else verifies that the node pack imports until a clone is dropped into
a live ComfyUI and the service restarted, so this lane is the early warning.
Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest
from comfy_api.latest import ComfyExtension

pytestmark = pytest.mark.comfyui

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_NODE_IDS = [
    "ArisuMiniMaxH3HybridToVideo",
    "ArisuMiniMaxH3HybridToVideoAdvanced",
    "ArisuMiniMaxH3ContextLatentResize",
    "ArisuMiniMaxH3VideoSettings",
    "ArisuMiniMaxH3VideoSettingsUpscale",
    "ArisuPathBuilder",
    "ArisuExtractLastImages",
    "ArisuPreviewSaveImage",
    "ArisuPreviewSaveImageUpscale",
]


@pytest.fixture(scope="module")
def pack() -> ModuleType:
    """Import the repo root as a package exactly like ComfyUI's ``load_custom_node``.

    ComfyUI never puts the pack on ``sys.path``; it builds a spec from the
    directory's ``__init__.py`` under a module name derived from the path, so
    the entry file's relative imports (``from .src... import``) must work that
    way.
    """
    name = str(REPO_ROOT).replace(".", "_x_")
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_pack_loads_like_comfyui(pack: ModuleType):
    extension = asyncio.run(pack.comfy_entrypoint())
    assert isinstance(extension, ComfyExtension)

    nodes = asyncio.run(extension.get_node_list())
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
    assert (REPO_ROOT / pack.WEB_DIRECTORY).is_dir()
