"""PyAV fallback for video segments, used only when the service has no system ``ffmpeg`` executable.

The functions follow the same frame and sample contracts as the native path. Decoding of existing files
runs in the isolated media worker (``main``); the saver encodes tensors in process, where nothing is decoded.
"""

from __future__ import annotations

import json
import struct
import sys
from fractions import Fraction
from typing import Any, BinaryIO, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import av
import numpy as np
from av.video.reformatter import ColorPrimaries, ColorRange, ColorTrc

from .media import UnsupportedMedia, open_media, streams
from .video import LAYOUTS, AudioInfo, Probe, VideoInfo, probe_json

_AAC_FRAME = 1024
_PRIMARIES = {"bt709": ColorPrimaries.BT709, "bt2020": ColorPrimaries.BT2020}
_TRANSFERS = {"iec61966-2-1": ColorTrc.IEC61966_2_1, "arib-std-b67": ColorTrc.ARIB_STD_B67, "smpte2084": ColorTrc.SMPTE2084}
_MATRICES = {"bt709": 1, "bt2020nc": 9}


def _channels(stream: Any) -> int:
    return len(stream.layout.channels)


def probe(path: str) -> Probe:
    """Measure packet timing with the linked libraries; this is never evidence for a packet copy."""
    with open(path, "rb") as handle, open_media(handle) as container:
        video, audio = streams(container)
        measured_video = measured_audio = None
        if video is not None:
            stamps = sorted(packet.pts for packet in container.demux(video) if packet.pts is not None and packet.size)
            nominal = video.average_rate or video.guessed_rate
            if not stamps or not nominal:
                raise UnsupportedMedia("video timestamps are unavailable")
            base = video.time_base
            measured_video = VideoInfo(
                codec=video.codec.canonical_name,
                profile="",
                tag="",
                width=video.codec_context.width,
                height=video.codec_context.height,
                sar="1:1",
                pix_fmt=video.codec_context.pix_fmt or "",
                fps=Fraction(nominal),
                time_base=Fraction(base),
                frames=len(stamps),
                start=stamps[0] * base,
                duration=(stamps[-1] - stamps[0]) * base + Fraction(1) / nominal,
                constant=all(abs((stamp - stamps[0]) * base - Fraction(index) / nominal) <= base for index, stamp in enumerate(stamps)),
                color=("unknown", "unknown", "unknown", "unknown"),
                extradata="",
            )
        if audio is not None:
            count = _channels(audio)
            ticks = audio.duration or 0
            measured_audio = AudioInfo(
                audio.codec.canonical_name,
                "",
                audio.rate,
                count,
                LAYOUTS.get(count, ""),
                round(ticks * audio.time_base * audio.rate),
                Fraction(max(0, audio.start_time or 0)) * audio.time_base,
                0,
                "",
            )
        return Probe(container.format.name, measured_video, measured_audio, False)


def _decode_audio(path: str, rate: int, channels: int) -> np.ndarray:
    """Decode the first audio track to ``[channels, samples]`` at ``rate``, placed by container time from zero.

    The linked decoder applies the leading trim of an encoded track but not the trailing one, so the stream
    duration bounds the valid end.
    """
    layout = LAYOUTS[channels]
    with open(path, "rb") as handle, open_media(handle) as container:
        _, audio = streams(container)
        if audio is None:
            raise UnsupportedMedia("no audio stream")
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=rate)
        pieces: List[Tuple[int, np.ndarray]] = []
        position = 0
        for frame in container.decode(audio):
            start = round(frame.pts * frame.time_base * rate) if frame.pts is not None else position
            for converted in resampler.resample(frame):
                samples = converted.to_ndarray()
                pieces.append((start, samples))
                start += samples.shape[1]
            position = start
        valid = (
            round(audio.duration * audio.time_base * rate)
            if audio.duration
            else max((start + data.shape[1] for start, data in pieces), default=0)
        )
        output = np.zeros((channels, max(0, valid)), dtype=np.float32)
        for start, samples in pieces:
            left, right = max(0, start), min(valid, start + samples.shape[1])
            if right > left:
                output[:, left:right] = samples[:, left - start : right - start]
        return output


