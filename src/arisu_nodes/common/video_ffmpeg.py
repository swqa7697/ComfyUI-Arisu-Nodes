"""FFmpeg command lines and output parsing for video segments. Every argument list is built from fixed parts."""

from __future__ import annotations

import json
import re
from fractions import Fraction
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .media import FORMATS, UnsupportedMedia
from .video import LAYOUTS, AudioInfo, ExportPlan, PlannedEntry, Probe, VideoInfo

# One local file per input: no network, no nested protocols, and only self-contained demuxers.
FILE_INPUT = ["-protocol_whitelist", "file", "-format_whitelist", FORMATS]
QUIET = ["-hide_banner", "-nostdin", "-loglevel", "error", "-nostats"]
_PROBE_ENTRIES = (
    "format=format_name:"
    "stream=index,codec_type,codec_name,profile,codec_tag_string,width,height,sample_aspect_ratio,pix_fmt,color_range,color_space,"
    "color_primaries,color_transfer,r_frame_rate,avg_frame_rate,time_base,start_pts,duration_ts,nb_frames,nb_read_packets,"
    "sample_rate,channels,channel_layout,initial_padding,extradata_hash:"
    "stream_disposition=attached_pic:packet=stream_index,pts,duration"
)


def parse_encoders(text: str) -> FrozenSet[str]:
    """Encoder names from ``ffmpeg -encoders``."""
    return frozenset(re.findall(r"^ [VAS][.A-Z]{5} (\S+)", text, re.MULTILINE))


def parse_decoders(text: str) -> FrozenSet[str]:
    """Codec names that ``ffmpeg -decoders`` can decode, whichever decoder provides them."""
    found = set()
    for name, rest in re.findall(r"^ [VAS][.A-Z]{5} (\S+)(.*)$", text, re.MULTILINE):
        wrapped = re.search(r"\(codec (\w+)\)", rest)
        found.add(wrapped.group(1) if wrapped else name)
    return frozenset(found)


def probe_argv(ffprobe: str, path: str) -> List[str]:
    """Inspect streams and packet timestamps of one contained local file."""
    return [
        ffprobe,
        "-v",
        "error",
        *FILE_INPUT,
        "-show_data_hash",
        "sha256",
        "-count_packets",
        "-show_entries",
        _PROBE_ENTRIES,
        "-of",
        "json",
        path,
    ]


def _ratio(value: Any) -> Optional[Fraction]:
    try:
        number = Fraction(str(value).replace(":", "/"))
    except (ValueError, ZeroDivisionError):
        return None
    return number if number > 0 else None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _video(stream: Dict[str, Any], packets: List[Dict[str, Any]]) -> VideoInfo:
    base = _ratio(stream.get("time_base"))
    if base is None or not packets or any(type(packet.get("pts")) is not int for packet in packets):
        raise UnsupportedMedia("video timestamps are unavailable")
    stamps = sorted(packet["pts"] for packet in packets)
    last = max(packets, key=lambda packet: packet["pts"])
    nominal = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))
    if nominal is None:
        raise UnsupportedMedia("video frame rate is unavailable")
    # One tick of tolerance accepts millisecond containers; exact representation is a separate copy requirement.
    constant = all(abs((stamp - stamps[0]) * base - index / nominal) <= base for index, stamp in enumerate(stamps))
    step = Fraction(1) / nominal
    span = (stamps[-1] - stamps[0]) * base + (_integer(last.get("duration")) * base or step)
    width, height = _integer(stream.get("width")), _integer(stream.get("height"))
    if width <= 0 or height <= 0:
        raise UnsupportedMedia("video dimensions are unavailable")
    sar = str(stream.get("sample_aspect_ratio") or "1:1")
    return VideoInfo(
        codec=str(stream.get("codec_name", "")),
        profile=str(stream.get("profile", "")),
        tag=str(stream.get("codec_tag_string", "")),
        width=width,
        height=height,
        sar="1:1" if sar.startswith("0") else sar,
        pix_fmt=str(stream.get("pix_fmt", "")),
        fps=nominal,
        time_base=base,
        frames=len(stamps),
        start=stamps[0] * base,
        duration=span,
        constant=constant,
        color=tuple(str(stream.get(key, "unknown")) for key in ("color_range", "color_space", "color_primaries", "color_transfer")),
        extradata=str(stream.get("extradata_hash", "")),
    )


