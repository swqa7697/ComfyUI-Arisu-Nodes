"""Preparation jobs and bounded, workflow-scoped Workbench media cache."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PIL import Image

from ..worker import worker_command, worker_environment
from .agent_docker import ASSETS, AgentBusy, DockerAgents
from .core import ResourceBundle, VideoSettings, finalized_markdown, motion_samples, validate_bundle, workbench_options
from .media import validate_workbench_source
from .workbench_images import PROCESSING, encode_image

logger = logging.getLogger(__name__)
CACHE_LIMIT = 2 * 1024 * 1024 * 1024
CACHE_TTL = 1800


def skill_catalog(directory: Path) -> Dict[str, Path]:
    """Discover only bounded, contained skill folders from administrator locations."""
    result = {}
    for prefix, root in (("bundled", ASSETS / "skills"), ("custom", directory / "skills")):
        if not root.is_dir() or root.is_symlink():
            continue
        for child in sorted(root.iterdir()):
            if len(result) >= 256:
                break
            if not child.is_dir() or child.is_symlink() or child.resolve().parent != root.resolve():
                continue
            definition = child / "SKILL.md"
            if not definition.is_file() or definition.is_symlink():
                continue
            paths = list(child.rglob("*"))
            if any(p.is_symlink() or (not p.is_file() and not p.is_dir()) for p in paths):
                continue
            if sum(p.stat().st_size for p in paths if p.is_file()) > 16 * 1024 * 1024:
                continue
            result[prefix + ":" + child.name] = child
    return result


@dataclass
class Generation:
    """A one-shot preparation capability; never a persisted workflow permission."""

    id: str
    node_id: str
    workflow: str
    options: Dict[str, Any]
    selection: Dict[str, Any]
    directory: Path
    graph: Dict[str, Any]
    deadline: float = field(default_factory=lambda: time.monotonic() + 600)
    cancelled: threading.Event = field(default_factory=threading.Event)
    prepared: threading.Event = field(default_factory=threading.Event)
    preparation_done: threading.Event = field(default_factory=threading.Event)
    state: str = "preparing"
    error: str = ""
    draft: str = ""
    taken: bool = False
    resources: Optional[ResourceBundle] = None
    settings: Optional[VideoSettings] = None
    motion: List[Dict[str, Any]] = field(default_factory=list)
    roots: Dict[str, str] = field(default_factory=dict)
    queue_finished: Optional[Callable[[], bool]] = None
    created: float = field(default_factory=time.monotonic)

    def public(self) -> Dict[str, Any]:
        """Return UI state, excluding physical paths and runtime capabilities."""
        return {"id": self.id, "state": self.state, "error": self.error, "draft": self.draft}


def _keyframe(assets: List[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    """Return the MCP keyframe row for a staged first/last lock."""
    item = next((asset for asset in assets if asset.get("role") == role), None)
    if item is None:
        return None
    return {"asset_id": item["id"], "name": item.get("name", ""), "resource_id": item.get("resource_id")}


def _inspect(item: Any, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe what the agent may read for one Studio card."""
    if item.kind == "image":
        return {
            "type": "image",
            "asset_ids": [asset["id"] for asset in assets if asset.get("resource_id") == item.id and asset.get("role") == "reference"],
        }
    if item.kind == "video":
        return {
            "type": "stills",
            "frames": [
                {"asset_id": asset["id"], "timestamp": asset.get("timestamp")}
                for asset in assets
                if asset.get("resource_id") == item.id and asset.get("role") == "reference_video_frame"
            ],
        }
    return {"type": "none"}


def job_context(job: Generation, assets: List[Dict[str, Any]], resources: ResourceBundle) -> Dict[str, Any]:
    """Build the version-3 Workbench MCP manifest from staged media."""
    settings = job.settings
    duration = settings.length / 24 if settings else None
    present = bool(job.motion)
    delivered = (settings.length - job.options["context_length"]) / 24 if settings and present else duration
    references = []
    for item in resources.images + resources.videos + resources.audios:
        if item.muted:
            continue
        key = job.options["source_id"] + ":" + item.id + ":" + item.root + ":" + item.path
        entry: Dict[str, Any] = {
            "id": item.id,
            "kind": item.kind,
            "name": Path(item.path).name,
            "note": job.options["reference_notes"].get(key, ""),
            "inspect": _inspect(item, assets),
        }
        if item.kind == "image" and item.crop:
            entry["selected_crop"] = item.crop
        if item.kind != "image":
            entry["selected_clip"] = item.clip
        if item.kind == "video":
            entry["include_audio"] = item.include_audio
        references.append(entry)
    attached = []
    notes = {entry["id"]: entry["note"] for entry in references}
    for index, asset in enumerate(assets):
        note = job.options["motion_notes"] if asset["role"] == "motion" else notes.get(asset.get("resource_id"), "")
        attached.append({**asset, "path": "/inputs/" + asset["file"], "attachment_index": index + 1, "note": note})
    return {
        "version": 3,
        "duration_seconds": duration,
        "frame_count": settings.length if settings else None,
        "aspect_ratio": settings.aspect_ratio if settings else None,
        "trigger_words": job.options["trigger_words"],
        "requirements": job.options["requirements"],
        "motion": {
            "present": present,
            "context_length": job.options["context_length"],
            "audio_context_length": job.options["audio_context_length"],
            "sample_duration_seconds": duration,
            "delivered_duration_seconds": delivered,
            "notes": job.options["motion_notes"] if present else "",
            "stills": [{"asset_id": asset["id"], "timestamp": asset.get("timestamp")} for asset in job.motion],
        },
        "keyframes": {"first": _keyframe(assets, "first_keyframe"), "last": _keyframe(assets, "last_keyframe")},
        "assets": attached,
        "references": references,
    }


