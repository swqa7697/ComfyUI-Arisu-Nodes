"""Fixed CPU worker preparing visual attachments without audio or transcoding."""

from __future__ import annotations

import json
import sys
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping

import av
from PIL import Image, ImageOps

from ..common.core import open_raster_image
from .core import Resource
from .media import open_media, origin_for, source_file, streams, upright, validate_workbench_source
from .workbench_images import encode_image


def stage(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cache cropped images and up to eight distinct presentation-time video stills."""
    directory = Path(payload["directory"])
    roots: Mapping[str, str] = payload["roots"]
    assets: List[Dict[str, Any]] = []
    remaining = payload["max_bytes"]

    def picture(image: Image.Image, item: Resource, role: str, **metadata: Any):
        nonlocal remaining
        identifier = uuid.uuid4().hex
        path = directory / (identifier + ".webp")
        with path.open("xb") as output:
            dimensions = encode_image(image, output, remaining)
        remaining -= path.stat().st_size
        assets.append(
            {
                "id": identifier,
                "file": path.name,
                "mime": "image/webp",
                "resource_id": item.id,
                "role": role,
                "name": Path(item.path).name,
                **dimensions,
                **metadata,
            }
        )

    for value in payload["resources"]:
        role = value["role"]
        item = Resource(**value["item"])
        if item.muted:
            continue
        validate_workbench_source(roots, item)
        if item.kind == "image":
            with source_file(roots, item) as source, open_raster_image(source) as image:
                image = ImageOps.exif_transpose(image)
                if item.crop:
                    left, top, width, height = item.crop
                    image = image.crop((left, top, left + width, top + height))
                picture(image, item, role)
        elif item.kind == "video":
            start, end = item.clip
            targets = [start + (end - start) * index / 7 for index in range(8)]
            target_index = 0
            sequence = 0
            with source_file(roots, item) as source, open_media(source) as container:
                video, _ = streams(container)
                base = origin_for(video)
                container.seek(int((base + Fraction(str(start))) / video.time_base), stream=video, backward=True)
                previous = None
                previous_time = None

                def emit(
                    frame: av.VideoFrame,
                    left: float,
                    right: float,
                    targets: List[float] = targets,
                    start: float = start,
                    end: float = end,
                    item: Resource = item,
                ):
                    nonlocal target_index, sequence
                    selected = False
                    while target_index < len(targets):
                        target = targets[target_index]
                        # The exclusive clip end belongs to the preceding displayed frame.
                        covered = target < right or (target_index == 7 and end <= right + 1e-7)
                        if not covered:
                            break
                        if target < left - 1e-7:
                            raise ValueError("selected video has incomplete coverage")
                        selected = True
                        target_index += 1
                    if selected:
                        picture(
                            upright(frame),
                            item,
                            "reference_video_frame",
                            sequence_index=sequence,
                            timestamp=max(0.0, left - start),
                            source_timestamp=left,
                        )
                        sequence += 1

                for frame in container.decode(video):
                    if frame.pts is None:
                        raise ValueError("video timestamps unavailable")
                    at = float(frame.pts * frame.time_base - base)
                    if previous is not None:
                        if at <= previous_time:
                            raise ValueError("video timestamps are not increasing")
                        emit(previous, previous_time, at)
                    if target_index == len(targets):
                        break
                    previous, previous_time = frame, at
                if target_index < len(targets) and previous is not None:
                    duration = float(previous.duration * previous.time_base) if previous.duration else 1 / float(video.average_rate or 24)
                    emit(previous, previous_time, previous_time + duration)
                if target_index != len(targets):
                    raise ValueError("selected video has incomplete coverage")
        # Audio remains metadata/notes only, including video soundtracks.
        validate_workbench_source(roots, item)
    return assets


def main():
    """Read only the parent's bounded validated job description."""
    payload = json.loads(sys.stdin.buffer.read(1024 * 1024))
    print(json.dumps(stage(payload)), flush=True)


if __name__ == "__main__":
    main()
