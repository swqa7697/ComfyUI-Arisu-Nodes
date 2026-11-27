"""Media jobs for video segments: backend detection, probing, supervised export and join previews."""

from __future__ import annotations

import collections
import json
import logging
import math
import os
import posixpath
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any, Callable, Deque, Dict, FrozenSet, Iterable, List, Mapping, Optional, OrderedDict, Tuple

import av

from ..worker import worker_command, worker_environment
from .http import Busy
from .media import StaleResource, UnsupportedMedia, revision_for, source_path
from .video import (
    CODECS,
    Capabilities,
    Correction,
    EditDocument,
    Entry,
    ExportPlan,
    ExportRequest,
    OutputSpec,
    Probe,
    Source,
    parse_correction,
    plan_export,
    plan_payload,
    probe_from_json,
    refusal,
    sequence_record,
    suggest_correction,
)
from .video_ffmpeg import (
    concat_script,
    decode_samples_argv,
    export_argv,
    framecrc_argv,
    join_frames_argv,
    parse_decoders,
    parse_encoders,
    parse_ffprobe,
    parse_framecrc,
    probe_argv,
)
from .video_store import discard_workspace, export_workspace, find_export, publish_export, reading, take_companion

logger = logging.getLogger(__name__)
PROBE_LIMIT = 64 * 1024 * 1024
_CAPABILITIES: Dict[str, Tuple[FrozenSet[str], FrozenSet[str], str]] = {}
_CAPABILITY_LOCK = threading.Lock()
_PROBES: OrderedDict[Tuple[str, str, str], Optional[Probe]] = OrderedDict()
_PROBE_LOCK = threading.Lock()
_PROBE_CACHE = 2048


class MediaToolError(RuntimeError):
    """A media process failed; its diagnostic output is in the server log."""


class EncoderUnavailable(ValueError):
    """The selected codec has no usable encoder in the active backend."""


@dataclass(frozen=True)
class Tools:
    """The media backend of this service: absolute executables, or none for the PyAV fallback."""

    ffmpeg: Optional[str]
    ffprobe: Optional[str]
    encoders: FrozenSet[str]
    version: str
    decoders: Optional[FrozenSet[str]] = None

    @property
    def backend(self) -> str:
        return "ffmpeg" if self.ffmpeg else "pyav"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(self.backend, self.encoders, self.decoders)


def collect(argv: List[str], limit: int, timeout: float, payload: Optional[bytes] = None) -> bytes:
    """Run a fixed command in the worker environment and return bounded stdout; stderr goes to the log on failure."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL if payload is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=worker_environment(),
    )
    errors: Deque[bytes] = collections.deque(maxlen=64)
    drain = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
    drain.start()
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    try:
        if payload is not None:
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except BrokenPipeError:
                pass
        output = process.stdout.read(limit + 1)
        if len(output) > limit:
            process.kill()
        code = process.wait()
    finally:
        timer.cancel()
        process.kill()
        process.wait()
        drain.join()
        process.stdout.close()
        process.stderr.close()
    if code != 0 or len(output) > limit:
        logger.warning("media tool failed (%s): %s", code, b"".join(errors).decode("utf-8", "replace")[-4000:])
        raise MediaToolError("media tool failed; see the server log")
    return output


def _pyav_encoder(name: str) -> bool:
    try:
        av.codec.Codec(name, "w")
    except ValueError:
        return False
    return True


def _pyav_encoders() -> FrozenSet[str]:
    return frozenset(name for spec in CODECS.values() for name in spec.encoders if _pyav_encoder(name))


def detect_tools() -> Tools:
    """Find the service's system FFmpeg; the executables are resolved here because workers run with a minimal PATH.

    Without the executable the PyAV libraries are the backend, and only their encoders are offered.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return Tools(None, None, _pyav_encoders(), "PyAV " + av.__version__)
    with _CAPABILITY_LOCK:
        if ffmpeg not in _CAPABILITIES:
            encoders = collect([ffmpeg, "-hide_banner", "-encoders"], 1024 * 1024, 30).decode("utf-8", "replace")
            decoders = collect([ffmpeg, "-hide_banner", "-decoders"], 1024 * 1024, 30).decode("utf-8", "replace")
            version = collect([ffmpeg, "-hide_banner", "-version"], 1024 * 1024, 30).decode("utf-8", "replace")
            label = version.splitlines()[0].replace("ffmpeg version ", "").split(" ")[0]
            _CAPABILITIES[ffmpeg] = (parse_encoders(encoders), parse_decoders(decoders), label)
        encoders, decoders, version = _CAPABILITIES[ffmpeg]
    return Tools(ffmpeg, shutil.which("ffprobe"), encoders, version, decoders)


