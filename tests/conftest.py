"""Shared pytest configuration for both test lanes.

Two jobs:

1. Collect the repo root as a plain directory. The root holds ComfyUI's entry
   file (an ``__init__.py`` importing ``comfy_api``), so pytest 8+ would collect
   the root as a ``Package`` and import that file during test setup, which
   fails outside ComfyUI. The hook is registered as a plugin rather than
   defined here directly because conftest hooks are scoped to their own
   directory, while the collector for the root is chosen through the hook
   proxy of the root's *parent* directory.
2. Wire ``sys.path``: the repo root first, so ``src.arisu_nodes`` and ``tests``
   resolve to this repo; then ``scripts/``, so the unit lane imports
   ``release_common`` under the same name the release CLIs use; then ComfyUI's
   root when ``COMFYUI_PATH`` is set, so ``comfy_api`` resolves. ComfyUI's tree
   has its own top-level ``tests`` package, hence the ordering.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

SCRIPTS_DIR = str(Path(REPO_ROOT) / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(sys.path.index(REPO_ROOT) + 1, SCRIPTS_DIR)

COMFYUI_PATH = os.environ.get("COMFYUI_PATH")
if COMFYUI_PATH and COMFYUI_PATH not in sys.path:
    sys.path.insert(sys.path.index(SCRIPTS_DIR) + 1, COMFYUI_PATH)


class _RootAsPlainDirectory:
    @staticmethod
    def pytest_collect_directory(path: Path, parent: pytest.Collector) -> pytest.Dir | None:
        if path == parent.config.rootpath:
            return pytest.Dir.from_parent(parent, path=path)
        return None


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(_RootAsPlainDirectory(), "arisu_root_as_plain_directory")
