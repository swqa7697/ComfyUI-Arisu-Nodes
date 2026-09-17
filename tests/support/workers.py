"""Hostile parent state and real child probes shared by media-worker regressions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pytest


def poison_parent(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plant an import hook and synthetic secrets that workers must not inherit."""
    directory.mkdir()
    marker = directory / "executed"
    (directory / "sitecustomize.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
    (directory / "folder_paths.py").write_text("raise RuntimeError('worker imported host ComfyUI')\n")
    monkeypatch.syspath_prepend(str(directory))
    for name, value in {
        "ARISU_TEST_SECRET": "synthetic-secret",
        "OPENAI_API_KEY": "synthetic-key",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "PYTHONPATH": str(directory),
        "PYTHONHOME": str(directory / "missing-python"),
        "PYTHONINSPECT": "1",
        "LD_LIBRARY_PATH": str(directory),
    }.items():
        monkeypatch.setenv(name, value)
    return marker


def assert_worker_isolated(arguments: Sequence[str], environment: Mapping[str, str], spawn: Callable[..., Any]):
    """Probe effective startup and environment using the real worker launch prefix."""
    probe = "import json,os,sys; print(json.dumps([list(os.environ),sys.flags.isolated,sys.dont_write_bytecode,sys.flags.utf8_mode]))"
    with spawn([*arguments[:-2], "-c", probe], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
    names, isolated, no_bytecode, utf8 = json.loads(stdout)
    assert not set(names) & {
        "ARISU_TEST_SECRET",
        "OPENAI_API_KEY",
        "HTTPS_PROXY",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "LD_LIBRARY_PATH",
    }
    assert isolated and no_bytecode and utf8
