"""Video segment contracts: take prefixes, records, the edit document and the export plan. Standard library only."""

from __future__ import annotations

import json
import math
import posixpath
import re
import struct
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple, Union

from .core import expand_save_prefix, relative_path

DEFAULT_PROJECT = "arisu_video"
DEFAULT_CLIP = "clip"
COMPANION = ".arisu"
TAKE_RECORD = "take.json"
TAKE_AUDIO = "audio.wav"
VIDEO_SUFFIXES = ("mp4", "webm", "mov", "mkv")
RECORD_LIMIT = 64 * 1024
SEQUENCE_LIMIT = 4 * 1024 * 1024
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DIRECTOR_DIR = re.compile(rf"(?:(?:.+/)?director|arisu_director)/({_UUID.pattern})")
_TRANSITIONS = ("cut", "continuation")


@dataclass(frozen=True)
class CodecSpec:
    """One selectable target codec: its CRF scale, suggested preset and encoders in order of preference."""

    probe_name: str
    max_crf: int
    preset: int
    encoders: Tuple[str, ...]
    chroma: Tuple[str, ...]


CODECS: Dict[str, CodecSpec] = {
    "h264": CodecSpec("h264", 51, 18, ("libx264",), ("420", "422", "444")),
    "h265": CodecSpec("hevc", 51, 20, ("libx265",), ("420", "422", "444")),
    "av1": CodecSpec("av1", 63, 24, ("libsvtav1", "libaom-av1"), ("420",)),
}
# CreateVideo's colour choices as (primaries, transfer, matrix); the range is always limited.
COLOR_SPACES: Dict[str, Tuple[str, str, str]] = {
    "sRGB": ("bt709", "iec61966-2-1", "bt709"),
    "HDR": ("bt2020", "arib-std-b67", "bt2020nc"),
    "HDR PQ": ("bt2020", "smpte2084", "bt2020nc"),
}
LAYOUTS: Dict[int, str] = {1: "mono", 2: "stereo", 6: "5.1"}
AAC_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)
EDIT_LIMIT = 256 * 1024
MAX_ENTRIES = 512
MAX_INCLUDED = 100
MAX_FADE_MS = 50
EMPTY_EDIT = '{"version":1,"output":null,"entries":[]}'
_SOURCE_CODECS = {"h264": "h264", "hevc": "h265", "av1": "av1"}
_ENTRY_KEYS = {"id", "source", "take", "segment", "root", "path", "revision", "included", "range", "audio", "join"}
_CORRECTION_BOUNDS = {"luma_gain": (0.90, 1.10), "luma_offset": (-0.06, 0.06), "cb_offset": (-0.04, 0.04), "cr_offset": (-0.04, 0.04)}


@dataclass(frozen=True)
class TakeTarget:
    """Where one take is written: a directory relative to output, a filename stem and the owning project."""

    directory: str
    stem: str
    project: Optional[str]


@dataclass(frozen=True)
class VideoInfo:
    """Measured facts about one video stream."""

    codec: str
    profile: str
    tag: str
    width: int
    height: int
    sar: str
    pix_fmt: str
    fps: Fraction
    time_base: Fraction
    frames: int
    start: Fraction
    duration: Fraction
    constant: bool
    color: Tuple[str, str, str, str]
    extradata: str


@dataclass(frozen=True)
class AudioInfo:
    """Measured facts about one audio stream; ``samples`` is the valid count when known, else an estimate."""

    codec: str
    profile: str
    rate: int
    channels: int
    layout: str
    samples: int
    start: Fraction
    priming: int
    extradata: str


@dataclass(frozen=True)
class Probe:
    """One file's streams; ``evidence`` is false when the probe cannot support a packet-copy decision."""

    container: str
    video: Optional[VideoInfo]
    audio: Optional[AudioInfo]
    evidence: bool


def validate_encoding(codec: Any, crf: Any) -> CodecSpec:
    """Check a codec and the CRF on that encoder's own scale."""
    if not isinstance(codec, str) or codec not in CODECS:
        raise ValueError("codec must be h264, h265 or av1")
    spec = CODECS[codec]
    if type(crf) is not int or not 0 <= crf <= spec.max_crf:
        raise ValueError(f"crf for {codec} must be between 0 and {spec.max_crf}")
    return spec


def resolve_take_prefix(
    project_prefix: str, clip_name: str, width: int, height: int, now: datetime, take: Optional[str] = None
) -> TakeTarget:
    """Choose the take location from the project inputs and optional Director take ID.

    Ordinary saves write ``P/videos/<clip>`` with ``arisu_video`` as the default project.
    Director saves write ``P/director/<take>/clip`` or ``arisu_director/<take>/clip`` without a project.
    """
    if not all(isinstance(value, str) for value in (project_prefix, clip_name)):
        raise TypeError("video prefixes must be strings")
    project = expand_save_prefix(project_prefix, width, height, now) if project_prefix.strip() else None
    if take is not None:
        if not isinstance(take, str) or not _UUID.fullmatch(take):
            raise ValueError("invalid Director take ID")
        directory = f"{project}/director/{take}" if project else f"arisu_director/{take}"
        return TakeTarget(directory, DEFAULT_CLIP, project)
    else:
        clip = clip_name.strip() or DEFAULT_CLIP
        if "/" in clip or "\\" in clip:
            raise ValueError("clip_name must be one filename segment")
        project = project or DEFAULT_PROJECT
        full = expand_save_prefix(f"{project}/videos/{clip}", width, height, now)
    directory, stem = posixpath.split(full)
    return TakeTarget(directory, stem, project)