def _audio(stream: Dict[str, Any], packets: List[Dict[str, Any]]) -> AudioInfo:
    base, rate, channels = _ratio(stream.get("time_base")), _integer(stream.get("sample_rate")), _integer(stream.get("channels"))
    if base is None or rate <= 0 or channels <= 0:
        raise UnsupportedMedia("audio parameters are unavailable")
    ticks = _integer(stream.get("duration_ts")) or sum(_integer(packet.get("duration")) for packet in packets)
    return AudioInfo(
        codec=str(stream.get("codec_name", "")),
        profile=str(stream.get("profile", "")),
        rate=rate,
        channels=channels,
        layout=str(stream.get("channel_layout") or LAYOUTS.get(channels, "")),
        samples=round(ticks * base * rate),
        start=_integer(stream.get("start_pts")) * base,
        priming=_integer(stream.get("initial_padding")),
        extradata=str(stream.get("extradata_hash", "")),
    )


def parse_ffprobe(text: str) -> Probe:
    """Turn ffprobe JSON into measured stream facts; cover art is not a video stream."""
    try:
        data = json.loads(text)
        listed, packets = data["streams"], data.get("packets", [])
        container = str(data["format"]["format_name"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise UnsupportedMedia("unsupported or incomplete media") from error

    def first(kind: str) -> Optional[Dict[str, Any]]:
        return next((s for s in listed if s.get("codec_type") == kind and not s.get("disposition", {}).get("attached_pic")), None)

    def owned(stream: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [packet for packet in packets if packet.get("stream_index") == stream.get("index")]

    video, audio = first("video"), first("audio")
    return Probe(container, _video(video, owned(video)) if video else None, _audio(audio, owned(audio)) if audio else None, True)


def encoder_args(encoder: str, crf: int, fast: bool = False) -> List[str]:
    """Quality arguments for one supported encoder; each has its own CRF scale. ``fast`` is for short previews."""
    options = {
        "libx264": ["-preset", "ultrafast" if fast else "medium", "-crf", str(crf)],
        "libx265": ["-preset", "medium", "-crf", str(crf), "-tag:v", "hvc1", "-x265-params", "log-level=error"],
        "libsvtav1": ["-preset", "6", "-crf", str(crf)],
        "libaom-av1": ["-cpu-used", "6", "-crf", str(crf), "-b:v", "0"],
    }
    return ["-c:v", encoder, *options[encoder]]


def color_filter(pix_fmt: str, color: Tuple[str, str, str]) -> str:
    """Convert full-range RGB to tagged limited-range YUV; the tags travel on the frames, where encoders read them."""
    primaries, transfer, matrix = color
    return (
        f"scale=in_range=pc:out_range=tv:out_color_matrix={matrix},format={pix_fmt},"
        f"setparams=range=tv:colorspace={matrix}:color_primaries={primaries}:color_trc={transfer}"
    )


def aac_args(channels: int) -> List[str]:
    """One AAC track at a bit rate that follows the channel count."""
    return ["-c:a", "aac", "-b:a", f"{min(384, 96 * channels)}k"]


def encode_take_argv(
    ffmpeg: str,
    *,
    width: int,
    height: int,
    fps: Fraction,
    deep: bool,
    pix_fmt: str,
    color: Tuple[str, str, str],
    encoder: str,
    crf: int,
    audio: Optional[Tuple[str, int, int]],
    metadata: Optional[str],
    output: str,
) -> List[str]:
    """Encode raw RGB frames from stdin, with an optional PCM file ``(path, end_sample, channels)`` and a tag file."""
    argv = [ffmpeg, *QUIET, "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le" if deep else "rgb24", "-video_size", f"{width}x{height}"]
    argv += ["-framerate", f"{fps.numerator}/{fps.denominator}", "-i", "pipe:0"]
    inputs = 1
    if audio is not None:
        argv += ["-protocol_whitelist", "file", "-f", "wav", "-i", audio[0]]
        inputs += 1
    if metadata is not None:
        argv += ["-protocol_whitelist", "file", "-f", "ffmetadata", "-i", metadata]
    argv += [
        "-map",
        "0:v:0",
        *(["-map", "1:a:0"] if audio is not None else []),
        "-map_metadata",
        str(inputs) if metadata is not None else "-1",
    ]
    argv += ["-vf", color_filter(pix_fmt, color), *encoder_args(encoder, crf)]
    if audio is not None:
        argv += ["-af", f"atrim=end_sample={audio[1]}", *aac_args(audio[2])]
    return [*argv, "-movflags", "+faststart+use_metadata_tags", "-f", "mp4", output]


def decode_samples_argv(ffmpeg: str, path: str) -> List[str]:
    """Decode the first audio track to raw float samples on stdout, as a player would deliver it."""
    return [ffmpeg, *QUIET, *FILE_INPUT, "-i", path, "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]


def framecrc_argv(ffmpeg: str, path: str) -> List[str]:
    """List packet timing with native FFmpeg alone, for hosts that have no ffprobe."""
    return [
        ffmpeg,
        *QUIET,
        *FILE_INPUT,
        "-copyts",
        "-i",
        path,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-f",
        "framecrc",
        "pipe:1",
    ]


def parse_framecrc(text: str) -> Probe:
    """Read packet timing from a framecrc listing; pixel format and colour are unknown, so it is no copy evidence."""
    headers: Dict[Tuple[str, int], str] = {}
    rows: Dict[int, List[Tuple[int, int]]] = {}
    for line in text.splitlines():
        header = re.fullmatch(r"#(\w+) (\d+): *(.+)", line)
        if header:
            headers[header.group(1), int(header.group(2))] = header.group(3).strip()
            continue
        fields = [field.strip() for field in line.split(",")]
        if not line.startswith("#") and len(fields) >= 4:
            try:
                rows.setdefault(int(fields[0]), []).append((int(fields[2]), int(fields[3])))
            except ValueError as error:
                raise UnsupportedMedia("media timestamps are unavailable") from error
    video = audio = None
    for index, packets in rows.items():
        base, kind = _ratio(headers.get(("tb", index))), headers.get(("media_type", index))
        if base is None or not packets:
            raise UnsupportedMedia("unsupported or incomplete media")
        first, end = min(pts for pts, _ in packets), max(pts + duration for pts, duration in packets)
        if kind == "video" and video is None:
            width, _, height = headers.get(("dimensions", index), "0x0").partition("x")
            stamps = sorted(pts for pts, _ in packets)
            span = (end - first) * base
            if span <= 0 or _integer(width) <= 0 or _integer(height) <= 0:
                raise UnsupportedMedia("unsupported or incomplete media")
            nominal = Fraction(len(stamps)) / span
            video = VideoInfo(
                codec=headers.get(("codec_id", index), ""),
                profile="",
                tag="",
                width=_integer(width),
                height=_integer(height),
                sar=headers.get(("sar", index), "1/1").replace("/", ":"),
                pix_fmt="",
                fps=nominal,
                time_base=base,
                frames=len(stamps),
                start=first * base,
                duration=span,
                constant=all(abs((stamp - first) * base - step / nominal) <= base for step, stamp in enumerate(stamps)),
                color=("unknown", "unknown", "unknown", "unknown"),
                extradata="",
            )
        elif kind == "audio" and audio is None:
            rate = _integer(headers.get(("sample_rate", index)))
            layout = headers.get(("channel_layout_name", index), "")
            channels = next((count for count, name in LAYOUTS.items() if name == layout), 0)
            if rate <= 0 or channels <= 0:
                raise UnsupportedMedia("audio parameters are unavailable")
            start = max(first, 0)
            audio = AudioInfo(
                headers.get(("codec_id", index), ""), "", rate, channels, layout, round((end - start) * base * rate), start * base, 0, ""
            )
    return Probe("", video, audio, False)


def _quoted(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def _microseconds(value: Fraction) -> int:
    return round(value * 1000000)


def concat_script(plan: ExportPlan) -> str:
    """A concat demuxer list that pins every file to its planned place on the picture timeline.

    ``inpoint`` anchors each file at its first picture rather than an earlier audio priming packet, and each
    ``duration`` is the difference of two rounded cumulative boundaries, so the error never accumulates.
    """
    lines = ["ffconcat version 1.0"]
    for entry in plan.entries:
        if any(ord(character) < 32 for character in entry.path):
            raise ValueError("a source path cannot be listed for packet copy")
        length = _microseconds(Fraction(entry.frames[1]) / plan.fps) - _microseconds(Fraction(entry.frames[0]) / plan.fps)
        lines += [f"file {_quoted(entry.path)}", "inpoint 0", f"duration {length // 1000000}.{length % 1000000:06d}"]
    return "\n".join(lines) + "\n"


def _audio_chains(plan: ExportPlan, pads: List[Optional[str]]) -> List[str]:
    """One continuous sample timeline: each entry fills exactly its slot, then all slots join and are stamped by count."""
    layout = LAYOUTS[plan.channels]
    chains = []
    for index, (entry, pad) in enumerate(zip(plan.entries, pads)):
        slot = entry.samples[1] - entry.samples[0]
        if pad is None:
            chain = f"anullsrc=r={plan.sample_rate}:cl={layout},atrim=end_sample={slot},asetpts=N/SR/TB"
        else:
            # Embedded tracks are placed by container time once, which removes encoder priming and fills a late start.
            resample = f"aresample={plan.sample_rate}:async=1:first_pts=0" if entry.audio == "embedded" else f"aresample={plan.sample_rate}"
            chain = f"{pad}{resample},atrim=start_sample={entry.audio_offset}:end_sample={entry.audio_offset + slot},asetpts=N/SR/TB,apad=whole_len={slot}"
            if entry.fade_in:
                chain += f",afade=t=in:ss=0:ns={entry.fade_in}"
            if entry.fade_out:
                chain += f",afade=t=out:ss={slot - entry.fade_out}:ns={entry.fade_out}"
            chain += f",aformat=sample_fmts=fltp:channel_layouts={layout}"
        chains.append(f"{chain}[a{index}]")
    joined = "".join(f"[a{index}]" for index in range(len(chains)))
    chains.append(f"{joined}concat=n={len(plan.entries)}:v=0:a=1,asetpts=N/SR/TB[aout]")
    return chains


def _correction_filter(entry: PlannedEntry, pix_fmt: str) -> str:
    """Taper a bounded luma and chroma adjustment across the opening frames; every constant is formatted here."""
    scale = 4 if "10" in pix_fmt else 1
    top, black, taper, fix = 255 * scale + scale - 1, 16 * scale, entry.correction.taper, entry.correction
    weight = f"(1-N/{taper})"
    luma = f"clip(lum(X,Y)+{weight}*(({fix.luma_gain - 1:.5f})*(lum(X,Y)-{black})+({fix.luma_offset * 219 * scale:.4f})),0,{top})"
    cb = f"clip(cb(X,Y)+{weight}*({fix.cb_offset * 224 * scale:.4f}),0,{top})"
    cr = f"clip(cr(X,Y)+{weight}*({fix.cr_offset * 224 * scale:.4f}),0,{top})"
    return f",geq=lum='{luma}':cb='{cb}':cr='{cr}':enable='lt(n,{taper})'"


def _video_chains(plan: ExportPlan) -> List[str]:
    """Conform each entry to the output format, then join and stamp frames by count on the exact output rate."""
    rate = f"{plan.fps.numerator}/{plan.fps.denominator}"
    chains = []
    for index, entry in enumerate(plan.entries):
        chain = f"[{index}:v:0]setpts=PTS-STARTPTS,"
        if entry.by_time:
            # Presentation time decides which source picture each output frame shows.
            window = "" if entry.whole else f"trim=start={float(entry.start_time):.6f}:end={float(entry.end_time):.6f},setpts=PTS-STARTPTS,"
            count = entry.frames[1] - entry.frames[0]
            chain += f"{window}fps={rate},tpad=stop=-1:stop_mode=clone,trim=end_frame={count}"
        else:
            chain += f"trim=start_frame={entry.first}:end_frame={entry.last},setpts=PTS-STARTPTS"
        chain += f",scale={plan.width}:{plan.height},setsar=1,format={plan.pix_fmt}"
        if entry.correction is not None:
            chain += _correction_filter(entry, plan.pix_fmt)
        chains.append(f"{chain}[v{index}]")
    tags = ""
    if "unknown" not in plan.color:
        tags = f",setparams=range={plan.color[0]}:colorspace={plan.color[1]}:color_primaries={plan.color[2]}:color_trc={plan.color[3]}"
    joined = "".join(f"[v{index}]" for index in range(len(chains)))
    chains.append(f"{joined}concat=n={len(plan.entries)}:v=1:a=0,settb={plan.fps.denominator}/{plan.fps.numerator},setpts=N{tags}[vout]")
    return chains


def export_argv(ffmpeg: str, plan: ExportPlan, script: str, output: str, fast: bool = False) -> List[str]:
    """The single process that writes a film: packet copy from ``script`` or one encode, with at most one AAC encode."""
    head = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
    tail = ["-map_metadata", "-1", "-movflags", "+faststart", "-f", "mp4", output]
    sound = plan.audio_operation is not None
    if plan.video_operation == "copy" and plan.audio_operation == "copy":
        return [*head, *FILE_INPUT, "-i", plan.entries[0].path, "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", *tail]
    inputs: List[str] = []
    pads: List[Optional[str]] = []
    count = 0
    if plan.video_operation == "copy":
        inputs += [
            "-copyts",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "concat," + FORMATS,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            script,
        ]
        count = 1
    else:
        for entry in plan.entries:
            inputs += [*FILE_INPUT, "-i", entry.path]
        count = len(plan.entries)
    for index, entry in enumerate(plan.entries):
        if not sound or entry.audio == "none":
            pads.append(None)
        elif entry.audio == "embedded" and plan.video_operation == "encode":
            pads.append(f"[{index}:a:0]")
        else:
            inputs += (
                ["-protocol_whitelist", "file", "-f", "wav", "-i", entry.audio_path]
                if entry.audio == "pcm"
                else [*FILE_INPUT, "-i", entry.audio_path]
            )
            pads.append(f"[{count}:a:0]")
            count += 1
    graph = [*(_video_chains(plan) if plan.video_operation == "encode" else []), *(_audio_chains(plan, pads) if sound else [])]
    argv = [*head, *inputs, *(["-filter_complex", ";".join(graph)] if graph else [])]
    if plan.video_operation == "copy":
        argv += ["-map", "0:v:0", "-c:v", "copy", "-avoid_negative_ts", "disabled"]
    else:
        argv += ["-map", "[vout]", "-fps_mode", "passthrough", *encoder_args(plan.encoder, plan.crf, fast)]
    argv += ["-map", "[aout]", *aac_args(plan.channels)] if sound else ["-an"]
    return [*argv, *tail]


def join_frames_argv(ffmpeg: str, path: str, first: int, count: int) -> List[str]:
    """Reduce a few consecutive frames to 64x36 4:4:4 on stdout, for the join colour comparison."""
    chain = f"setpts=PTS-STARTPTS,trim=start_frame={first}:end_frame={first + count},scale=64:36,format=yuv444p"
    return [ffmpeg, *QUIET, *FILE_INPUT, "-i", path, "-map", "0:v:0", "-vf", chain, "-f", "rawvideo", "pipe:1"]