def log_fallback(job: str, codec: str):
    """Every job on the fallback path says so, with its reason, backend and codec."""
    logger.warning("system ffmpeg executable not found; %s uses the PyAV %s backend with codec %s", job, av.__version__, codec)


def worker(task: Dict[str, Any], limit: int = PROBE_LIMIT, timeout: float = 120) -> Dict[str, Any]:
    """Run one PyAV task in the isolated media worker and return its JSON answer."""
    output = collect(worker_command("video"), limit, timeout, json.dumps(task).encode())
    return json.loads(output.decode("utf-8").strip().splitlines()[-1])


def select_encoder(tools: Tools, codec: str) -> str:
    """The preferred available encoder for a codec, or a precise refusal that keeps the user's codec choice."""
    wanted = CODECS[codec].encoders
    found = next((name for name in wanted if name in tools.encoders), None)
    if found is None:
        raise EncoderUnavailable(f"this FFmpeg build has no {codec} encoder ({' or '.join(wanted)})")
    return found


def probe_path(path: str, tools: Tools) -> Probe:
    """Measure one already contained file. Without ffprobe, native FFmpeg supplies timing but no copy evidence."""
    try:
        if tools.ffprobe and tools.ffmpeg:
            return parse_ffprobe(collect(probe_argv(tools.ffprobe, path), PROBE_LIMIT, 120).decode("utf-8", "replace"))
        if tools.ffmpeg:
            return parse_framecrc(collect(framecrc_argv(tools.ffmpeg, path), PROBE_LIMIT, 120).decode("utf-8", "replace"))
        return probe_from_json(worker({"task": "probe", "path": path}))
    except (MediaToolError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise UnsupportedMedia("unsupported or incomplete media") from error


def count_samples(path: str, channels: int, tools: Tools) -> int:
    """Count the samples a decoder delivers from the first audio track, after container trimming."""
    if tools.ffmpeg is None:
        return int(worker({"task": "samples", "path": path})["samples"])
    process = subprocess.Popen(
        decode_samples_argv(tools.ffmpeg, path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=worker_environment(),
    )
    total = 0
    try:
        for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
            total += len(chunk)
        code = process.wait()
    finally:
        process.kill()
        process.wait()
        process.stdout.close()
    if code != 0:
        raise MediaToolError("media tool failed; see the server log")
    return total // (4 * channels)


def describe_source(roots: Mapping[str, str], root: str, path: str, tools: Tools) -> Source:
    """Measure a contained video and read its take record. The stat fingerprint only keys the probe cache."""
    if not path:
        return Source("missing")
    try:
        absolute = source_path(roots, root, path)
        current = revision_for(os.stat(absolute))
    except (OSError, ValueError, TypeError):
        return Source("missing")
    key = (absolute, current, tools.backend + str(bool(tools.ffprobe)))
    with _PROBE_LOCK:
        known = key in _PROBES
        probe = _PROBES.get(key)
        if known:
            _PROBES.move_to_end(key)
    if not known:
        try:
            probe = probe_path(absolute, tools)
        except UnsupportedMedia:
            # An unusable file is remembered for this revision, so a slow failure is not repeated on every listing.
            probe = None
        with _PROBE_LOCK:
            _PROBES[key] = probe
            while len(_PROBES) > _PROBE_CACHE:
                _PROBES.popitem(last=False)
    if probe is None:
        return Source("unusable", absolute)
    if probe.video is None:
        return Source("unusable", absolute)
    record, pcm, lost = take_companion(roots["output"], path) if root == "output" else (None, None, False)
    return Source("ok", absolute, probe, record, pcm, lost)


def run_supervised(
    argv: List[str], check: Callable[[], None], progress: Callable[[int], None], deadline: float, payload: Optional[bytes] = None
):
    """Run one media process to its end under a deadline, reporting ``frame=`` progress; ``check`` may raise to stop it."""
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL if payload is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=worker_environment(),
    )
    errors: Deque[bytes] = collections.deque(maxlen=64)

    def follow():
        for line in process.stdout:
            if line.startswith(b"frame="):
                try:
                    progress(int(line[6:]))
                except ValueError:
                    continue

    threads = [threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True), threading.Thread(target=follow, daemon=True)]
    for thread in threads:
        thread.start()
    code: Optional[int] = None
    limit = time.monotonic() + deadline
    try:
        if payload is not None:
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except BrokenPipeError:
                pass
        while code is None:
            check()
            if time.monotonic() > limit:
                raise MediaToolError("media job exceeded its deadline")
            try:
                code = process.wait(0.1)
            except subprocess.TimeoutExpired:
                continue
    finally:
        process.kill()
        process.wait()
        for thread in threads:
            thread.join()
        process.stdout.close()
        process.stderr.close()
    if code != 0:
        logger.warning("media tool failed (%s): %s", code, b"".join(errors).decode("utf-8", "replace")[-4000:])
        raise MediaToolError("video export failed; see the server log")


