"""Fixed, isolated startup for the two CPU media workers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List


def worker_environment() -> Dict[str, str]:
    """Pass OS startup settings without host secrets or interpreter overrides."""
    names = ("SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
    return {"PATH": os.defpath, **{name: os.environ[name] for name in names if name in os.environ}}


def worker_command(worker: str) -> List[str]:
    """Select only a package-owned worker under isolated, bytecode-free Python."""
    if worker not in ("proxy", "workbench"):
        raise ValueError("unsupported media worker")
    return [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), worker]


def main():
    """Restore only this package's source directory, never the parent's imports."""
    if len(sys.argv) != 2 or sys.argv[1] not in ("proxy", "workbench"):
        raise ValueError("unsupported media worker")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Load PyAV and the selected worker only in the child, after fixed path setup.
    if sys.argv[1] == "proxy":
        from arisu_nodes.minimax_h3.proxy_worker import main as run
    else:
        from arisu_nodes.minimax_h3.workbench_media import main as run
    run()


if __name__ == "__main__":
    main()
