"""One supervised conversion worker and a bounded, interest-aware proxy cache."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Set

from .core import Resource
from .media import source_file

logger = logging.getLogger(__name__)


class ProxyBusy(ValueError):
    """The single conversion worker is busy."""


@dataclass
class ProxyJob:
    """A shared conversion; editor handles and active streams pin its lifetime."""

    item: Resource
    directory: Path
    duration: float
    state: str = "running"
    progress: int = 0
    error: str = ""
    interests: Set[str] = field(default_factory=set)
    streams: int = 0
    touched: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    task: Optional[asyncio.Task[Any]] = None
    process: Optional[asyncio.subprocess.Process] = None

    @property
    def path(self) -> Path:
        """The sole server-generated file owned by this job."""
        return self.directory / "playback.webm"


class ProxyManager:
    """Manage conversion ownership until the actual child process exits."""

    def __init__(self, roots: Mapping[str, str], temp: str, budget: int = 2 * 1024**3, deadline: float = 600, idle: float = 1800):
        self.roots = roots
        self.temp = temp
        self.budget = budget
        self.deadline = deadline
        self.idle = idle
        self.jobs: Dict[str, ProxyJob] = {}
        self.handles: Dict[str, ProxyJob] = {}
        self.accessed: Dict[str, float] = {}
        self.worker = asyncio.Lock()
        self.sweeper: Optional[asyncio.Task[Any]] = None

    def key(self, item: Resource) -> str:
        """Include relative source identity as well as revision in shared cache keys."""
        return json.dumps((item.root, item.path, item.revision, "vp9-opus-v1"))

    def size(self) -> int:
        """Count partial outputs as well as ready files."""
        return sum(job.path.stat().st_size for job in self.jobs.values() if job.path.exists())

    def evict(self, needed: int = 0):
        """Remove only idle, unserved entries; never unlink a streaming file."""
        now = time.monotonic()
        for handle, touched in list(self.accessed.items()):
            job = self.handles.get(handle)
            if job and not job.streams and now - touched >= self.idle:
                job.interests.discard(handle)
                self.handles.pop(handle, None)
                self.accessed.pop(handle, None)
                if not job.interests and job.state == "running":
                    job.cancelled = True
        for key, job in sorted(self.jobs.items(), key=lambda pair: pair[1].touched):
            if job.state == "running" or job.interests or job.streams:
                continue
            if now - job.touched >= self.idle or self.size() + needed > self.budget:
                shutil.rmtree(job.directory)
                self.jobs.pop(key, None)

    async def start(self, item: Resource, duration: float) -> str:
        """Acquire a separate editor interest, sharing an existing conversion."""
        with source_file(self.roots, item):
            pass
        self.evict()
        if len(self.handles) >= 256:
            raise ProxyBusy("too many playback interests")
        key = self.key(item)
        job = self.jobs.get(key)
        if job is not None and job.state in ("error", "cancelled"):
            self.jobs[key + ":" + uuid.uuid4().hex] = job
            self.jobs.pop(key)
            job = None
        if job is None:
            if self.worker.locked():
                raise ProxyBusy("another playback conversion is running")
            await self.worker.acquire()
            try:
                os.makedirs(self.temp, exist_ok=True)
                job = ProxyJob(item, Path(tempfile.mkdtemp(prefix="arisu-resource-", dir=self.temp)), duration)
                self.jobs[key] = job
                job.task = asyncio.create_task(self._run(job))
            except BaseException:
                self.worker.release()
                raise
        handle = uuid.uuid4().hex
        job.interests.add(handle)
        job.touched = time.monotonic()
        self.handles[handle] = job
        self.accessed[handle] = time.monotonic()
        if self.sweeper is None:
            self.sweeper = asyncio.create_task(self._sweep())
        return handle

    def get(self, handle: str) -> ProxyJob:
        """Recheck source authorization even when the playback proxy is cached."""
        job = self.handles[handle]
        with source_file(self.roots, job.item):
            pass
        job.touched = time.monotonic()
        self.accessed[handle] = job.touched
        return job

    async def release(self, handle: str):
        """Release only this editor's interest; reap abandoned running work."""
        self.accessed.pop(handle, None)
        job = self.handles.pop(handle, None)
        if job is None:
            return
        job.interests.discard(handle)
        job.touched = time.monotonic()
        if not job.interests and job.state == "running" and job.task:
            job.cancelled = True
            # Cleanup must finish even if the HTTP client disconnects here.
            await asyncio.shield(asyncio.gather(job.task, return_exceptions=True))

    async def _progress(self, job: ProxyJob):
        while line := await job.process.stdout.readline():
            try:
                job.progress = int(json.loads(line)["progress"])
            except (KeyError, ValueError, TypeError):
                logger.warning("invalid playback worker progress")

    async def _run(self, job: ProxyJob):
        reader = None
        errors = None
        try:
            if job.cancelled:
                raise asyncio.CancelledError
            job.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-B",
                "-m",
                "arisu_nodes.minimax_h3.proxy_worker",
                env={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parents[2]), *sys.path]),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            payload = {
                "roots": dict(self.roots),
                "item": asdict(job.item),
                "output": str(job.path),
                "duration": job.duration,
                "max_bytes": max(0, self.budget - self.size()),
            }
            job.process.stdin.write(json.dumps(payload).encode())
            await job.process.stdin.drain()
            job.process.stdin.close()
            reader = asyncio.create_task(self._progress(job))
            errors = asyncio.create_task(job.process.stderr.read())
            started = time.monotonic()
            while job.process.returncode is None:
                if job.cancelled:
                    raise asyncio.CancelledError
                if time.monotonic() - started >= self.deadline:
                    raise TimeoutError("playback conversion deadline exceeded")
                self.evict()
                if self.size() > self.budget:
                    raise ValueError("playback cache capacity exceeded")
                await asyncio.sleep(0.1)
            await job.process.wait()
            if job.process.returncode:
                logger.error("playback worker failed: %s", (await errors).decode(errors="replace"))
                raise ValueError("playback codec is unavailable or conversion failed")
            if self.size() > self.budget:
                raise ValueError("playback cache capacity exceeded")
            with source_file(self.roots, job.item):
                pass
            job.state, job.progress = "ready", 100
        except asyncio.CancelledError:
            job.state = "cancelled"
        except Exception:
            logger.exception("playback conversion failed")
            job.state, job.error = "error", "Playback conversion failed or exceeded its limits. Retry."
        finally:
            if job.process and job.process.returncode is None:
                job.process.kill()
                await job.process.wait()
            for task in (reader, errors):
                if task:
                    await asyncio.gather(task, return_exceptions=True)
            if job.state != "ready":
                job.path.unlink(missing_ok=True)
            job.touched = time.monotonic()
            self.worker.release()

    async def _sweep(self):
        while True:
            await asyncio.sleep(30)
            self.evict()

    async def close(self):
        """Reap workers before deleting server-owned cache directories."""
        if self.sweeper:
            self.sweeper.cancel()
            await asyncio.gather(self.sweeper, return_exceptions=True)
        tasks = [job.task for job in self.jobs.values() if job.task]
        for job in self.jobs.values():
            job.cancelled = True
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in self.jobs.values():
            if not job.streams:
                shutil.rmtree(job.directory, ignore_errors=True)
        self.jobs.clear()
        self.handles.clear()
        self.accessed.clear()
