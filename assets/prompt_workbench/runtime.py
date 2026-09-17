"""Fresh CLI state with credential-only synchronization to the borrowed volume."""

from __future__ import annotations

import json
import os
import signal
import stat
import tempfile
import threading
from pathlib import Path
from typing import Optional

# This module runs in Linux containers; host-side tests may import it on Windows.
if os.name == "posix":
    import fcntl


class Runtime:
    """Serialize credential use without loading any policy from persistent storage."""

    def __init__(self, agent: str, auth: Path = Path("/auth"), home: Path = Path("/home/agent")):
        self.auth = auth
        self.home = home / ("." + agent)
        self.agent = agent
        self.stop = threading.Event()
        self.error: Optional[Exception] = None
        self.last: Optional[bytes] = None
        self.thread: Optional[threading.Thread] = None
        self.lock: Optional[int] = None

    def __enter__(self) -> Runtime:  # noqa: PYI034 - Python 3.10 container-test imports
        self.lock = os.open(self.auth / ".workbench.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.home.mkdir(parents=True, exist_ok=True)
            source = self.auth / "auth.json"
            if source.is_symlink():
                raise ValueError("invalid credential destination")
            if source.exists():
                self.last = self.read(source)
                target = self.home / "auth.json"
                target.write_bytes(self.last)
                target.chmod(0o600)
            policy = Path("/opt/workbench/agents") / self.agent / "config.toml"
            (self.home / "config.toml").symlink_to(policy)
            self.thread = threading.Thread(target=self.watch, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            os.close(self.lock)
            self.lock = None
            raise

    @staticmethod
    def read(path: Path) -> bytes:
        """Read a small regular credential file without following a symlink."""
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("credentials must be a regular file")
            value = source.read(256 * 1024 + 1)
        if len(value) > 256 * 1024 or not isinstance(json.loads(value), dict):
            raise ValueError("invalid credentials")
        return value

    def sync(self):
        """Persist credential rotation atomically, never other CLI-owned state."""
        source = self.home / "auth.json"
        if not source.exists():
            return
        value = self.read(source)
        if value != self.last:
            target = self.auth / "auth.json"
            if target.is_symlink():
                raise ValueError("invalid credential destination")
            descriptor, name = tempfile.mkstemp(prefix=".workbench-auth-", dir=self.auth)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(value)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self.last = value

    def watch(self):
        """Save refreshes even during long inference requests."""
        while not self.stop.wait(0.2):
            try:
                self.sync()
            except (OSError, ValueError) as error:
                self.error = error
                return

    def __exit__(self, *_args):
        self.stop.set()
        if self.thread:
            self.thread.join()
        try:
            self.sync()
            if self.error:
                raise ValueError("credential synchronization failed") from self.error
        finally:
            if self.lock is not None:
                os.close(self.lock)


def stop_on_signal(_number: int, _frame):
    """Unwind process/credential cleanup when Docker stops the container."""
    raise SystemExit(128 + signal.SIGTERM)
