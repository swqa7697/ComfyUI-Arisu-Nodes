"""Fixed CPU worker that stages selected media, never exposing original roots."""

from __future__ import annotations

import json
import math
import sys
import wave
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping

import av
import numpy as np
from PIL import Image

from .core import Resource, align_clip_frames, workbench_samples
from .media import open_media, origin_for, read_audio, read_image, source_file, streams, upright, validate_source
from .proxy_worker import LimitedOutput


def stage(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Write selected images, video intervals and audio with a total byte bound."""
    directory = Path(payload["directory"])
    roots: Mapping[str, str] = payload["roots"]
    assets: List[Dict[str, Any]] = []
    remaining = payload["max_bytes"]

    class BudgetOutput(LimitedOutput):
        """Account for partial bytes across concurrently open encoders."""

        def __init__(self, output: Any, limit: int = 2 * 1024 * 1024 * 1024):
            super().__init__(output, limit)

        def write(self, data: bytes) -> int:
            nonlocal remaining
            if len(data) > remaining:
                raise ValueError("prepared media exceeds the cache budget")
            count = super().write(data)
            remaining -= count
            return count

        def flush(self):
            self.handle.flush()

    def record(path: Path, kind: str, item: Resource, role: str, timestamp: Any = None):
        assets.append(
            {
                "id": path.stem,
                "file": path.name,
                "mime": kind,
                "resource_id": item.id,
                "role": role,
                "name": Path(item.path).name,
                "timestamp": timestamp,
            }
        )

    def picture(image: Image.Image, item: Resource, role: str, timestamp: Any = None):
        path = directory / (str(len(assets)) + ".png")
        with path.open("xb") as output:
            image.save(BudgetOutput(output, 16 * 1024 * 1024), format="PNG")
        record(path, "image/png", item, role, timestamp)

    def audio(item: Resource, role: str, base: Any = None, interval: Any = None):
        waveform, rate = read_audio(roots, item, base, interval)
        path = directory / (str(len(assets)) + ".wav")
        channels = waveform.shape[1]
        with path.open("xb") as output, wave.open(BudgetOutput(output), "wb") as encoded:
            encoded.setnchannels(channels)
            encoded.setsampwidth(2)
            encoded.setframerate(rate)
            for left in range(0, waveform.shape[-1], rate):
                pcm = np.clip(waveform[0, :, left : left + rate].T, -1, 1)
                encoded.writeframes((pcm * 32767).astype("<i2").tobytes())
        record(path, "audio/wav", item, role)

    for value in payload["resources"]:
        role = value["role"]
        item = Resource(**value["item"])
        if item.muted:
            continue
        validate_source(roots, item)
        if item.kind == "image":
            picture(Image.fromarray((read_image(roots, item)[0] * 255).round().astype(np.uint8)), item, role)
        elif item.kind == "audio":
            audio(item, role)
        else:
            start, end = item.clip
            count = align_clip_frames(math.floor((end - start) * 24 + 1e-7), payload["frame_count"])
            retained = set(workbench_samples(count, 8))
            path = directory / ("video-" + str(len(assets)) + ".webm")
            with source_file(roots, item) as source, open_media(source) as container:
                video, _ = streams(container)
                base = origin_for(video)
                container.seek(int((base + Fraction(str(start))) / video.time_base), stream=video, backward=True)
                with path.open("xb") as output_file, av.open(BudgetOutput(output_file), "w", format="webm") as output:
                    stream = output.add_stream("libvpx-vp9", rate=24)
                    stream.pix_fmt = "yuv420p"
                    stream.options = {"deadline": "realtime", "cpu-used": "6"}
                    previous = None
                    previous_time = None
                    index = 0

                    def emit(
                        frame: av.VideoFrame,
                        left: float,
                        right: float,
                        count: int = count,
                        start: float = start,
                        stream: Any = stream,
                        retained: Any = retained,
                        item: Resource = item,
                    ):
                        nonlocal index
                        while index < count and start + index / 24 < right:
                            if start + index / 24 < left - 1e-6:
                                raise ValueError("selected video has a timestamp gap")
                            image = upright(frame)
                            stream.width, stream.height = image.size
                            if index in retained:
                                picture(image, item, "reference_video_frame", index / 24)
                            encoded = av.VideoFrame.from_image(image)
                            encoded.pts, encoded.time_base = index, Fraction(1, 24)
                            for packet in stream.encode(encoded):
                                output.mux(packet)
                            index += 1

                    for frame in container.decode(video):
                        if frame.pts is None:
                            raise ValueError("video timestamps unavailable")
                        at = float(frame.pts * frame.time_base - base)
                        if previous is not None and at > previous_time:
                            emit(previous, previous_time, at)
                        previous, previous_time = frame, at
                        if index == count:
                            break
                    if index < count and previous is not None:
                        duration = (
                            float(previous.duration * previous.time_base) if previous.duration else 1 / float(video.average_rate or 24)
                        )
                        emit(previous, previous_time, previous_time + duration)
                    if index != count:
                        raise ValueError("selected video has incomplete coverage")
                    for packet in stream.encode():
                        output.mux(packet)
            record(path, "video/webm", item, role)
            if item.include_audio:
                # Separate selected soundtrack: the agent never receives excluded sound.
                audio(replace(item, clip=(start, start + count / 24)), "reference_soundtrack", base, (start, start + count / 24))
        validate_source(roots, item)
    return assets


def main():
    """Read only the parent's bounded validated job description."""
    payload = json.loads(sys.stdin.buffer.read(1024 * 1024))
    print(json.dumps(stage(payload)), flush=True)


if __name__ == "__main__":
    main()
