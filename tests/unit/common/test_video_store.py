"""Filesystem ownership of video segments: counters, publication order, export versions and verified deletion."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.arisu_nodes.common.media import revision_for
from src.arisu_nodes.common.video_store import (
    delete_take,
    deletion_plan,
    discard_take,
    discard_workspace,
    export_workspace,
    find_export,
    list_takes,
    predicted_export,
    publish_export,
    publish_take,
    reading,
    reserve_take,
    take_companion,
)

TAKE = "552564c1-1999-442e-a016-c1965b957d62"
JOB = "0c5d6a2e-3d55-4a51-9d0a-2f5e0c8e6b11"


def publish(output: Path, directory: str, stem: str = "clip", origin: str = "ordinary", sound: bool = True) -> Dict[str, Any]:
    """Publish a take the way the saver does, with placeholder bytes for the media."""
    reservation = reserve_take(str(output), directory, stem)
    Path(reservation.part("video.part")).write_bytes(b"video")
    if sound:
        Path(reservation.part("audio.wav.part")).write_bytes(b"\x00" * 64)

    def build(video: str, audio: Any) -> Dict[str, Any]:
        relative = f"{directory}/{reservation.name}"
        pcm = {"root": "output", "path": f"{relative}.arisu/audio.wav", "revision": revision_for(os.stat(audio))} if audio else None
        return {
            "version": 1,
            "kind": "arisu.take",
            "take": TAKE,
            "origin": origin,
            "video": {
                "root": "output",
                "path": f"{relative}.mp4",
                "revision": revision_for(os.stat(video)),
                "frames": 2,
                "fps": [24, 1],
                "width": 2,
                "height": 2,
                "codec": "h264",
            },
            "audio": {"rate": 8, "channels": 2, "samples": 8, "pcm": pcm} if audio else None,
        }

    return publish_take(reservation, sound, build)


def test_takes_and_exports_are_claimed_published_and_deleted_without_touching_other_files(tmp_path: Path):
    output, outside = tmp_path / "output", tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    videos = output / "P" / "videos"

    # Concurrent saves of one stem each get their own counter; a latent slot beside them takes none.
    videos.mkdir(parents=True)
    (videos / "clip_00007.safetensors").write_bytes(b"latent")
    (videos / "clip_00002_.mp4").symlink_to(outside / "planted.mp4")
    claimed: List[int] = []
    threads = [threading.Thread(target=lambda: claimed.append(reserve_take(str(output), "P/videos", "clip").counter)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # The planted name at 2 is a collision even though it dangles, so numbering continues after it.
    assert sorted(claimed) == list(range(3, 11)) and not (outside / "planted.mp4").exists()
    for counter in claimed:
        os.rmdir(videos / f"clip_{counter:05}_.arisu")
    (output / "escape").symlink_to(outside)
    for directory, stem in (("escape", "clip"), ("../outside", "clip"), ("P/videos", ""), ("P/videos", "..")):
        with pytest.raises(ValueError):
            reserve_take(str(output), directory, stem)
    assert not list(outside.iterdir())

    # The record is written last. A failure before it leaves no video, no companion and no directory behind.
    failing = reserve_take(str(output), "P/videos", "clip")
    Path(failing.part("video.part")).write_bytes(b"video")
    Path(failing.part("audio.wav.part")).write_bytes(b"audio")
    before = sorted(os.listdir(videos))
    with pytest.raises(RuntimeError):
        publish_take(failing, True, lambda video, audio: (_ for _ in ()).throw(RuntimeError("probe failed")))
    assert os.path.exists(failing.video) and not os.path.exists(failing.part("take.json"))
    discard_take(failing)
    assert sorted(os.listdir(videos)) == [name for name in before if name != "clip_00003_.arisu"] and not os.path.exists(failing.video)
    # A name that appears at the claimed number during the save moves the take to the next one.
    racing = reserve_take(str(output), "P/videos", "clip")
    Path(racing.part("video.part")).write_bytes(b"video")
    Path(racing.video).write_bytes(b"someone else's file")
    moved = publish_take(racing, False, lambda video, audio: {"video": os.path.basename(video)})
    assert (
        moved == {"video": f"clip_{racing.counter:05}_.mp4"}
        and racing.counter == 4
        and (videos / "clip_00003_.mp4").read_bytes() == b"someone else's file"
    )

    first = publish(output, "P/videos", "shot")
    directed = publish(output, f"P/director/{TAKE}", origin="director")
    (output / "P" / "director" / TAKE / "clip_00002_.mp4").write_bytes(b"stock render")
    (output / "arisu_director" / TAKE).mkdir(parents=True)
    (output / "arisu_director" / TAKE / "clip_00001_.mp4").write_bytes(b"legacy render")
    (output / "P" / "director" / "notes").mkdir()
    (videos / "linked_00001_.mp4").symlink_to(outside / "planted.mp4")
    # The browser lists published takes and Director renders; bare files, symlinks and other folders are not offered.
    listed = list_takes(str(output), "P", False)
    renders = [f"P/director/{TAKE}/clip_00001_.mp4", f"P/director/{TAKE}/clip_00002_.mp4"]
    assert listed == ["P/videos/clip_00004_.mp4", "P/videos/shot_00001_.mp4", *renders]
    assert (
        list_takes(str(output), "P", True)[-1] == f"arisu_director/{TAKE}/clip_00001_.mp4"
        and list_takes(str(output), "missing", True)[:-1] == []
    )

    path, revision = first["video"]["path"], first["video"]["revision"]
    record, pcm, lost = take_companion(str(output), path, revision)
    assert record["take"] == TAKE and pcm.samples == 8 and not lost
    # A record that names another revision is not this file's record; replaced PCM is reported as lost.
    assert take_companion(str(output), path, "older") == (None, None, False)
    companion = output / first["audio"]["pcm"]["path"]
    companion.write_bytes(b"\x00" * 64)
    assert take_companion(str(output), path, revision)[1:] == (None, True)
    record_file = companion.with_name("take.json")
    saved = record_file.read_text()
    record_file.write_text(
        json.dumps(
            {
                **json.loads(saved),
                "audio": {
                    "rate": 8,
                    "channels": 2,
                    "samples": 8,
                    "pcm": {**first["audio"]["pcm"], "revision": revision_for(companion.stat())},
                },
            }
        )
    )

    # Deletion is authorized by the server's own findings, never by the request.
    for case, (target, wanted) in {
        "director take": (directed["video"]["path"], directed["video"]["revision"]),
        "stock render": (f"P/director/{TAKE}/clip_00002_.mp4", "any"),
        "old revision": (path, "older"),
        "no record": ("P/videos/clip_00003_.mp4", revision_for((videos / "clip_00003_.mp4").stat())),
    }.items():
        with pytest.raises(PermissionError):
            deletion_plan(str(output), target, wanted)
            pytest.fail(f"case={case!r}")
    with pytest.raises(FileNotFoundError):
        deletion_plan(str(output), "P/videos/gone_00001_.mp4", "any")
    # A link that leaves output is refused by containment before anything is inspected.
    for target in ("P/videos/linked_00001_.mp4", "escape/clip_00001_.mp4"):
        with pytest.raises(ValueError):
            deletion_plan(str(output), target, "any")
    assert [os.path.basename(name) for name, _ in deletion_plan(str(output), path, revision)] == [
        "take.json",
        "audio.wav",
        "shot_00001_.mp4",
    ]
    # A record replaced by a symlink no longer proves ownership.
    record_file.unlink()
    record_file.symlink_to(outside / "take.json")
    (outside / "take.json").write_text(saved)
    with pytest.raises(PermissionError):
        deletion_plan(str(output), path, revision)
    record_file.unlink()
    record_file.write_text(json.dumps({**json.loads(saved), "audio": None}))
    # While an export reads the video the deletion waits; afterwards only registered files go, and the user's stay.
    (companion.parent / "notes.txt").write_text("mine")
    video = str((output / path).resolve())
    with reading([video]), reading([video]):
        assert delete_take(str(output), path, revision) == "deferred" and os.path.exists(video)
    assert (
        not os.path.exists(video)
        and not record_file.exists()
        and companion.exists()
        and (companion.parent / "notes.txt").read_text() == "mine"
    )

    # A deletion that cannot complete is refused, never reported as done, and the take stays whole and listed.
    locked = publish(output, "P/videos", "locked", sound=False)
    videos.chmod(0o555)
    try:
        assert delete_take(str(output), locked["video"]["path"], locked["video"]["revision"]) == "refused"
    finally:
        videos.chmod(0o755)
    assert (output / locked["video"]["path"]).is_file() and (videos / "locked_00001_.arisu" / "take.json").is_file()
    assert (
        delete_take(str(output), locked["video"]["path"], locked["video"]["revision"]) == "deleted"
        and not (videos / "locked_00001_.arisu").exists()
    )

    # Exports: the directory appears complete in one rename, concurrent jobs take different versions.
    assert predicted_export(str(output), "P", "main") == "P/exports/main_00001/main_00001.mp4"
    workspaces = [export_workspace(str(output), "P", job) for job in (JOB, TAKE)]
    with pytest.raises(FileExistsError):
        export_workspace(str(output), "P", JOB)
    records = []
    for job, workspace in zip((JOB, TAKE), workspaces):
        film = Path(workspace) / "film.mp4"
        film.write_bytes(b"film " + job.encode())

        def build(counter: int, named: str, job: str = job) -> Dict[str, Any]:
            film_path = f"P/exports/main_{counter:05}/main_{counter:05}.mp4"
            return {
                "version": 1,
                "kind": "arisu.sequence",
                "job": job,
                "counter": counter,
                "film": {"root": "output", "path": film_path, "revision": revision_for(os.stat(named))},
            }

        if job == TAKE:
            # Another export published version 2 after this one chose its number.
            (output / "P" / "exports" / "main_00002").mkdir()
            (output / "P" / "exports" / "main_00002" / "keep.txt").write_text("other export")
        records.append(publish_export(workspace, "main", str(film), build))
    exports = output / "P" / "exports"
    assert [record["counter"] for record in records] == [1, 3]
    assert sorted(os.listdir(exports)) == ["main_00001", "main_00002", "main_00003"] and sorted(os.listdir(exports / "main_00003")) == [
        "main_00003.mp4",
        "sequence.json",
    ]
    assert predicted_export(str(output), "P", "main").endswith("main_00004/main_00004.mp4")
    # The same job finds its export again, until its film is no longer the recorded file.
    assert find_export(str(output), "P", "main", JOB)["counter"] == 1 and find_export(str(output), "P", "main", "another") is None
    (exports / "main_00001" / "main_00001.mp4").write_bytes(b"replaced")
    assert find_export(str(output), "P", "main", JOB) is None
    # An abandoned workspace is swept by a later job; a current one and published versions are kept.
    stale, current = exports / ".arisu-tmp-old", exports / ".arisu-tmp-new"
    stale.mkdir()
    current.mkdir()
    os.utime(stale, (time.time() - 3 * 24 * 3600,) * 2)
    discard_workspace(export_workspace(str(output), "P", JOB))
    assert not stale.exists() and current.exists() and (exports / "main_00002" / "keep.txt").exists()
    discard_workspace(str(exports / "main_00002"))
    assert (exports / "main_00002" / "keep.txt").exists() and not list(outside.glob("*.mp4"))