def director_take_id(directory: str) -> Optional[str]:
    """The Director take ID when a directory follows either Director layout; the location is the only authority."""
    match = _DIRECTOR_DIR.fullmatch(directory)
    return match.group(1) if match else None


def parse_take_context(text: Any) -> Dict[str, Optional[str]]:
    """Read the optional provenance a Director render attaches to its saver."""
    empty: Dict[str, Optional[str]] = {"take": None, "segment": None, "predecessor": None, "transition": None}
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError("invalid take context")
    if not text.strip():
        return empty
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("invalid take context") from error
    if not isinstance(value, dict) or set(value) != set(empty):
        raise ValueError("invalid take context")
    take = value["take"]
    if not isinstance(take, str) or not _UUID.fullmatch(take):
        raise ValueError("invalid take context")
    segment, predecessor, transition = value["segment"], value["predecessor"], value["transition"]
    if not isinstance(segment, str) or not 0 < len(segment) <= 128 or transition not in _TRANSITIONS:
        raise ValueError("invalid take context")
    if predecessor is not None and (not isinstance(predecessor, str) or not _UUID.fullmatch(predecessor)):
        raise ValueError("invalid take context")
    return {"take": take, "segment": segment, "predecessor": predecessor, "transition": transition}


def exact_rate(rate: Any) -> Fraction:
    """A rational frame rate without float noise: 23.976 stays 2997/125 and 24000/1001 stays itself."""
    value = Fraction(rate).limit_denominator(1001000)
    if not 1 <= value <= 240:
        raise ValueError("frame rate must be between 1 and 240")
    return value


def sample_boundary(frames: int, fps: Fraction, rate: int) -> int:
    """The audio sample index at a cumulative frame count, rounded to nearest with ties to even."""
    return round(Fraction(frames * rate) / fps)


def wav_header(channels: int, rate: int, samples: int) -> bytes:
    """A RIFF header for interleaved 32-bit float PCM; the stdlib ``wave`` module refuses this format."""
    block = channels * 4
    data = samples * block
    if not 0 < channels <= 8 or rate <= 0 or samples < 0 or data > 0xFFFFFFFF - 50:
        raise ValueError("audio does not fit one PCM companion file")
    fmt = struct.pack("<HHIIHH", 3, channels, rate, rate * block, block, 32)
    fact = struct.pack("<I", samples)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<I", len(fact)) + fact + b"data"
    return b"RIFF" + struct.pack("<I", len(body) + 4 + data) + body + struct.pack("<I", data)


def ffmetadata(values: Mapping[str, str]) -> str:
    """Container tags as an FFmpeg metadata file, so large workflows never meet an argument-length limit."""

    def escape(text: str) -> str:
        return re.sub(r"([=;#\\\n\[])", r"\\\1", text.replace("\r\n", "\n").replace("\x00", ""))

    return ";FFMETADATA1\n" + "".join(f"{escape(key)}={escape(value)}\n" for key, value in values.items())


def _fraction(value: Fraction) -> List[int]:
    return [value.numerator, value.denominator]


def take_record(
    *,
    take: str,
    created: str,
    project: Optional[str],
    context: Mapping[str, Optional[str]],
    path: str,
    revision: str,
    size: int,
    video: VideoInfo,
    encoder: str,
    crf: int,
    audio: Optional[Dict[str, Any]],
    backend: str,
) -> Dict[str, Any]:
    """The published description of one take; locations are relative to the output root."""
    directory = posixpath.dirname(path)
    return {
        "version": 1,
        "kind": "arisu.take",
        "take": take,
        "created": created,
        "origin": "director" if director_take_id(directory) else "ordinary",
        "project": project,
        "segment": context["segment"],
        "predecessor": context["predecessor"],
        "transition": context["transition"],
        "upstream_trim": None,
        "video": {
            "root": "output",
            "path": path,
            "revision": revision,
            "size": size,
            "frames": video.frames,
            "fps": _fraction(video.fps),
            "time_base": _fraction(video.time_base),
            "vfr": not video.constant,
            "width": video.width,
            "height": video.height,
            "codec": video.codec,
            "encoder": encoder,
            "crf": crf,
            "pix_fmt": video.pix_fmt,
            "color": dict(zip(("range", "matrix", "primaries", "transfer"), video.color)),
        },
        "audio": audio,
        "backend": backend,
    }


def _positive(value: Any, limit: int = 1 << 40) -> bool:
    return type(value) is int and 0 < value <= limit


def _pair(value: Any) -> Fraction:
    if not isinstance(value, list) or len(value) != 2 or not all(_positive(part) for part in value):
        raise ValueError("invalid take record")
    return Fraction(value[0], value[1])