def run_export(
    plan: ExportPlan,
    tools: Tools,
    workspace: str,
    output: str,
    check: Callable[[], None],
    progress: Callable[[int], None],
    fast: bool = False,
):
    """Write the planned film to ``output`` in one supervised process: native FFmpeg, or the isolated PyAV worker."""
    deadline = 600 + plan.frames * 2.0
    if tools.ffmpeg is None:
        task = {"task": "export", "plan": plan_payload(plan), "output": output}
        run_supervised(worker_command("video"), check, progress, deadline, json.dumps(task).encode())
        return
    script = os.path.join(workspace, "video.ffconcat")
    listed = plan.video_operation == "copy" and plan.audio_operation != "copy"
    try:
        if listed:
            with open(script, "x", encoding="utf-8") as handle:
                handle.write(concat_script(plan))
        run_supervised(export_argv(tools.ffmpeg, plan, script, output, fast), check, progress, deadline)
    finally:
        if listed and os.path.lexists(script):
            os.unlink(script)


def validate_export(path: str, plan: ExportPlan, tools: Tools):
    """Measure the finished film against the plan before it may be published."""
    probe = probe_path(path, tools)
    video, audio = probe.video, probe.audio
    good = video is not None and video.frames == plan.frames and video.start == 0 and video.constant
    if good and plan.audio_operation is not None:
        good = audio is not None and audio.start == 0
        if good and plan.audio_operation == "encode":
            good = count_samples(path, plan.channels, tools) == plan.samples
    elif good:
        good = audio is None
    if not good:
        logger.warning("exported film failed validation: %s against %s frames and %s samples", probe, plan.frames, plan.samples)
        raise MediaToolError("the exported film does not match its plan; export with Choose codec and CRF instead")


def join_means(path: str, first: int, count: int, tools: Tools) -> List[Tuple[float, float, float]]:
    """Mean Y, Cb and Cr of consecutive frames, each as 0-1 of its 8-bit range."""
    if tools.ffmpeg is None:
        return [tuple(frame) for frame in worker({"task": "means", "path": path, "first": first, "count": count})["means"]]
    data = collect(join_frames_argv(tools.ffmpeg, path, first, count), 64 * 1024 * 1024, 120)
    plane = 64 * 36
    means = []
    for start in range(0, len(data) - len(data) % (plane * 3), plane * 3):
        y, cb, cr = (sum(data[start + index * plane : start + (index + 1) * plane]) / plane for index in range(3))
        means.append(((y - 16) / 219, (cb - 128) / 224, (cr - 128) / 224))
    return means


