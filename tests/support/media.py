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