def read_take_record(text: str) -> Dict[str, Any]:
    """Validate a take record read from disk; the file is data and may have been edited by anyone."""
    if len(text.encode("utf-8")) > RECORD_LIMIT:
        raise ValueError("invalid take record")
    try:
        record = json.loads(text)
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid take record") from error
    if not isinstance(record, dict) or record.get("version") != 1 or record.get("kind") != "arisu.take":
        raise ValueError("invalid take record")
    video, audio, take = record.get("video"), record.get("audio"), record.get("take")
    if not isinstance(take, str) or not _UUID.fullmatch(take) or not isinstance(video, dict):
        raise ValueError("invalid take record")
    if video.get("root") != "output" or not isinstance(video.get("revision"), str):
        raise ValueError("invalid take record")
    relative_path(video.get("path"))
    _pair(video.get("fps"))
    if not all(_positive(video.get(key)) for key in ("frames", "width", "height")) or not isinstance(video.get("codec"), str):
        raise ValueError("invalid take record")
    for key in ("segment", "predecessor", "transition"):
        if record.get(key) is not None and (not isinstance(record[key], str) or len(record[key]) > 128):
            raise ValueError("invalid take record")
    if audio is not None:
        if not isinstance(audio, dict) or not all(_positive(audio.get(key)) for key in ("rate", "channels", "samples")):
            raise ValueError("invalid take record")
        pcm = audio.get("pcm")
        if pcm is not None:
            if not isinstance(pcm, dict) or pcm.get("root") != "output" or not isinstance(pcm.get("revision"), str):
                raise ValueError("invalid take record")
            relative_path(pcm.get("path"))
    return record


def take_summary(record: Mapping[str, Any]) -> Dict[str, Any]:
    """The fields a panel shows for one take. No ``id``, ``filename`` or ``type`` keys: ComfyUI rewrites those in ui output."""
    video, audio = record["video"], record["audio"]
    fps = _pair(video["fps"])
    return {
        "take": record["take"],
        "origin": record.get("origin", "ordinary"),
        "root": video["root"],
        "path": video["path"],
        "revision": video["revision"],
        "frames": video["frames"],
        "fps": video["fps"],
        "duration": float(Fraction(video["frames"]) / fps),
        "width": video["width"],
        "height": video["height"],
        "codec": video["codec"],
        "audio": None
        if audio is None
        else {"rate": audio["rate"], "channels": audio["channels"], "samples": audio["samples"], "pcm": audio.get("pcm") is not None},
        "segment": record.get("segment"),
        "predecessor": record.get("predecessor"),
        "transition": record.get("transition"),
    }


def new_take_id() -> str:
    """A stable identifier for a take that is not owned by a Director directory."""
    return str(uuid.uuid4())


def embedded_samples(frames: int, fps: Fraction, rate: int, samples: int) -> int:
    """The audio kept in the playable file: no more than the picture's duration, as the stock saver does."""
    return min(samples, math.ceil(Fraction(frames * rate) / fps))


@dataclass(frozen=True)
class Correction:
    """A bounded colour adjustment for the opening frames of one take, tied to the join it was approved for."""

    luma_gain: float
    luma_offset: float
    cb_offset: float
    cr_offset: float
    taper: int
    basis: Tuple[str, int, str, int]


@dataclass(frozen=True)
class Entry:
    """One row of the edit list; ``correction`` and ``fade`` belong to the join before it."""

    id: str
    source: str
    take: str
    segment: str
    root: str
    path: str
    revision: str
    included: bool
    range: Optional[Tuple[int, int]]
    audio: str
    correction: Optional[Correction]
    fade: int


@dataclass(frozen=True)
class OutputSpec:
    """The common film format a user confirmed when the inputs differ."""

    width: int
    height: int
    fps: Fraction
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class EditDocument:
    """A validated edit list; ``raw`` is the canonical JSON form kept in export records."""

    output: Optional[OutputSpec]
    entries: Tuple[Entry, ...]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ExportRequest:
    """The node inputs of one export."""

    project: str
    name: str
    encoding: str
    codec: str
    crf: int


@dataclass(frozen=True)
class Capabilities:
    """What the active backend can do; ``decoders`` is ``None`` when the backend cannot list them."""

    backend: str
    encoders: FrozenSet[str]
    decoders: Optional[FrozenSet[str]] = None


@dataclass(frozen=True)
class PcmSource:
    """A verified float PCM companion."""

    path: str
    rate: int
    channels: int
    samples: int
    revision: str = ""


@dataclass(frozen=True)
class Source:
    """The server's current view of one entry's file."""

    state: str
    path: str = ""
    revision: str = ""
    probe: Optional[Probe] = None
    record: Optional[Mapping[str, Any]] = None
    pcm: Optional[PcmSource] = None
    pcm_lost: bool = False


@dataclass(frozen=True)
class PlannedEntry:
    """One included entry on the output timeline; audio offsets are in output-rate samples."""

    id: str
    path: str
    first: int
    last: int
    frames: Tuple[int, int]
    samples: Tuple[int, int]
    whole: bool
    by_time: bool
    start_time: Fraction
    end_time: Fraction
    audio: str
    audio_path: str
    audio_offset: int
    audio_delta: int
    correction: Optional[Correction]
    fade_in: int
    fade_out: int


