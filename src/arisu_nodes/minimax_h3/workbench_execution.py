"""Isolate authorized queued motion preparation from the ordinary executor cache."""

from __future__ import annotations

import functools
import inspect
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import execution
import folder_paths

from .workbench_context import context_inputs

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_pending: Dict[str, Tuple[Any, Any]] = {}
_adapter = None


def install():
    """Install once, failing closed when the executor interface is incompatible."""
    global _adapter
    with _lock:
        current = execution.PromptExecutor.execute_async
        if current is _adapter:
            return
        if _adapter is not None or not inspect.iscoroutinefunction(current):
            raise ValueError("Workbench motion cache isolation is unavailable with this executor")
        if not {"self", "prompt", "prompt_id", "extra_data", "execute_outputs"}.issubset(inspect.signature(current).parameters):
            raise ValueError("Workbench motion cache isolation requires a compatible ComfyUI executor")

        @functools.wraps(current)
        async def isolated(self: Any, prompt: Any, prompt_id: str, extra_data: Any = None, execute_outputs: Any = None) -> Any:
            with _lock:
                registration = _pending.pop(prompt_id, None)
            if registration is None:
                return await current(self, prompt, prompt_id, extra_data or {}, execute_outputs or [])
            job, approved = registration
            original = self.caches
            try:
                if job.cancelled.is_set() or time.monotonic() > job.deadline or prompt is not approved or execute_outputs != [job.node_id]:
                    raise ValueError("Workbench motion preparation authorization expired")
                self.caches = execution.CacheSet(cache_type=self.cache_type, cache_args=self.cache_args)
                if self.cache_type == execution.CacheType.RAM_PRESSURE:
                    release_private = self.caches.outputs.ram_release

                    def release(target: Any, free_active: bool = False, min_entry_size: int = 0) -> int:
                        freed = release_private(target, free_active=free_active, min_entry_size=min_entry_size)
                        # Keep normal pressure relief available without changing the video graph's cache keys.
                        return freed + original.outputs.ram_release(target, free_active=free_active, min_entry_size=min_entry_size)

                    self.caches.outputs.ram_release = release
                return await current(self, prompt, prompt_id, extra_data or {}, execute_outputs or [])
            except Exception:
                logger.exception("Workbench isolated preparation failed")
                job.error = "Motion preparation failed; check the server logs."
                job.prepared.set()
                self.success = False
                self.history_result = {"outputs": {}, "meta": {}}
                self.status_messages = []
                self.add_message(
                    "execution_error",
                    {
                        "prompt_id": prompt_id,
                        "node_id": job.node_id,
                        "node_type": "ArisuMiniMaxH3PromptWorkbench",
                        "executed": [],
                        "exception_message": job.error,
                        "exception_type": "RuntimeError",
                        "traceback": [],
                        "current_inputs": {},
                        "current_outputs": [],
                    },
                    broadcast=False,
                )
            finally:
                if self.caches is not original and self.cache_type == execution.CacheType.RAM_PRESSURE:
                    self.caches.outputs.__dict__.pop("ram_release", None)
                self.caches = original

        _adapter = isolated
        execution.PromptExecutor.execute_async = isolated


def register(prompt_id: str, job: Any, graph: Any):
    """Authorize an exact server-owned graph before placing it on the queue."""
    install()
    with _lock:
        _pending[prompt_id] = (job, graph)


def discard(prompt_id: str):
    """Forget a cancelled or finished queued capability."""
    with _lock:
        _pending.pop(prompt_id, None)


def vae_identity(job: Any) -> str:
    """Identify installed VAE weights without loading a model or touching GPU state."""
    source = job.graph[job.node_id]["inputs"]["vae"][0]
    while job.graph[source]["class_type"] == "Reroute":
        source = next(iter(job.graph[source]["inputs"].values()))[0]
    selection = context_inputs(job.graph, source, job.roots, ("vae_name",))["vae_name"]
    if selection not in folder_paths.get_filename_list("vae"):
        raise ValueError("select an installed video VAE")
    model_path = Path(folder_paths.get_full_path_or_raise("vae", selection))
    stat = model_path.stat()
    return repr((selection, str(model_path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
