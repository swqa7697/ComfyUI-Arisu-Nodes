"""Small synthetic media fixtures shared by execute, route, and worker scenarios."""

from __future__ import annotations

import wave
from fractions import Fraction
from pathlib import Path
from typing import List, Optional

import av
import numpy as np
from PIL import Image


def make_video(path: Path, fps: int = 24, seconds: int = 1, timestamps: Optional[List[int]] = None):
    """Write lossless solid-color frames whose red value identifies source order."""
    with av.open(str(path), "w", format="matroska") as output:
        stream = output.add_stream("ffv1", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 65, 49, "bgr0"
        if timestamps:
            stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        for index in range(len(timestamps) if timestamps else fps * seconds):
            frame = av.VideoFrame.from_image(Image.new("RGB", (65, 49), (index % 256, 0, 0)))
            frame.pts = timestamps[index] if timestamps else index
            frame.time_base = Fraction(1, 1000) if timestamps else Fraction(1, fps)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


def make_audio(path: Path):
    """Write a one-second mono constant waveform at its native 8 kHz rate."""
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(np.full(8000, 8192, dtype="<i2").tobytes())


def make_av(path: Path):
    """Write video starting at 2s with a mono soundtrack starting 250ms later."""
    with av.open(str(path), "w", format="matroska") as output:
        video = output.add_stream("ffv1", rate=24)
        video.width, video.height, video.pix_fmt = 65, 49, "bgr0"
        audio = output.add_stream("pcm_s16le", rate=8000)
        audio.layout = "mono"
        for index in range(48):
            frame = av.VideoFrame.from_image(Image.new("RGB", (65, 49), (index, 0, 0)))
            frame.pts, frame.time_base = 48 + index, Fraction(1, 24)
            for packet in video.encode(frame):
                output.mux(packet)
        for index in range(15):
            frame = av.AudioFrame.from_ndarray(np.full((1, 800), 8192, dtype=np.int16), format="s16", layout="mono")
            frame.sample_rate = 8000
            frame.pts, frame.time_base = 18000 + index * 800, Fraction(1, 8000)
            for packet in audio.encode(frame):
                output.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode(None):
                output.mux(packet)


def marker_clip(
    frames: int, rate: int, fps: int = 24, flashes: Optional[List[int]] = None, clicks: Optional[List[int]] = None, value: float = 0.25
):
    """Build flat grey frames ``[N, 64, 64, 3]`` (the smallest size every AV1 encoder accepts) with white flash frames, and stereo sound ``[2, T]`` with unit clicks.

    A flash and a click placed at the same time prove where picture and sound meet after encoding.
    """
    images = np.full((frames, 64, 64, 3), value, dtype=np.float32)
    for index in flashes or []:
        images[index] = 1.0
    sound = np.zeros((2, round(frames * rate / fps)), dtype=np.float32)
    for index in clicks or []:
        sound[:, index : index + 32] = 0.9
    return images, sound


def read_markers(path: Path):
    """Decode a saved video: frame count, flash frame indexes and times, valid sample count, and click start samples."""
    with av.open(str(path)) as container:
        video = container.streams.video[0]
        flashes, times, count = [], [], 0
        for frame in container.decode(video):
            if frame.to_ndarray(format="gray").mean() > 180:
                flashes.append(count)
                times.append(float(frame.pts * frame.time_base))
            count += 1
    samples, clicks = 0, []
    with av.open(str(path)) as container:
        if container.streams.audio:
            audio = container.streams.audio[0]
            resampler = av.AudioResampler(format="fltp", layout=audio.layout, rate=audio.rate)
            pieces = [converted.to_ndarray() for frame in container.decode(audio) for converted in resampler.resample(frame)]
            wave_form = np.concatenate(pieces, axis=1) if pieces else np.zeros((1, 0), dtype=np.float32)
            # PyAV applies the container's leading trim but not its trailing one; the stream duration marks the valid end.
            if audio.duration:
                wave_form = wave_form[:, : round(audio.duration * audio.time_base * audio.rate)]
            samples = wave_form.shape[1]
            loud = np.flatnonzero(np.abs(wave_form[0]) > 0.4)
            clicks = [int(index) for position, index in enumerate(loud) if position == 0 or index - loud[position - 1] > 64]
    return {"frames": count, "flashes": flashes, "times": times, "samples": samples, "clicks": clicks}
