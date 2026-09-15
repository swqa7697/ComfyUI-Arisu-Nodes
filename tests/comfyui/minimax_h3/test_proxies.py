"""Real proxy conversion and supervised-worker lifetime regressions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import av
import pytest

from src.arisu_nodes.minimax_h3.core import Resource
from src.arisu_nodes.minimax_h3.media import metadata
from src.arisu_nodes.minimax_h3.proxies import ProxyBusy, ProxyManager
from tests.support.media import make_audio, make_video

pytestmark = pytest.mark.comfyui


def test_proxy_preserves_dimensions_and_shares_interests(tmp_path: Path):
    make_video(tmp_path / "source.mkv")
    roots = {"input": str(tmp_path)}
    info = metadata(roots, Resource("v", "video", "input", "source.mkv"))
    item = Resource("v", "video", "input", "source.mkv", revision=info["revision"])

    async def run():
        manager = ProxyManager(roots, str(tmp_path / "cache"))
        try:
            first = await manager.start(item, info["duration"])
            second = await manager.start(item, info["duration"])
            job = manager.get(first)
            assert manager.get(second) is job
            await manager.release(first)
            await asyncio.wait_for(job.task, 20)
            assert job.state == "ready", job.error
            # Audio-only Opus proxies follow the same supervisor and retain source duration.
            make_audio(tmp_path / "sound.wav")
            audio_info = metadata(roots, Resource("a", "audio", "input", "sound.wav"))
            audio_handle = await manager.start(Resource("a", "audio", "input", "sound.wav", revision=audio_info["revision"]), 1)
            audio_job = manager.get(audio_handle)
            await asyncio.wait_for(audio_job.task, 20)
            assert audio_job.state == "ready", audio_job.error
            with av.open(str(audio_job.path)) as output:
                assert not output.streams.video and len(output.streams.audio) == 1
                assert sum(frame.samples for frame in output.decode(audio=0)) >= 47000
            await manager.release(audio_handle)

            with av.open(str(job.path)) as container:
                frame = next(container.decode(video=0))
                assert (frame.width, frame.height) == (65, 49)
            manager.idle = 0
            job.streams += 1
            await manager.release(second)
            manager.evict()
            assert job.path.is_file()
            job.streams -= 1
            manager.evict()
            assert not job.path.exists()
        finally:
            await manager.close()

    asyncio.run(run())


def test_proxy_reaps_stalled_workers_on_cancel_and_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_video(tmp_path / "source.mkv")
    roots = {"input": str(tmp_path)}
    info = metadata(roots, Resource("v", "video", "input", "source.mkv"))
    item = Resource("v", "video", "input", "source.mkv", revision=info["revision"])
    real_spawn = asyncio.create_subprocess_exec

    async def stalled(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        return await real_spawn(sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(60)", **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", stalled)

    async def run():
        manager = ProxyManager(roots, str(tmp_path / "cache"), deadline=0.1)
        try:
            handle = await manager.start(item, 1)
            job = manager.get(handle)
            await asyncio.wait_for(job.task, 5)
            assert job.state == "error" and job.process.returncode is not None
            assert not manager.worker.locked() and not job.path.exists()
            await manager.release(handle)
            manager.deadline = 60
            handle = await manager.start(item, 1)
            job = manager.get(handle)
            while job.process is None:
                await asyncio.sleep(0.01)
            # Partial data is accounted for, and a different source cannot queue unbounded work.
            job.path.write_bytes(b"partial")
            assert manager.size() == 7
            make_video(tmp_path / "other.mkv")
            other_info = metadata(roots, Resource("x", "video", "input", "other.mkv"))
            with pytest.raises(ProxyBusy):
                await manager.start(Resource("x", "video", "input", "other.mkv", revision=other_info["revision"]), 1)
            await manager.release(handle)
            assert job.process.returncode is not None and job.state == "cancelled"
            assert not manager.worker.locked() and not job.path.exists()
            # Immediate release before the task starts still releases the worker guard.
            handle = await manager.start(item, 1)
            immediate = manager.get(handle)
            await manager.release(handle)
            assert immediate.state == "cancelled" and not manager.worker.locked()
            # A hard byte budget counts partial files and stops conversion before publication.
            manager.budget = 1
            handle = await manager.start(item, 1)
            limited = manager.get(handle)
            limited.path.write_bytes(b"too large")
            await asyncio.wait_for(limited.task, 5)
            assert limited.state == "error" and not limited.path.exists()
            await manager.release(handle)

        finally:
            await manager.close()

    asyncio.run(run())