def count_samples(path: str) -> int:
    """The valid samples of the first audio track at its own rate."""
    with open(path, "rb") as handle, open_media(handle) as container:
        _, audio = streams(container)
        if audio is None:
            raise UnsupportedMedia("no audio stream")
        rate, channels = audio.rate, min(2, _channels(audio))
    return int(_decode_audio(path, rate, channels).shape[1])


def _frames(path: str) -> Iterator[Tuple[Fraction, av.VideoFrame]]:
    with open(path, "rb") as handle, open_media(handle) as container:
        video, _ = streams(container)
        if video is None:
            raise UnsupportedMedia("no video stream")
        origin: Optional[Fraction] = None
        for frame in container.decode(video):
            if frame.pts is None:
                raise UnsupportedMedia("video timestamps are unavailable")
            stamp = frame.pts * frame.time_base
            origin = stamp if origin is None else origin
            yield stamp - origin, frame


def means(path: str, first: int, count: int) -> List[List[float]]:
    """Mean Y, Cb and Cr of consecutive frames, each as 0-1 of its 8-bit range."""
    found = []
    for index, (_, frame) in enumerate(_frames(path)):
        if index >= first + count:
            break
        if index >= first:
            y, cb, cr = (float(plane.mean()) for plane in frame.reformat(64, 36, "yuv444p").to_ndarray())
            found.append([(y - 16) / 219, (cb - 128) / 224, (cr - 128) / 224])
    return found


def _read_pcm(path: str) -> Tuple[np.ndarray, int]:
    """Read a float PCM companion written by the saver as ``[channels, samples]``."""
    with open(path, "rb") as handle:
        header = handle.read(64)
        marker = header.find(b"data")
        if header[:4] != b"RIFF" or header[8:12] != b"WAVE" or marker < 0 or struct.unpack_from("<H", header, 20)[0] != 3:
            raise UnsupportedMedia("unsupported PCM companion")
        channels, rate = struct.unpack_from("<HI", header, 22)
        handle.seek(marker + 8)
        data = np.frombuffer(handle.read(struct.unpack_from("<I", header, marker + 4)[0]), dtype="<f4")
    return data[: len(data) - len(data) % channels].reshape(-1, channels).T.astype(np.float32), rate


def _resample(samples: np.ndarray, source: int, rate: int, channels: int) -> np.ndarray:
    """Convert rate and channel count through the linked resampler."""
    if source == rate and samples.shape[0] == channels:
        return samples
    resampler = av.AudioResampler(format="fltp", layout=LAYOUTS[channels], rate=rate)
    frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples), format="fltp", layout=LAYOUTS[samples.shape[0]])
    frame.sample_rate = source
    pieces = [converted.to_ndarray() for converted in (*resampler.resample(frame), *resampler.resample(None))]
    return np.concatenate(pieces, axis=1) if pieces else np.zeros((channels, 0), dtype=np.float32)


def _slot(entry: Mapping[str, Any], rate: int, channels: int) -> np.ndarray:
    """Exactly one entry's planned samples: its source cut at the picture boundary, padded with silence, faded in place."""
    length = entry["samples"][1] - entry["samples"][0]
    output = np.zeros((channels, length), dtype=np.float32)
    if entry["audio"] == "pcm":
        source = _resample(*_read_pcm(entry["audio_path"]), rate, channels)
    elif entry["audio"] == "embedded":
        source = _decode_audio(entry["audio_path"], rate, channels)
    else:
        return output
    piece = source[:, entry["audio_offset"] : entry["audio_offset"] + length]
    output[:, : piece.shape[1]] = piece
    if entry["fade_in"]:
        output[:, : entry["fade_in"]] *= np.linspace(0.0, 1.0, entry["fade_in"], dtype=np.float32)
    if entry["fade_out"]:
        output[:, length - entry["fade_out"] :] *= np.linspace(1.0, 0.0, entry["fade_out"], dtype=np.float32)
    return output