def feed(argv: List[str], chunks: Iterable[bytes], check: Callable[[], None]):
    """Pipe byte chunks to a fixed command; ``check`` may raise between chunks to stop it, and the child never outlives the call."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=worker_environment())
    errors: Deque[bytes] = collections.deque(maxlen=64)
    drain = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
    drain.start()
    code: Optional[int] = None
    try:
        try:
            for chunk in chunks:
                check()
                process.stdin.write(chunk)
            process.stdin.close()
        except BrokenPipeError:
            pass
        while code is None:
            check()
            try:
                code = process.wait(0.1)
            except subprocess.TimeoutExpired:
                continue
    finally:
        process.kill()
        process.wait()
        drain.join()
        if not process.stdin.closed:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        process.stderr.close()
    if code != 0:
        logger.warning("media tool failed (%s): %s", code, b"".join(errors).decode("utf-8", "replace")[-4000:])
        raise MediaToolError("video encoding failed; see the server log")


class ExportRefused(ValueError):
    """The edit cannot be exported as it stands; the message says what to resolve."""


def describe_entries(roots: Mapping[str, str], document: EditDocument, tools: Tools) -> Dict[str, Source]:
    """Measure every included entry of an edit list."""
    return {entry.id: describe_source(roots, entry.root, entry.path, tools) for entry in document.entries if entry.included}


def export_film(
    roots: Mapping[str, str],
    request: ExportRequest,
    document: EditDocument,
    job: str,
    tools: Tools,
    check: Callable[[], None],
    progress: Callable[[int, int], None],
) -> Dict[str, Any]:
    """Export one version of a film and return its record; the same job returns its published export.

    The snapshot is the validated document. Source locations are checked before the media process opens them.
    The version directory appears only when the film and its record are complete.
    """
    output_root = roots["output"]
    published = find_export(output_root, request.project, request.name, job)
    if published is not None:
        return published
    sources = describe_entries(roots, document, tools)
    plan = plan_export(document, sources, request, tools.capabilities)
    if not plan.ready:
        raise ExportRefused(refusal(plan))
    if tools.ffmpeg is None:
        log_fallback("export", plan.codec)
    inputs = {(entry.root, entry.path): sources[entry.id].path for entry in document.entries if entry.included}
    locations = {}
    for entry in plan.entries:
        if entry.audio == "pcm":
            path = sources[entry.id].record["audio"]["pcm"]["path"]
            inputs[("output", path)] = entry.audio_path
            locations[entry.id] = {"path": path}
    try:
        workspace = export_workspace(output_root, request.project, job)
    except FileExistsError as error:
        raise ExportRefused("this export is already running") from error
    try:
        film = os.path.join(workspace, "film.mp4")
        with reading(sorted(set(inputs.values()))):
            for (root, path), resolved in inputs.items():
                if source_path(roots, root, path) != resolved:
                    raise ExportRefused("a source no longer resolves to its selected location")
            run_export(plan, tools, workspace, film, check, lambda frame: progress(frame, plan.frames))
        validate_export(film, plan, tools)

        def build(counter: int, named: str) -> Dict[str, Any]:
            info = os.stat(named)
            label = f"{request.name}_{counter:05}"
            return sequence_record(
                job=job,
                created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                request=request,
                counter=counter,
                film={
                    "root": "output",
                    "path": posixpath.join(request.project, "exports", label, label + ".mp4"),
                    "size": info.st_size,
                },
                backend={"name": tools.backend, "version": tools.version, "probe": "ffprobe" if tools.ffprobe else tools.backend},
                plan=plan,
                document=document,
                locations=locations,
            )

        return publish_export(workspace, request.name, film, build)
    except BaseException:
        discard_workspace(workspace)
        raise


PREVIEW_SECONDS = 3
PREVIEW_HEIGHT = 720
PREVIEW_CLIP_LIMIT = 64 * 1024 * 1024
PREVIEW_MEASURED = 12
PREVIEW_KEPT = 4


@dataclass
class PreviewJob:
    """One looped join preview: variant ``a`` is the direct cut, ``b`` the candidate correction or fade."""

    directory: str
    state: str = "running"
    progress: int = 0
    error: Optional[str] = None
    variants: List[str] = field(default_factory=list)
    cut: float = 0.0
    signalling: Dict[str, Any] = field(default_factory=dict)
    suggestion: Optional[Dict[str, Any]] = None
    touched: float = field(default_factory=time.monotonic)
    cancelled: bool = False


class PreviewCancelled(Exception):
    """The preview was released while its worker was running."""


class PreviewManager:
    """Run one bounded join preview at a time in ComfyUI's temp directory and expire idle results."""

    def __init__(self, temp: str, deadline: float = 120.0, idle: float = 1800.0):
        self.temp, self.deadline, self.idle = temp, deadline, idle
        self.jobs: Dict[str, PreviewJob] = {}
        self._worker = threading.Lock()
        self._lock = threading.Lock()

    def _sweep(self):
        with self._lock:
            finished = sorted((key for key, job in self.jobs.items() if job.state != "running"), key=lambda key: self.jobs[key].touched)
            expired = [key for key in finished if time.monotonic() - self.jobs[key].touched > self.idle]
            # Finished previews are few and short-lived: beyond the limit the least recently used ones go first.
            expired += [key for key in finished[: max(0, len(finished) - PREVIEW_KEPT)] if key not in expired]
            for key in expired:
                shutil.rmtree(self.jobs.pop(key).directory, ignore_errors=True)

    def start(
        self, roots: Mapping[str, str], outgoing: Mapping[str, Any], incoming: Mapping[str, Any], join: Mapping[str, Any], tools: Tools
    ) -> str:
        """Plan both variants from current files and start the worker; a busy worker refuses instead of queueing."""
        self._sweep()
        sides = []
        for side in (outgoing, incoming):
            if not isinstance(side, dict) or set(side) - {"revision"} != {"root", "path", "range"}:
                raise ValueError("invalid join preview request")
            source = describe_source(roots, side["root"], side["path"], tools)
            if source.state != "ok":
                raise StaleResource("a join source is missing or unusable")
            sides.append((side, source))
        if (
            not isinstance(join, dict)
            or set(join) != {"correction", "fade"}
            or type(join["fade"]) is not int
            or not 0 <= join["fade"] <= 50
        ):
            raise ValueError("invalid join preview request")
        (left, before), (right, after) = sides
        rate = before.probe.video.fps
        window = math.ceil(PREVIEW_SECONDS * rate)
        ranges = []
        for side, source, tail in ((left, before, True), (right, after, False)):
            first, last = side["range"] or (0, source.probe.video.frames)
            if type(first) is not int or type(last) is not int or not 0 <= first < last <= source.probe.video.frames:
                raise ValueError("invalid join preview range")
            ranges.append((max(first, last - window), last) if tail else (first, min(last, first + window)))
        scale = min(1.0, PREVIEW_HEIGHT / before.probe.video.height)
        width, height = (max(2, round(size * scale / 2) * 2) for size in (before.probe.video.width, before.probe.video.height))
        sounds = [source.probe.audio for source in (before, after) if source.probe.audio is not None]
        spec = OutputSpec(
            width,
            height,
            rate,
            max((sound.rate for sound in sounds), default=48000),
            min(2, max((sound.channels for sound in sounds), default=2)),
        )
        applied = join["correction"]
        if applied is not None:
            if not isinstance(applied, dict):
                raise ValueError("invalid join preview correction")
            # A candidate is held to the same bounds as a stored correction, on the preview's own slice of the join.
            basis = {
                "prev_source": f"{left['root']}:{left['path']}",
                "prev_end": ranges[0][1],
                "source": f"{right['root']}:{right['path']}",
                "start": ranges[1][0],
            }
            applied = parse_correction({**applied, "basis": basis})

        def plan(correction: Optional[Correction], fade: int) -> ExportPlan:
            entries = tuple(
                Entry(
                    str(uuid.uuid4()),
                    "file",
                    "",
                    "",
                    side["root"],
                    side["path"],
                    True,
                    span,
                    "auto",
                    fix,
                    fade if fix or index else 0,
                )
                for index, (side, source, span, fix) in enumerate(((left, before, ranges[0], None), (right, after, ranges[1], correction)))
            )
            document = EditDocument(spec, entries, {})
            sources = {entry.id: source for entry, source in zip(entries, (before, after))}
            made = plan_export(document, sources, ExportRequest("preview", "join", "encode", "h264", 23), tools.capabilities)
            if not made.ready:
                raise ValueError(refusal(made))
            return made

        plans = {"a": plan(None, 0)}
        if applied is not None or join["fade"]:
            plans["b"] = plan(applied, join["fade"])
        if not self._worker.acquire(blocking=False):
            raise Busy("another join preview is running")
        try:
            os.makedirs(self.temp, exist_ok=True)
            job = PreviewJob(tempfile.mkdtemp(prefix="arisu-join-", dir=self.temp))
            colors = [source.probe.video.color for source in (before, after)]
            keys = ("range", "matrix", "primaries", "transfer")
            job.signalling = {
                "match": colors[0] == colors[1],
                "outgoing": dict(zip(keys, colors[0])),
                "incoming": dict(zip(keys, colors[1])),
            }
            job.cut = float(Fraction(ranges[0][1] - ranges[0][0]) / rate)
            handle = str(uuid.uuid4())
            with self._lock:
                self.jobs[handle] = job
            measured = (before.path, max(0, ranges[0][1] - PREVIEW_MEASURED), min(PREVIEW_MEASURED, ranges[0][1]), after.path, ranges[1][0])
            threading.Thread(target=self._run, args=(job, plans, measured, tools), daemon=True).start()
        except BaseException:
            self._worker.release()
            raise
        return handle

    def _run(self, job: PreviewJob, plans: Dict[str, ExportPlan], measured: Tuple[str, int, int, str, int], tools: Tools):
        limit = time.monotonic() + self.deadline

        def check():
            if job.cancelled:
                raise PreviewCancelled
            if time.monotonic() > limit:
                raise MediaToolError("join preview exceeded its deadline")

        try:
            if tools.ffmpeg is None:
                log_fallback("join preview", "h264")
            total = sum(plan.frames for plan in plans.values())
            done = 0
            for name, plan in plans.items():
                target = os.path.join(job.directory, name + ".mp4")
                run_export(
                    plan,
                    tools,
                    job.directory,
                    target,
                    check,
                    lambda frame, base=done: setattr(job, "progress", min(99, (base + frame) * 100 // total)),
                    True,
                )
                if os.path.getsize(target) > PREVIEW_CLIP_LIMIT:
                    raise MediaToolError("join preview exceeded its size limit")
                done += plan.frames
                job.variants.append(name)
            if job.signalling["match"]:
                check()
                before, first, count, after, start = measured
                job.suggestion = suggest_correction(
                    join_means(before, first, count, tools), join_means(after, start, PREVIEW_MEASURED, tools)
                )
            job.progress, job.state = 100, "ready"
        except PreviewCancelled:
            job.state = "error"
        except Exception:
            logger.exception("join preview failed")
            job.state, job.error = "error", "join preview failed; see the server log"
        finally:
            job.touched = time.monotonic()
            # A job released while it ran has no owner left: its files go with it, whatever state it reached.
            if job.state != "ready" or job.cancelled:
                shutil.rmtree(job.directory, ignore_errors=True)
            self._worker.release()

    def get(self, handle: str) -> PreviewJob:
        """Look up a job and keep it alive; unknown and expired handles raise ``KeyError``."""
        self._sweep()
        with self._lock:
            job = self.jobs[handle]
        job.touched = time.monotonic()
        return job

    def release(self, handle: str):
        """Forget a job; a running worker stops and removes its own files before the guard is freed."""
        with self._lock:
            job = self.jobs.pop(handle, None)
        if job is not None:
            job.cancelled = True
            if job.state != "running":
                shutil.rmtree(job.directory, ignore_errors=True)

    def close(self):
        """Stop every job at service shutdown."""
        for handle in list(self.jobs):
            self.release(handle)
