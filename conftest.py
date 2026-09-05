"""Repo-root pytest configuration.

ComfyUI requires this directory to be a package: ``__init__.py`` imports
``comfy_api``. pytest would otherwise collect the root as a ``Package`` and
import that file during test setup, which fails outside ComfyUI. Collect the
root as a plain directory instead.

The hook is registered as a plugin rather than defined here directly because
conftest hooks are scoped to their own directory, while the collector for the
root is chosen through the hook proxy of the root's *parent* directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class _RootAsPlainDirectory:
    @staticmethod
    def pytest_collect_directory(path: Path, parent: pytest.Collector) -> pytest.Dir | None:
        if path == parent.config.rootpath:
            return pytest.Dir.from_parent(parent, path=path)
        return None


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(_RootAsPlainDirectory(), "arisu_root_as_plain_directory")