class Workbench:
    """Own one generation until its CPU preparation and Docker container exit."""

    def __init__(self, directory: Path, temp: Path):
        self.directory = directory
        self.temp = temp
        self.agents = DockerAgents(directory)
        self.jobs: Dict[str, Generation] = {}
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.released: Dict[str, float] = {}
        self.lock = threading.RLock()

    def create(self, node_id: str, workflow: str, options: Any, graph: Dict[str, Any]) -> Generation:
        """Reserve the shared agent guard and issue a fresh preparation capability."""
        options = workbench_options(options)
        if options["skill"] not in skill_catalog(self.directory):
            raise ValueError("selected skill is unavailable")
        # Let discovery finish, then reserve without another poll taking the guard.
        with self.agents.discovery:
            status = self.agents.status()
            provider = status.get("agents", {}).get(options["agent"], {})
            if not status["docker"] or not provider.get("ready"):
                raise ValueError("complete agent setup before generating")
            if not self.agents.guard.acquire(blocking=False):
                raise AgentBusy("Workbench is busy")
        destination: Optional[Path] = None
        try:
            self.temp.mkdir(parents=True, exist_ok=True)
            if self.temp.is_symlink():
                raise ValueError("invalid cache destination")
            self.reap()
            with self.lock:
                if workflow in self.released:
                    raise ValueError("workflow was closed during preparation")
            identifier = uuid.uuid4().hex
            destination = self.temp / identifier
            destination.mkdir(mode=0o700)
            job = Generation(identifier, node_id, workflow, options, provider["selection"], destination, graph)
            graph[node_id]["inputs"]["prepare_job"] = identifier
            with self.lock:
                if workflow in self.released:
                    raise ValueError("workflow was closed during preparation")
                self.jobs[identifier] = job
            self.agents.begin_logs(options["agent"], "generate", job.id)
            self.agents.log("[prepare] Preparing workflow and selected references…")
            return job
        except BaseException:
            if destination is not None:
                shutil.rmtree(destination, ignore_errors=True)
            self.agents.guard.release()
            raise

    def get(self, identifier: str) -> Generation:
        """Resolve an existing job without treating client-provided paths as capabilities."""
        with self.lock:
            job = self.jobs.get(identifier)
        if job is None:
            raise ValueError("Workbench job is unavailable")
        return job

    def preparation(self, identifier: str, node_id: Optional[str] = None) -> Generation:
        """Require a current, matching, unconsumed preparation job."""
        job = self.get(identifier)
        if job.cancelled.is_set() or time.monotonic() > job.deadline or job.state != "preparing" or job.prepared.is_set():
            raise ValueError("Workbench preparation expired")
        if node_id is not None and str(node_id) != job.node_id:
            raise ValueError("Workbench preparation target changed")
        return job

    def take(self, identifier: str, node_id: Optional[str] = None) -> Generation:
        """Mark the execution worker before any VAE or file side effects."""
        with self.lock:
            job = self.preparation(identifier, node_id)
            if job.taken:
                raise ValueError("Workbench preparation has already been consumed")
            job.taken = True
            return job

    def used_bytes(self) -> int:
        """Count partial files, excluding symlinks, before reserving new writes."""
        return sum(p.stat().st_size for p in self.temp.rglob("*") if p.is_file() and not p.is_symlink())

    def link_file(self, original: Path, target: Path):
        """Create an exclusive immutable job/cache reference within the byte budget."""
        if original.is_symlink() or not original.is_file() or original.stat().st_size + self.used_bytes() > CACHE_LIMIT:
            raise ValueError("Workbench media cache capacity exceeded or entry unavailable")
        os.link(original, target, follow_symlinks=False)

    def restore_assets(self, job: Generation, key: str) -> Optional[List[Dict[str, Any]]]:
        """Reuse prepared files only after callers validate current source revisions."""
        with self.lock:
            cached = self.cache.get(key)
            if not cached or not cached["path"].is_dir() or cached["path"].is_symlink():
                return None
            for asset in cached["assets"]:
                self.link_file(cached["path"] / asset["file"], job.directory / asset["file"])
            cached["used"] = time.monotonic()
            cached["workflows"].add(job.workflow)
            return [dict(asset) for asset in cached["assets"]]

    def store_assets(self, job: Generation, key: str, assets: List[Dict[str, Any]]):
        """Cache immutable staged media; no tensors or source paths are retained."""
        with self.lock:
            if key in self.cache:
                return
            destination = self.temp / ("cache-" + key + "-" + uuid.uuid4().hex)
            destination.mkdir()
            try:
                for asset in assets:
                    self.link_file(job.directory / asset["file"], destination / asset["file"])
            except BaseException:
                shutil.rmtree(destination, ignore_errors=True)
                raise
            self.cache[key] = {"path": destination, "used": time.monotonic(), "workflows": {job.workflow}, "assets": assets}

    def cache_motion(self, job: Generation, key: str, frames: Optional[List[Image.Image]] = None) -> bool:
        """Cache only bounded stills, with timestamps matching sampled frame indices."""
        if frames is None:
            assets = self.restore_assets(job, key)
            if assets is None:
                return False
            job.motion = assets
            return True
        times = motion_samples(job.options["context_length"])
        if len(frames) != len(times):
            raise ValueError("motion frame count mismatch")
        for index, frame in enumerate(frames):
            target = job.directory / (uuid.uuid4().hex + ".webp")
            encoded = io.BytesIO()
            dimensions = encode_image(frame, encoded, CACHE_LIMIT - self.used_bytes())
            with target.open("xb") as output:
                output.write(encoded.getvalue())
            job.motion.append(
                {
                    "id": target.stem,
                    "file": target.name,
                    "mime": "image/webp",
                    "role": "motion",
                    "resource_id": "motion",
                    "timestamp": times[index] / 24,
                    "sequence_index": index,
                    **dimensions,
                }
            )
        self.store_assets(job, key, job.motion)
        return True

    def enforce_budget(self):
        """Count partial files as well as complete cached entries."""
        if self.used_bytes() > CACHE_LIMIT:
            raise ValueError("Workbench media cache capacity exceeded")

    def reap(self, workflow: Optional[str] = None):
        """Expire idle caches and finished jobs, or release a closed workflow."""
        if self.temp.is_symlink():
            return
        now = time.monotonic()
        with self.lock:
            self.released = {key: at for key, at in self.released.items() if now - at < CACHE_TTL}
            for key, value in list(self.cache.items()):
                if workflow:
                    value["workflows"].discard(workflow)
                if now - value["used"] > CACHE_TTL or not value["workflows"]:
                    shutil.rmtree(value["path"], ignore_errors=True)
                    del self.cache[key]
            # A previous process leaves no in-memory interests; expire only its named staging directories.
            known = {value["path"] for value in self.cache.values()} | {job.directory for job in self.jobs.values()}
            for path in self.temp.iterdir() if self.temp.is_dir() else ():
                if (
                    path not in known
                    and not path.is_symlink()
                    and path.is_dir()
                    and re.fullmatch(r"(?:[0-9a-f]{32}|cache-[0-9a-f]{64}(?:-[0-9a-f]{32})?)", path.name)
                    and time.time() - path.stat().st_mtime > CACHE_TTL
                ):
                    shutil.rmtree(path, ignore_errors=True)
            for key, job in list(self.jobs.items()):
                if job.state in ("complete", "failed", "cancelled") and (now - job.created > CACHE_TTL or job.workflow == workflow):
                    shutil.rmtree(job.directory, ignore_errors=True)
                    del self.jobs[key]

    def release(self, workflow: str):
        """Cancel outstanding work and release this browser workflow's cache interest."""
        with self.lock:
            self.released[workflow] = time.monotonic()
            if len(self.released) > 512:
                del self.released[next(iter(self.released))]
            for job in self.jobs.values():
                if job.workflow == workflow:
                    job.cancelled.set()
        self.reap(workflow)

    def execute(self, job: Generation):
        """Wait for queued preparation, stage media, then run the agent off the graph queue."""
        process = None
        try:
            while not job.prepared.wait(0.1):
                if job.queue_finished and job.queue_finished():
                    raise ValueError("preparation did not complete; check the connected loaders and ComfyUI execution error")
                if job.cancelled.is_set() or time.monotonic() > job.deadline:
                    raise ValueError("generation cancelled or preparation timed out")
            if job.error:
                raise ValueError(job.error)
            if job.cancelled.is_set():
                raise ValueError("generation cancelled")
            job.state = "preparing_media"
            resources = job.resources or ResourceBundle()
            validate_bundle(resources)
            sources = []
            for role, items in (
                ("first_keyframe", (resources.first,)),
                ("last_keyframe", (resources.last,)),
                ("reference", resources.images + resources.videos + resources.audios),
            ):
                for item in items:
                    if item:
                        validate_workbench_source(job.roots, item)
                        sources.append({"role": role, "item": asdict(item)})
            used = self.used_bytes()
            payload = {
                "directory": str(job.directory),
                "roots": job.roots,
                "resources": sources,
                "max_bytes": CACHE_LIMIT - used,
            }
            media_key = hashlib.sha256(json.dumps([sources, PROCESSING], sort_keys=True).encode()).hexdigest()
            assets = self.restore_assets(job, media_key)
            if assets is None:
                process = subprocess.Popen(
                    worker_command("workbench"),
                    cwd=ASSETS.parents[1],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env=worker_environment(),
                )
                sent = False
                while True:
                    try:
                        stdout, stderr = process.communicate(json.dumps(payload) if not sent else None, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        sent = True
                        if job.cancelled.is_set() or time.monotonic() > job.deadline:
                            raise ValueError("generation cancelled or preparation timed out")
                if process.returncode:
                    logger.warning("Workbench media worker: %s", stderr[-4000:])
                    raise ValueError("selected media could not be prepared")
                assets = json.loads(stdout)
                self.store_assets(job, media_key, assets)
            assets = assets + job.motion
            (job.directory / "context.json").write_text(json.dumps(job_context(job, assets, resources), ensure_ascii=False))
            self.enforce_budget()
            # Snapshot the selected skill too: no symlink/administrator edits during a run.
            skill = skill_catalog(self.directory).get(job.options["skill"])
            if skill is None:
                raise ValueError("selected skill is unavailable")
            staged_skill = job.directory / "skill"
            if sum(p.stat().st_size for p in skill.rglob("*") if p.is_file()) + self.used_bytes() > CACHE_LIMIT:
                raise ValueError("Workbench media cache capacity exceeded")
            shutil.copytree(skill, staged_skill)
            for item in resources.sources():
                validate_workbench_source(job.roots, item)
            # Docker's fixed unprivileged UID can differ from the host owner's UID.
            # These are exclusively staged files, never hard links to source originals.
            job.directory.chmod(0o755)
            for path in job.directory.rglob("*"):
                path.chmod(0o755 if path.is_dir() else path.stat().st_mode | 0o444)
            job.state = "generating"
            job.draft = finalized_markdown(
                self.agents.generate(job.options["agent"], job.directory, staged_skill, job.selection, job.cancelled, job.deadline)
            )
            if job.cancelled.is_set():
                raise ValueError("generation cancelled")
            job.state = "complete"
        except Exception as error:
            logger.exception("Workbench generation failed")
            job.state = "cancelled" if job.cancelled.is_set() else "failed"
            job.error = str(error) if isinstance(error, ValueError) else "Prompt generation failed; see server logs."
        finally:
            job.cancelled.set()
            if process and process.poll() is None:
                process.kill()
                process.communicate()
            # A disconnected browser must not release the GPU preparation worker's guard.
            if job.queue_finished:
                while not job.queue_finished():
                    time.sleep(0.1)
            if job.taken:
                job.preparation_done.wait()
            shutil.rmtree(job.directory, ignore_errors=True)
            self.agents.finish_logs(job.state)
            self.agents.guard.release()

    def close(self):
        """Request cancellation; the owning workers retain their guards until exit."""
        with self.lock:
            for job in self.jobs.values():
                job.cancelled.set()
        self.agents.close()


_service: Optional[Workbench] = None


def initialize(directory: Path, temp: Path) -> Workbench:
    """Bind runtime paths at extension startup; tests supply temporary directories."""
    global _service
    if _service is None:
        _service = Workbench(directory, temp)
    return _service


def service() -> Workbench:
    """Return the initialized service, without creating directories at node import."""
    if _service is None:
        raise ValueError("Prompt Workbench service is unavailable")
    return _service


def motion_key(job: Generation, shape: Any, identity: str) -> str:
    """Key stills by preparation graph revisions, VAE identity and context window."""
    inputs = {key: {k: v for k, v in entry.items() if k != "_meta"} for key, entry in job.graph.items() if key != job.node_id}
    return hashlib.sha256(
        json.dumps([inputs, list(shape), identity, job.options["context_length"], PROCESSING], sort_keys=True, default=str).encode()
    ).hexdigest()