@dataclass(frozen=True)
class ExportPlan:
    """Everything preflight shows and export executes."""

    states: Tuple[Tuple[str, str, Optional[str]], ...]
    entries: Tuple[PlannedEntry, ...] = ()
    fps: Fraction = Fraction(24)
    width: int = 0
    height: int = 0
    pix_fmt: str = "yuv420p"
    color: Tuple[str, str, str, str] = ("unknown", "unknown", "unknown", "unknown")
    sample_rate: int = 0
    channels: int = 0
    frames: int = 0
    samples: int = 0
    video_operation: str = "encode"
    video_reason: str = ""
    codec: str = "h264"
    encoder: Optional[str] = None
    crf: Optional[int] = None
    audio_operation: Optional[str] = None
    audio_reason: str = ""
    needs: Tuple[Dict[str, Any], ...] = ()
    warnings: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        """True when export can run as planned."""
        return bool(self.entries) and not self.needs and not self.errors and all(state == "ok" for _, state, _ in self.states)


def _bad(detail: str) -> ValueError:
    return ValueError(f"invalid edit list: {detail}")


def _frame_pair(value: Any) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2 or not all(type(part) is int for part in value) or not 0 <= value[0] < value[1]:
        raise _bad("frame interval")
    return value[0], value[1]


def parse_correction(value: Any) -> Optional[Correction]:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {*_CORRECTION_BOUNDS, "taper", "basis"}:
        raise _bad("colour correction")
    numbers = []
    for key, (low, high) in _CORRECTION_BOUNDS.items():
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise _bad(f"colour correction {key} outside {low:g} to {high:g}")
        numbers.append(float(number))
    basis = value["basis"]
    if type(value["taper"]) is not int or not 1 <= value["taper"] <= 96 or not isinstance(basis, dict):
        raise _bad("colour correction taper")
    if set(basis) != {"prev_revision", "prev_end", "revision", "start"}:
        raise _bad("colour correction basis")
    if not all(isinstance(basis[key], str) for key in ("prev_revision", "revision")) or not all(
        type(basis[key]) is int for key in ("prev_end", "start")
    ):
        raise _bad("colour correction basis")
    return Correction(*numbers, value["taper"], (basis["prev_revision"], basis["prev_end"], basis["revision"], basis["start"]))


def _entry(value: Any) -> Entry:
    if not isinstance(value, dict) or set(value) != _ENTRY_KEYS:
        raise _bad("entry fields")
    texts = {key: value[key] for key in ("id", "source", "take", "segment", "root", "path", "revision")}
    if not all(isinstance(text, str) and len(text) <= 1024 and "\x00" not in text for text in texts.values()):
        raise _bad("entry text")
    join = value["join"]
    if not _UUID.fullmatch(texts["id"]) or texts["source"] not in ("take", "director", "file") or type(value["included"]) is not bool:
        raise _bad("entry identity")
    if value["audio"] not in ("auto", "embedded", "none") or not isinstance(join, dict) or set(join) != {"correction", "fade"}:
        raise _bad("entry audio or join")
    if type(join["fade"]) is not int or not 0 <= join["fade"] <= MAX_FADE_MS:
        raise _bad(f"fade outside 0 to {MAX_FADE_MS} ms")
    # An entry that lost its location on import stays in the list until the user rebinds it.
    path = relative_path(texts["path"]) if texts["path"] else ""
    return Entry(
        texts["id"],
        texts["source"],
        texts["take"],
        texts["segment"],
        texts["root"],
        path,
        texts["revision"],
        value["included"],
        _frame_pair(value["range"]),
        value["audio"],
        parse_correction(join["correction"]),
        join["fade"],
    )


def _output(value: Any) -> Optional[OutputSpec]:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"width", "height", "fps", "sample_rate", "channels"}:
        raise _bad("output format")
    width, height = value["width"], value["height"]
    if not all(type(size) is int and 2 <= size <= 8192 and size % 2 == 0 for size in (width, height)):
        raise _bad("output size must be even and at most 8192")
    if value["sample_rate"] not in AAC_RATES or value["channels"] not in LAYOUTS:
        raise _bad("output audio format")
    try:
        fps = exact_rate(_pair(value["fps"]))
    except ValueError as error:
        raise _bad("output frame rate") from error
    return OutputSpec(width, height, fps, value["sample_rate"], value["channels"])