def _tag(target: Any, color: Tuple[str, str, str]):
    """Signal limited-range colour as ``(primaries, transfer, matrix)`` names; unknown names stay unset."""
    primaries, transfer, matrix = color
    if primaries in _PRIMARIES and transfer in _TRANSFERS and matrix in _MATRICES:
        target.color_primaries, target.color_trc = _PRIMARIES[primaries], _TRANSFERS[transfer]
        target.colorspace, target.color_range = _MATRICES[matrix], ColorRange.MPEG


class Writer:
    """One MP4 with a constant-rate video track and, optionally, one AAC track stamped by sample count from zero."""

    def __init__(
        self, target: Any, *, width: int, height: int, fps: Fraction, pix_fmt: str, encoder: str, crf: int, color: Tuple[str, str, str]
    ):
        self.output = av.open(target, "w", format="mp4", options={"movflags": "faststart+use_metadata_tags"})
        self.video = self.output.add_stream(encoder, rate=fps)
        self.video.width, self.video.height, self.video.pix_fmt = width, height, pix_fmt
        self.video.time_base = self.video.codec_context.time_base = Fraction(1) / fps
        self.video.options = {"crf": str(crf), **({"preset": "6"} if encoder == "libsvtav1" else {})}
        self.color, self.pix_fmt, self.fps = color, pix_fmt, fps
        _tag(self.video.codec_context, color)
        self.audio: Any = None
        self.frames = self.samples = 0
        self.rate = self.channels = 0
        self.pending = np.zeros((0, 0), dtype=np.float32)

    def add_audio(self, rate: int, channels: int):
        """Create the single audio track before the first frame is written."""
        self.audio = self.output.add_stream("aac", rate=rate, layout=LAYOUTS[channels])
        self.rate, self.channels = rate, channels
        self.pending = np.zeros((channels, 0), dtype=np.float32)

    def write_frame(self, frame: av.VideoFrame):
        """Encode one picture already in the output size and pixel format."""
        frame.pts, frame.time_base = self.frames, Fraction(1) / self.fps
        _tag(frame, self.color)
        self.frames += 1
        self.output.mux(self.video.encode(frame))

    def write_audio(self, samples: np.ndarray, last: bool = False):
        """Queue samples and encode whole AAC frames, so only the final frame of the track is short."""
        self.pending = np.concatenate((self.pending, samples), axis=1)
        while self.pending.shape[1] >= _AAC_FRAME or (last and self.pending.shape[1]):
            chunk, self.pending = self.pending[:, :_AAC_FRAME], self.pending[:, _AAC_FRAME:]
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(chunk), format="fltp", layout=LAYOUTS[self.channels])
            frame.sample_rate, frame.pts, frame.time_base = self.rate, self.samples, Fraction(1, self.rate)
            self.samples += chunk.shape[1]
            self.output.mux(self.audio.encode(frame))

    def close(self):
        """Flush both encoders and finish the file."""
        try:
            self.output.mux(self.video.encode(None))
            if self.audio is not None:
                self.write_audio(np.zeros((self.channels, 0), dtype=np.float32), True)
                self.output.mux(self.audio.encode(None))
        finally:
            self.output.close()


def write_take(
    path: str,
    frames: Iterable[np.ndarray],
    *,
    width: int,
    height: int,
    fps: Fraction,
    deep: bool,
    pix_fmt: str,
    color: Tuple[str, str, str],
    encoder: str,
    crf: int,
    waveform: Optional[np.ndarray],
    rate: int,
    limit: int,
    tags: Mapping[str, str],
    check: Callable[[], None],
):
    """Encode tensor frames ``[n, H, W, 3]`` and an optional waveform ``[C, T]`` as one take, in process."""
    with open(path, "xb") as handle:
        writer = Writer(handle, width=width, height=height, fps=fps, pix_fmt=pix_fmt, encoder=encoder, crf=crf, color=color)
        try:
            for key, value in tags.items():
                writer.output.metadata[key] = value
            if waveform is not None:
                writer.add_audio(rate, waveform.shape[0])
            for chunk in frames:
                check()
                for picture in chunk:
                    frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(picture), format="rgb48le" if deep else "rgb24")
                    writer.write_frame(frame.reformat(format=pix_fmt, dst_colorspace=_MATRICES.get(color[2])))
            if waveform is not None:
                writer.write_audio(np.ascontiguousarray(waveform[:, :limit], dtype=np.float32))
        finally:
            writer.close()


