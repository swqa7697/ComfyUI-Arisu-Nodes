"""Fixed subprocess entrypoint for cancellable CPU-only playback conversion."""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from typing import Any, BinaryIO, Dict

import av

from .core import Resource
from .media import open_media, origin_for, source_file, streams, upright


class LimitedOutput:
    """Enforce the parent's remaining byte budget before each encoder write."""

    def __init__(self, handle: BinaryIO, limit: int):
        self.handle = handle
        self.limit = limit

    def write(self, data: bytes) -> int:
        if self.handle.tell() + len(data) > self.limit:
            raise ValueError("playback cache capacity exceeded")
        return self.handle.write(data)

    def tell(self) -> int:
        return self.handle.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.handle.seek(offset, whence)

    def writable(self) -> bool:
        return True


def convert(payload: Dict[str, Any]):
    """Convert only the parent-authorized source into its exclusively created file."""
    item = Resource(**payload["item"])
    with source_file(payload["roots"], item) as source, open_media(source) as container:
        video, audio = streams(container)
        origin = origin_for(video or audio)
        with open(payload["output"], "xb") as file, av.open(LimitedOutput(file, payload["max_bytes"]), "w", format="webm") as output:
            vout = output.add_stream("libvpx-vp9", rate=video.average_rate or 24) if video else None
            if vout:
                vout.time_base = vout.codec_context.time_base = Fraction(1, 1000)
            aout = output.add_stream("libopus", rate=48000) if audio else None
            if aout:
                aout.layout = "stereo"
                resampler = av.AudioResampler(format="flt", layout="stereo", rate=48000)
            selected = [stream for stream in (video, audio) if stream is not None]
            last_progress = -1
            audio_position = 0
            for packet in container.demux(selected):
                for frame in packet.decode():
                    if frame.pts is None:
                        raise ValueError("media timestamps are unavailable")
                    time = frame.pts * frame.time_base - origin
                    if time < 0:
                        continue
                    if packet.stream == video:
                        picture = upright(frame)
                        vout.width, vout.height = picture.size
                        vout.pix_fmt = "yuv420p"
                        vout.options = {"deadline": "realtime", "cpu-used": "6"}
                        converted = av.VideoFrame.from_image(picture)
                        converted.pts = round(time * 1000)
                        converted.time_base = Fraction(1, 1000)
                        for encoded in vout.encode(converted):
                            output.mux(encoded)
                    else:
                        # Opus resampling is for browser playback only; execution uses originals.
                        frame.pts = round(time * frame.sample_rate)
                        frame.time_base = Fraction(1, frame.sample_rate)
                        for converted in resampler.resample(frame):
                            converted.pts = round(time * 48000) if converted.pts is None else converted.pts
                            converted.time_base = Fraction(1, 48000)
                            audio_position = converted.pts + converted.samples
                            for encoded in aout.encode(converted):
                                output.mux(encoded)
                    progress = min(99, int(float(time) / payload["duration"] * 100))
                    if progress > last_progress:
                        print(json.dumps({"progress": progress}), flush=True)
                        last_progress = progress
            if aout:
                for converted in resampler.resample(None):
                    converted.pts = audio_position
                    converted.time_base = Fraction(1, 48000)
                    for encoded in aout.encode(converted):
                        output.mux(encoded)
            for stream in (vout, aout):
                if stream:
                    for encoded in stream.encode(None):
                        output.mux(encoded)


if __name__ == "__main__":
    convert(json.loads(sys.stdin.buffer.read(1024 * 1024)))