def parse_edit(value: Union[str, Mapping[str, Any]]) -> EditDocument:
    """Validate the workflow's edit list, from the widget text or a request body."""
    text = value if isinstance(value, str) else json.dumps(value)
    if len(text.encode("utf-8")) > EDIT_LIMIT:
        raise _bad("larger than 256 KiB")

    def unique(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise _bad("duplicate field")
        return result

    try:
        data = json.loads(text, object_pairs_hook=unique)
    except (RecursionError, json.JSONDecodeError) as error:
        raise _bad("not JSON") from error
    if not isinstance(data, dict) or set(data) != {"version", "output", "entries"} or data["version"] != 1:
        raise _bad("unsupported version")
    if not isinstance(data["entries"], list) or len(data["entries"]) > MAX_ENTRIES:
        raise _bad(f"more than {MAX_ENTRIES} entries")
    entries = tuple(_entry(item) for item in data["entries"])
    if len({entry.id for entry in entries}) != len(entries):
        raise _bad("duplicate entry ID")
    if sum(entry.included for entry in entries) > MAX_INCLUDED:
        raise _bad(f"more than {MAX_INCLUDED} included entries")
    return EditDocument(_output(data["output"]), entries, data)


def parse_export_request(project: Any, name: Any, encoding: Any, codec: Any, crf: Any) -> ExportRequest:
    """Validate the node inputs of an export; the project and name stay relative to output."""
    if not isinstance(project, str) or not isinstance(name, str):
        raise TypeError("project and export name must be strings")
    project = relative_path(project or DEFAULT_PROJECT)
    name = relative_path(name.strip() or "main")
    if "/" in name or name.startswith("."):
        raise ValueError("export name must be one filename segment")
    if encoding not in ("inherit", "encode"):
        raise ValueError("encoding must be inherit or encode")
    validate_encoding(codec, crf)
    return ExportRequest(project, name, encoding, codec, crf)


def _spec_json(spec: OutputSpec) -> Dict[str, Any]:
    return {
        "width": spec.width,
        "height": spec.height,
        "fps": _fraction(spec.fps),
        "sample_rate": spec.sample_rate,
        "channels": spec.channels,
    }


def _audio_choice(entry: Entry, source: Source) -> str:
    if entry.audio == "none":
        return "none"
    if entry.audio == "auto" and source.pcm is not None:
        return "pcm"
    return "embedded" if source.probe is not None and source.probe.audio is not None else "none"


def _copy_blocker(
    request: ExportRequest, backend: str, plan: List[PlannedEntry], videos: List[VideoInfo], sources: List[Source], spec: OutputSpec
) -> Optional[str]:
    """Why the video cannot be copied as packets, or ``None`` when every check passes."""
    first = videos[0]
    if request.encoding == "encode":
        return "an output codec and CRF were chosen"
    if backend != "ffmpeg":
        return "the PyAV fallback cannot copy packets"
    if not all(source.probe.evidence for source in sources):
        return "stream compatibility cannot be established without ffprobe"
    if any(entry.correction for entry in plan):
        return "a colour correction is applied"
    if any(
        entry.by_time or (video.width, video.height) != (spec.width, spec.height) or video.sar != "1:1"
        for entry, video in zip(plan, videos)
    ):
        return "sources are conformed to one frame size and rate"
    if any((entry.first, entry.last) != (0, video.frames) for entry, video in zip(plan, videos)):
        return "a frame-exact trim needs a video encode"
    settings = {(v.codec, v.profile, v.tag, v.pix_fmt, v.color, v.extradata, v.time_base) for v in videos}
    if len(settings) != 1:
        return "sources use different encoder settings"
    if not all("mp4" in source.probe.container for source in sources):
        return "a source is not in an MP4 container"
    # The packet-copy list is a text file of paths; a control character in a name must never become a directive.
    if any(ord(character) < 32 for entry in plan for character in entry.path):
        return "a source path cannot be listed for packet copy"
    if any(video.start != 0 or (Fraction(1) / spec.fps / video.time_base).denominator != 1 for video in videos):
        return "source timestamps are not on the frame grid"
    return None if first.codec in _SOURCE_CODECS else "the source codec cannot be kept"


def plan_export(document: EditDocument, sources: Mapping[str, Source], request: ExportRequest, caps: Capabilities) -> ExportPlan:
    """Decide the output timeline and the operation for each track from measured sources.

    Every entry occupies the difference between two cumulative boundaries, so rounding never accumulates.
    """
    included = [entry for entry in document.entries if entry.included]
    states: List[Tuple[str, str, Optional[str]]] = []
    for entry in included:
        source = sources[entry.id]
        message = None
        state = source.state
        if state == "ok" and source.probe is not None and source.probe.video is not None:
            first, last = entry.range or (0, source.probe.video.frames)
            if last > source.probe.video.frames:
                state, message = "unusable", "the frame interval is outside the video"
        states.append((entry.id, state, message))
    if not included:
        return ExportPlan((), errors=("select at least one video",))
    if any(state != "ok" for _, state, _ in states):
        return ExportPlan(tuple(states))

    found = [sources[entry.id] for entry in included]
    videos = [source.probe.video for source in found]
    choices = [_audio_choice(entry, source) for entry, source in zip(included, found)]
    needs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []

    lost = [entry.id for entry, source in zip(included, found) if entry.audio == "auto" and source.pcm is None and source.pcm_lost]
    if lost:
        needs.append({"kind": "switch_audio", "entries": lost, "suggested": {"audio": "embedded"}})
    formats = set()
    for choice, source in zip(choices, found):
        if choice == "pcm":
            formats.add((source.pcm.rate, source.pcm.channels))
        elif choice == "embedded":
            formats.add((source.probe.audio.rate, source.probe.audio.channels))
    natural = OutputSpec(
        videos[0].width,
        videos[0].height,
        videos[0].fps,
        max((rate for rate, _ in formats), default=0),
        max((channels for _, channels in formats), default=0),
    )
    uniform = len({(v.width, v.height, v.fps, v.constant) for v in videos}) == 1 and videos[0].constant and len(formats) <= 1
    # AAC carries only standard rates and layouts; anything else needs a confirmed output format.
    uniform = uniform and (not formats or (natural.sample_rate in AAC_RATES and natural.channels in LAYOUTS))
    odd = natural.width % 2 or natural.height % 2
    spec = document.output or natural
    if document.output is None and (not uniform or odd):
        suggested = OutputSpec(
            natural.width + natural.width % 2,
            natural.height + natural.height % 2,
            natural.fps,
            natural.sample_rate if natural.sample_rate in AAC_RATES else 48000,
            natural.channels if natural.channels in LAYOUTS else 2,
        )
        needs.append({"kind": "confirm_output", "entries": [entry.id for entry in included], "suggested": _spec_json(suggested)})
        spec = suggested
    silent = not formats
    rate, channels = (0, 0) if silent else (spec.sample_rate, spec.channels)

    planned: List[PlannedEntry] = []
    position = 0
    for index, (entry, source, video, choice) in enumerate(zip(included, found, videos, choices)):
        first, last = entry.range or (0, video.frames)
        by_time = not video.constant or video.fps != spec.fps
        whole = (first, last) == (0, video.frames)
        start_time = Fraction(first) / video.fps
        end_time = video.duration if whole else Fraction(last) / video.fps
        count = max(1, round((end_time - start_time) * spec.fps)) if by_time else last - first
        frames = (position, position + count)
        position += count
        samples = (0, 0) if silent else (sample_boundary(frames[0], spec.fps, rate), sample_boundary(frames[1], spec.fps, rate))
        slot = samples[1] - samples[0]
        offset = delta = 0
        audio_path = ""
        if not silent and choice != "none":
            available_rate = source.pcm.rate if choice == "pcm" else source.probe.audio.rate
            available = source.pcm.samples if choice == "pcm" else source.probe.audio.samples
            # Embedded sound is placed on the file's clock from zero, while the picture is re-zeroed to its first
            # frame: a picture that starts late must take that lead with it, or the sound would arrive early.
            lead = max(Fraction(0), video.start) if choice == "embedded" else Fraction(0)
            offset = round((lead + start_time) * rate)
            delta = round(Fraction(available * rate, available_rate)) - offset - slot
            audio_path = source.pcm.path if choice == "pcm" else source.path
            # Known tail padding and rounding are reconciled at the sample boundary; anything larger is reported.
            if abs(delta) > math.ceil(rate / spec.fps) + (1024 if choice == "embedded" else 0):
                warnings.append(f"entry {index + 1}: audio is {abs(delta)} samples {'longer' if delta > 0 else 'shorter'} than its picture")
        fade = 0 if index == 0 or silent else min(round(entry.fade * rate / 1000), slot // 2)
        correction = entry.correction if index else None
        if entry.correction is not None:
            previous = planned[-1] if planned else None
            basis = (included[index - 1].revision, previous.last, entry.revision, first) if previous else None
            if entry.correction.basis != basis:
                needs.append({"kind": "refresh_correction", "entries": [entry.id], "suggested": {}})
        if planned and fade:
            planned[-1] = replace(planned[-1], fade_out=min(fade, (planned[-1].samples[1] - planned[-1].samples[0]) // 2))
        planned.append(
            PlannedEntry(
                id=entry.id,
                path=source.path,
                first=first,
                last=last,
                frames=frames,
                samples=samples,
                whole=whole,
                by_time=by_time,
                start_time=start_time,
                end_time=end_time,
                audio="none" if silent else choice,
                audio_path=audio_path,
                audio_offset=offset,
                audio_delta=delta,
                correction=correction,
                fade_in=fade,
                fade_out=0,
            )
        )  # fmt: skip

    codecs = {_SOURCE_CODECS.get(video.codec) for video in videos}
    common = next(iter(codecs)) if len(codecs) == 1 else None
    codec, crf = request.codec, request.crf
    if request.encoding == "inherit":
        if common is None:
            needs.append(
                {
                    "kind": "choose_codec",
                    "entries": [entry.id for entry in included],
                    "suggested": {"codec": request.codec, "crf": request.crf},
                }
            )
        else:
            recorded = {(source.record or {}).get("video", {}).get("crf") for source in found}
            kept = next(iter(recorded)) if len(recorded) == 1 else None
            codec = common
            crf = kept if type(kept) is int and 0 <= kept <= CODECS[common].max_crf else CODECS[common].preset
    if common is not None or request.encoding == "encode":
        reason = _copy_blocker(request, caps.backend, planned, videos, found, spec)
    else:
        reason = "sources use different codecs"
    encoder = None
    pix_fmt = videos[0].pix_fmt
    if reason is None:
        operation, reason, crf = "copy", "whole compatible segments are copied as packets", None
    else:
        operation = "encode"
        encoder = next((name for name in CODECS[codec].encoders if name in caps.encoders), None)
        if encoder is None:
            errors.append(f"this {caps.backend} build has no {codec} encoder ({' or '.join(CODECS[codec].encoders)})")
        for index, video in enumerate(videos):
            if caps.decoders is not None and video.codec not in caps.decoders:
                errors.append(f"entry {index + 1}: this {caps.backend} build has no {video.codec} decoder")
        match = re.fullmatch(r"yuvj?(4\d\d)p(10le)?", pix_fmt)
        pix_fmt = (
            f"yuv{match.group(1) if match and match.group(1) in CODECS[codec].chroma else '420'}p{(match.group(2) or '') if match else ''}"
        )

    audio_operation: Optional[str] = None
    audio_reason = ""
    if not silent:
        only = planned[0]
        sound = found[0].probe.audio
        direct = (
            operation == "copy"
            and len(planned) == 1
            and only.audio == "embedded"
            and sound.codec == "aac"
            and sound.start == 0
            and (sound.rate, sound.channels) == (rate, channels)
            and not any(text.startswith("entry 1:") for text in warnings)
        )
        audio_operation = "copy" if direct else "encode"
        audio_reason = (
            "one whole segment keeps its own track" if direct else "sound is rebuilt on one continuous sample timeline and encoded once"
        )
    return ExportPlan(
        tuple(states),
        tuple(planned),
        spec.fps,
        spec.width,
        spec.height,
        pix_fmt,
        videos[0].color,
        rate,
        channels,
        position,
        0 if silent else sample_boundary(position, spec.fps, rate),
        operation,
        reason,
        codec if operation == "encode" else (common or codec),
        encoder,
        crf,
        audio_operation,
        audio_reason,
        tuple(needs),
        tuple(warnings),
        tuple(errors),
    )


def plan_json(plan: ExportPlan, destination: str, backend: str) -> Dict[str, Any]:
    """The preflight answer: per-entry state and ranges, totals, operations with reasons, and what still needs a decision."""
    by_id = {entry.id: entry for entry in plan.entries}
    rows = []
    for identifier, state, message in plan.states:
        entry = by_id.get(identifier)
        rows.append(
            {
                "id": identifier,
                "state": state,
                "frames": list(entry.frames) if entry else None,
                "samples": list(entry.samples) if entry and plan.sample_rate else None,
                "audio": entry.audio if entry else "none",
                "message": message,
            }
        )
    return {
        "entries": rows,
        "frames": plan.frames,
        "duration": float(Fraction(plan.frames) / plan.fps),
        "samples": plan.samples if plan.sample_rate else None,
        "fps": _fraction(plan.fps),
        "width": plan.width,
        "height": plan.height,
        "sample_rate": plan.sample_rate or None,
        "channels": plan.channels or None,
        "video": {
            "operation": plan.video_operation,
            "reason": plan.video_reason,
            "codec": plan.codec,
            "encoder": plan.encoder,
            "crf": plan.crf,
        },
        "audio": None if plan.audio_operation is None else {"operation": plan.audio_operation, "reason": plan.audio_reason},
        "destination": destination,
        "backend": backend,
        "needs": list(plan.needs),
        "warnings": [*plan.warnings, *plan.errors],
        "ready": plan.ready,
    }


def sequence_record(
    *,
    job: str,
    created: str,
    request: ExportRequest,
    counter: int,
    film: Dict[str, Any],
    backend: Dict[str, str],
    plan: ExportPlan,
    document: EditDocument,
    locations: Mapping[str, Dict[str, str]],
) -> Dict[str, Any]:
    """The snapshot of one export: what was used and how, readable after a source is removed."""
    entries = {entry.id: entry for entry in document.entries}
    return {
        "version": 1,
        "kind": "arisu.sequence",
        "job": job,
        "created": created,
        "project": request.project,
        "name": request.name,
        "counter": counter,
        "film": film,
        "backend": backend,
        "request": {"encoding": request.encoding, "codec": request.codec, "crf": request.crf},
        "video": {
            "operation": plan.video_operation,
            "reason": plan.video_reason,
            "codec": plan.codec,
            "encoder": plan.encoder,
            "crf": plan.crf,
            "width": plan.width,
            "height": plan.height,
            "fps": _fraction(plan.fps),
            "pix_fmt": plan.pix_fmt,
            "color": dict(zip(("range", "matrix", "primaries", "transfer"), plan.color)),
            "frames": plan.frames,
            "start_pts": 0,
        },
        "audio": None
        if plan.audio_operation is None
        else {
            "operation": plan.audio_operation,
            "reason": plan.audio_reason,
            "codec": "aac",
            "rate": plan.sample_rate,
            "channels": plan.channels,
            "samples": plan.samples,
            "start_pts": 0,
        },
        "entries": [
            {
                "id": item.id,
                "source": entries[item.id].source,
                "take": entries[item.id].take,
                "segment": entries[item.id].segment,
                "root": entries[item.id].root,
                "path": entries[item.id].path,
                "revision": entries[item.id].revision,
                "range": [item.first, item.last],
                "frames": list(item.frames),
                "samples": list(item.samples) if plan.sample_rate else None,
                "audio": {
                    "choice": entries[item.id].audio,
                    "source": item.audio,
                    "offset": item.audio_offset,
                    "delta": item.audio_delta,
                    **locations.get(item.id, {}),
                },
            }
            for item in plan.entries
        ],
        "document": document.raw,
    }


def read_sequence_record(text: str) -> Dict[str, Any]:
    """Validate the fields of an export record that recovery relies on."""
    if len(text.encode("utf-8")) > SEQUENCE_LIMIT:
        raise ValueError("invalid export record")
    try:
        record = json.loads(text)
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid export record") from error
    film = record.get("film") if isinstance(record, dict) else None
    if not isinstance(film, dict) or record.get("kind") != "arisu.sequence" or record.get("version") != 1:
        raise ValueError("invalid export record")
    if not isinstance(record.get("job"), str) or film.get("root") != "output" or not isinstance(film.get("revision"), str):
        raise ValueError("invalid export record")
    relative_path(film.get("path"))
    return record


def suggest_correction(outgoing: List[Tuple[float, float, float]], incoming: List[Tuple[float, float, float]]) -> Optional[Dict[str, Any]]:
    """Compare mean Y, Cb, Cr (0-1 of each range) across frames on both sides of a join.

    A step is offered only when it is persistent: larger than three times the normal variation inside either
    shot and a small floor, with every incoming frame on the same side of the outgoing level.
    """
    if len(outgoing) < 2 or len(incoming) < 2:
        return None
    offsets = []
    stable = False
    for channel in range(3):
        before, after = [frame[channel] for frame in outgoing], [frame[channel] for frame in incoming]
        level = sum(before) / len(before)
        step = sum(after) / len(after) - level
        spread = max(max(before) - min(before), max(after) - min(after))
        persistent = abs(step) > max(3 * spread, 0.5 / 255) and all((value - level) * step > 0 for value in after)
        stable = stable or persistent
        offsets.append(-step if persistent else 0.0)
    if not stable:
        return {"stable": False, "correction": None}
    limits = (_CORRECTION_BOUNDS["luma_offset"], _CORRECTION_BOUNDS["cb_offset"], _CORRECTION_BOUNDS["cr_offset"])
    luma, cb, cr = (round(min(high, max(low, value)), 5) for value, (low, high) in zip(offsets, limits))
    return {"stable": True, "correction": {"luma_gain": 1.0, "luma_offset": luma, "cb_offset": cb, "cr_offset": cr, "taper": 24}}


def probe_json(probe: Probe) -> Dict[str, Any]:
    """Serialize measured stream facts for the worker boundary; rationals travel as integer pairs."""

    def plain(info: Any) -> Optional[Dict[str, Any]]:
        if info is None:
            return None
        return {
            key: _fraction(value) if isinstance(value, Fraction) else list(value) if isinstance(value, tuple) else value
            for key, value in vars(info).items()
        }

    return {"container": probe.container, "video": plain(probe.video), "audio": plain(probe.audio), "evidence": probe.evidence}


def probe_from_json(data: Mapping[str, Any]) -> Probe:
    """Rebuild a probe that a worker reported."""

    def rational(value: Any) -> Fraction:
        return Fraction(int(value[0]), int(value[1]))

    video, audio = data["video"], data["audio"]
    if video is not None:
        video = VideoInfo(
            **{**video, **{key: rational(video[key]) for key in ("fps", "time_base", "start", "duration")}, "color": tuple(video["color"])}
        )
    if audio is not None:
        audio = AudioInfo(**{**audio, "start": rational(audio["start"])})
    return Probe(str(data["container"]), video, audio, bool(data["evidence"]))


def plan_payload(plan: ExportPlan) -> Dict[str, Any]:
    """The part of a plan a media worker needs, as plain JSON."""
    return {
        "fps": _fraction(plan.fps),
        "width": plan.width,
        "height": plan.height,
        "pix_fmt": plan.pix_fmt,
        "color": list(plan.color),
        "sample_rate": plan.sample_rate,
        "channels": plan.channels,
        "frames": plan.frames,
        "samples": plan.samples,
        "encoder": plan.encoder,
        "crf": plan.crf,
        "entries": [
            {
                "path": entry.path,
                "first": entry.first,
                "last": entry.last,
                "frames": list(entry.frames),
                "samples": list(entry.samples),
                "whole": entry.whole,
                "by_time": entry.by_time,
                "start_time": _fraction(entry.start_time),
                "audio": entry.audio,
                "audio_path": entry.audio_path,
                "audio_offset": entry.audio_offset,
                "fade_in": entry.fade_in,
                "fade_out": entry.fade_out,
                "correction": None
                if entry.correction is None
                else {key: getattr(entry.correction, key) for key in ("luma_gain", "luma_offset", "cb_offset", "cr_offset", "taper")},
            }
            for entry in plan.entries
        ],
    }


def parse_job(text: Any) -> str:
    """The one-shot export request ID: blank for an ordinary run, otherwise a UUID."""
    if not isinstance(text, str) or (text and not _UUID.fullmatch(text)):
        raise ValueError("invalid export request")
    return text


def refusal(plan: ExportPlan) -> str:
    """Why an export cannot run, in the order a user must resolve it."""
    for index, (_, state, message) in enumerate(plan.states):
        if state != "ok":
            return f"entry {index + 1} is {message or state}; review it in the edit list"
    if plan.errors:
        return plan.errors[0]
    if plan.needs:
        return "the export check needs a decision first: " + ", ".join(sorted({need["kind"].replace("_", " ") for need in plan.needs}))
    return "select at least one usable video"