def _correct(frame: av.VideoFrame, fix: Mapping[str, Any], index: int, pix_fmt: str) -> av.VideoFrame:
    """Apply the tapered luma and chroma adjustment to one opening frame."""
    weight = 1 - index / fix["taper"]
    deep = "10" in pix_fmt
    scale, top = (4, 1023) if deep else (1, 255)
    planes = []
    for plane, (gain, offset, zero) in zip(
        frame.planes,
        (
            (fix["luma_gain"] - 1, fix["luma_offset"] * 219 * scale, 16 * scale),
            (0.0, fix["cb_offset"] * 224 * scale, 0),
            (0.0, fix["cr_offset"] * 224 * scale, 0),
        ),
    ):
        data = np.frombuffer(plane, dtype="<u2" if deep else np.uint8).reshape(plane.height, -1).astype(np.float32)
        planes.append(np.clip(data + weight * (gain * (data - zero) + offset), 0, top))
    result = av.VideoFrame(frame.width, frame.height, pix_fmt)
    for plane, data in zip(result.planes, planes):
        plane.update(np.round(data).astype("<u2" if deep else np.uint8).tobytes())
    return result


def _pictures(entry: Mapping[str, Any], fps: Fraction) -> Iterator[av.VideoFrame]:
    """The source pictures of one entry in output order: by index, or by presentation time for other rates."""
    count = entry["frames"][1] - entry["frames"][0]
    if not entry["by_time"]:
        for index, (_, frame) in enumerate(_frames(entry["path"])):
            if index >= entry["last"]:
                return
            if index >= entry["first"]:
                yield frame
        return
    start, produced, held = Fraction(*entry["start_time"]), 0, None
    for stamp, frame in _frames(entry["path"]):
        # Output frame j shows the last source picture presented at or before its time.
        while held is not None and produced < count and start + Fraction(produced) / fps < stamp:
            yield held
            produced += 1
        held = frame
    while held is not None and produced < count:
        yield held
        produced += 1


def export(plan: Mapping[str, Any], output: str):
    """Encode the planned film once: conformed pictures by count, and one continuous sample timeline."""
    fps = Fraction(*plan["fps"])
    color = (plan["color"][2], plan["color"][3], plan["color"][1])
    with open(output, "xb") as handle:
        writer = Writer(
            handle,
            width=plan["width"],
            height=plan["height"],
            fps=fps,
            pix_fmt=plan["pix_fmt"],
            encoder=plan["encoder"],
            crf=plan["crf"],
            color=color,
        )
        try:
            if plan["sample_rate"]:
                writer.add_audio(plan["sample_rate"], plan["channels"])
            for entry in plan["entries"]:
                for index, picture in enumerate(_pictures(entry, fps)):
                    frame = picture.reformat(plan["width"], plan["height"], plan["pix_fmt"])
                    if entry["correction"] is not None and index < entry["correction"]["taper"]:
                        frame = _correct(frame, entry["correction"], index, plan["pix_fmt"])
                    writer.write_frame(frame)
                    print(f"frame={writer.frames}", flush=True)
                if plan["sample_rate"]:
                    writer.write_audio(_slot(entry, plan["sample_rate"], plan["channels"]))
        finally:
            writer.close()


def run(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Dispatch one fixed task; the parent supplies already contained absolute paths."""
    name = task.get("task")
    if name == "probe":
        return probe_json(probe(task["path"]))
    if name == "samples":
        return {"samples": count_samples(task["path"])}
    if name == "means":
        return {"means": means(task["path"], int(task["first"]), int(task["count"]))}
    if name == "export":
        export(task["plan"], task["output"])
        return {"done": True}
    raise ValueError("unsupported video task")


def main(stdin: Optional[BinaryIO] = None):
    """Read only the parent's bounded task description and answer with one JSON line."""
    source = stdin or sys.stdin.buffer
    try:
        print(json.dumps(run(json.loads(source.read(4 * 1024 * 1024)))), flush=True)
    except (av.FFmpegError, EOFError, StopIteration, UnsupportedMedia) as error:
        raise SystemExit(f"unsupported or incomplete media: {error}") from error
