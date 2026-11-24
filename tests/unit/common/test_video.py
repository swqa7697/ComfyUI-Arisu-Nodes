"""Boundaries of the video segment contracts that no execute test reaches."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime
from fractions import Fraction
from typing import Any, Dict, List, Optional

import pytest

from src.arisu_nodes.common.media import UnsupportedMedia
from src.arisu_nodes.common.video import (
    AudioInfo,
    Capabilities,
    PcmSource,
    Probe,
    Source,
    VideoInfo,
    director_take_id,
    ffmetadata,
    parse_edit,
    parse_export_request,
    parse_take_context,
    plan_export,
    resolve_take_prefix,
    sample_boundary,
    suggest_correction,
    wav_header,
)
from src.arisu_nodes.common.video_ffmpeg import export_argv, parse_decoders, parse_encoders, parse_ffprobe, parse_framecrc

TAKE = "552564c1-1999-442e-a016-c1965b957d62"
NATIVE = Capabilities("ffmpeg", frozenset({"libx264", "libx265", "libsvtav1"}), frozenset({"h264", "hevc", "av1"}))


def row(**changes: Any) -> Dict[str, Any]:
    base = {
        "id": str(uuid.uuid4()),
        "source": "take",
        "take": "",
        "segment": "",
        "root": "output",
        "path": "films/a.mp4",
        "revision": "r",
        "included": True,
        "range": None,
        "audio": "auto",
        "join": {"correction": None, "fade": 0},
    }
    return {**base, **changes}


def edit(entries: List[Dict[str, Any]], output: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"version": 1, "output": output, "entries": entries}


def video(frames: int, fps: Fraction = Fraction(24), **changes: Any) -> VideoInfo:
    base = VideoInfo(
        "h264", "High", "avc1", 64, 64, "1:1", "yuv420p", fps, Fraction(1, 12288), frames, Fraction(0), Fraction(frames) / fps, True,
        ("tv", "bt709", "bt709", "iec61966-2-1"), "sha",
    )  # fmt: skip
    return replace(base, **changes)


def sound(frames: int, rate: int = 32000, **changes: Any) -> AudioInfo:
    return replace(AudioInfo("aac", "LC", rate, 2, "stereo", round(frames * rate / 24), Fraction(0), 1024, "sha"), **changes)


def source(frames: int, pcm: bool = True, silent: bool = False, **changes: Any) -> Source:
    companion = PcmSource("/o/a.wav", 32000, 2, round(frames * 32000 / 24)) if pcm and not silent else None
    probe = Probe("mov,mp4,m4a,3gp,3g2,mj2", video(frames), None if silent else sound(frames), True)
    return replace(Source("ok", "/o/a.mp4", "r", probe, None, companion), **changes)


def test_edit_lists_prefixes_and_requests_refuse_hostile_or_ambiguous_input():
    correction = {"luma_gain": 1.0, "luma_offset": 0.0, "cb_offset": 0.0, "cr_offset": 0.0, "taper": 12}
    basis = {"prev_revision": "a", "prev_end": 1, "revision": "b", "start": 0}
    spec = {"width": 64, "height": 64, "fps": [24, 1], "sample_rate": 32000, "channels": 2}
    refused = {
        "not json": "{",
        "other version": json.dumps({**edit([]), "version": 2}),
        "extra field": json.dumps({**edit([]), "roots": ["/"]}),
        "duplicate field": '{"version":1,"output":null,"entries":[],"entries":[]}',
        "duplicate id": edit([row(id=TAKE), row(id=TAKE)]),
        "bad id": edit([row(id="1")]),
        "absolute path": edit([row(path="/etc/passwd")]),
        "parent path": edit([row(path="films/../../a.mp4")]),
        "home path": edit([row(path="~/a.mp4")]),
        "drive path": edit([row(path="C:/a.mp4")]),
        "null byte": edit([row(path="a\x00.mp4")]),
        "extra entry field": edit([{**row(), "base": "/"}]),
        "empty range": edit([row(range=[4, 4])]),
        "negative range": edit([row(range=[-1, 4])]),
        "float range": edit([row(range=[0, 4.5])]),
        "long fade": edit([row(join={"correction": None, "fade": 51})]),
        "audio choice": edit([row(audio="external")]),
        "gain bound": edit([row(join={"correction": {**correction, "luma_gain": 1.5, "basis": basis}, "fade": 0})]),
        "chroma bound": edit([row(join={"correction": {**correction, "cb_offset": 0.05, "basis": basis}, "fade": 0})]),
        "taper bound": edit([row(join={"correction": {**correction, "taper": 97, "basis": basis}, "fade": 0})]),
        "no basis": edit([row(join={"correction": correction, "fade": 0})]),
        "odd output": edit([], {**spec, "width": 63}),
        "output rate": edit([], {**spec, "sample_rate": 12345}),
        "output fps": edit([], {**spec, "fps": [0, 1]}),
        "too many entries": edit([row() for _ in range(513)]),
        "too many included": edit([row() for _ in range(101)]),
        "too large": edit([row(segment="x" * 1000) for _ in range(300)]),
    }
    for case, value in refused.items():
        with pytest.raises(ValueError):
            parse_edit(value)
            pytest.fail(f"case={case!r}")
    # An entry that lost its location on import stays in the list, and exclusion lifts the included limit.
    kept = parse_edit(edit([row(path="", revision=""), *(row(included=False) for _ in range(150))], spec))
    assert kept.entries[0].path == "" and len(kept.entries) == 151 and kept.output.fps == 24

    now = datetime(2026, 11, 24, 9, 5, 7)
    prefixes = {
        ("", ""): ("arisu_video/videos", "clip", "arisu_video"),
        ("P/q", "shot"): ("P/q/videos", "shot", "P/q"),
        ("P/", " shot "): ("P/videos", "shot", "P"),
        ("%year%/%width%x%height%", "c"): ("2026/64x48/videos", "c", "2026/64x48"),
    }
    for case, (directory, stem, project) in prefixes.items():
        target = resolve_take_prefix(*case, 64, 48, now)
        assert (target.directory, target.stem, target.project) == (directory, stem, project), f"case={case!r}"
    for case in (
        ("..", "c"),
        ("P", "a/b"),
        ("P", "a\\b"),
        ("/abs", "clip"),
        ("%date:x%", "c"),
    ):
        with pytest.raises(ValueError):
            resolve_take_prefix(*case, 64, 48, now)
            pytest.fail(f"case={case!r}")
    # Only the location makes a Director take; a name that merely looks similar is an ordinary directory.
    takes = {
        f"P/director/{TAKE}": TAKE,
        f"arisu_director/{TAKE}": TAKE,
        f"director/{TAKE}": TAKE,
        f"P/directors/{TAKE}": None,
        "P/director/abc": None,
    }
    for case, expected in takes.items():
        assert director_take_id(case) == expected, f"case={case!r}"
    target = resolve_take_prefix("%year%/%width%x%height%", "ignored", 64, 48, now, TAKE)
    assert (target.directory, target.stem, target.project) == (f"2026/64x48/director/{TAKE}", "clip", "2026/64x48")
    assert parse_take_context("") == {"take": None, "segment": None, "predecessor": None, "transition": None}
    context = {"take": TAKE, "segment": "s", "predecessor": None, "transition": "cut"}
    assert parse_take_context(json.dumps(context)) == context
    for case in (
        "[]",
        '{"segment":"s"}',
        json.dumps({**context, "predecessor": "x"}),
        json.dumps({**context, "transition": "wipe"}),
        json.dumps({**context, "take": "../escape"}),
    ):
        with pytest.raises(ValueError):
            parse_take_context(case)
            pytest.fail(f"case={case!r}")
    assert parse_export_request("", "  ", "inherit", "av1", 63).name == "main"
    for case in (
        ("P", "a/b", "inherit", "h264", 18),
        ("P", ".hidden", "inherit", "h264", 18),
        ("P", "m", "copy", "h264", 18),
        ("P", "m", "encode", "h264", 52),
    ):
        with pytest.raises(ValueError):
            parse_export_request(*case)
            pytest.fail(f"case={case!r}")
    # The companion header declares IEEE float so readers do not take it for integer PCM.
    header = wav_header(2, 32000, 10)
    assert header[:4] == b"RIFF" and int.from_bytes(header[4:8], "little") == len(header) - 8 + 80 and header[20:22] == b"\x03\x00"
    assert ffmetadata({"a=b": "x;y#z\\\nnext"}) == ";FFMETADATA1\na\\=b=x\\;y\\#z\\\\\\\nnext\n"
    assert ffmetadata({"[CHAPTER]": "v"}) == ";FFMETADATA1\n\\[CHAPTER]=v\n"


def test_export_plan_keeps_cumulative_boundaries_and_follows_the_decision_table():
    # Ties round to even, and 29.97 fps boundaries come from the cumulative count, never from summed slots.
    assert [sample_boundary(frames, Fraction(24), 32000) for frames in (0, 243, 464, 668)] == [0, 324000, 618667, 890667]
    assert (sample_boundary(1, Fraction(2), 1), sample_boundary(3, Fraction(2), 1), sample_boundary(5, Fraction(2), 1)) == (0, 2, 2)
    ntsc = Fraction(30000, 1001)
    assert sample_boundary(30000, ntsc, 48000) == 48048000 and sample_boundary(1, ntsc, 48000) == 1602

    def plan(
        sources: List[Source], rows: Optional[List[Dict[str, Any]]] = None, caps: Capabilities = NATIVE, output: Any = None, **request: Any
    ):
        rows = rows or [row() for _ in sources]
        document = parse_edit(edit(rows, output))
        values = {"project": "P", "name": "main", "encoding": "inherit", "codec": "h264", "crf": 18, **request}
        return plan_export(
            document, {entry.id: found for entry, found in zip(document.entries, sources)}, parse_export_request(**values), caps
        )

    three = [source(frames) for frames in (243, 221, 204)]
    whole = plan(three)
    assert (whole.frames, whole.samples, whole.video_operation, whole.audio_operation, whole.crf) == (668, 890667, "copy", "encode", None)
    spec = {"width": 64, "height": 64, "fps": [24, 1], "sample_rate": 32000, "channels": 2}
    other = replace(three[1], probe=replace(three[1].probe, video=video(221, extradata="other")))
    late = replace(three[1], probe=replace(three[1].probe, video=video(221, start=Fraction(1, 24))))
    coarse = replace(three[1], probe=replace(three[1].probe, video=video(221, time_base=Fraction(1, 1000))))
    matroska = replace(three[1], probe=replace(three[1].probe, container="matroska,webm"))
    blind = replace(three[1], probe=replace(three[1].probe, evidence=False))
    # Each row: sources, rows, request and backend -> the video operation and the words that explain it.
    table = {
        "explicit codec": ({"sources": three, "encoding": "encode", "codec": "av1", "crf": 30}, "encode", "chosen"),
        "frame-exact trim": ({"sources": three, "rows": [row(), row(range=[2, 221]), row()]}, "encode", "trim"),
        "different settings": ({"sources": [three[0], other]}, "encode", "settings"),
        "off the grid": ({"sources": [three[0], late]}, "encode", "frame grid"),
        "inexact time base": ({"sources": [three[0], coarse]}, "encode", "settings"),
        "other container": ({"sources": [three[0], matroska]}, "encode", "MP4"),
        "no ffprobe": ({"sources": [three[0], blind]}, "encode", "ffprobe"),
        "control character in a path": (
            {"sources": [three[0], replace(three[1], path="/o/a\nfile '/etc/passwd'.mp4")]},
            "encode",
            "listed",
        ),
        "pyav backend": ({"sources": three, "caps": Capabilities("pyav", NATIVE.encoders)}, "encode", "PyAV"),
        "conformed size": (
            {"sources": [three[0], replace(three[1], probe=replace(three[1].probe, video=video(221, width=128)))], "output": spec},
            "encode",
            "conformed",
        ),
    }
    for case, (arguments, operation, words) in table.items():
        made = plan(**arguments)
        assert made.video_operation == operation and words in made.video_reason and made.ready, f"case={case!r}"
        assert made.encoder is not None and made.audio_operation == "encode", f"case={case!r}"
    # Inherit keeps the source codec and a recorded CRF when an encode is forced; an unknown CRF uses the preset.
    recorded = [replace(item, record={"video": {"crf": 14}}) for item in three]
    assert (plan(recorded, rows=[row(), row(range=[1, 221]), row()]).crf, plan(three, rows=[row(), row(range=[1, 221]), row()]).crf) == (
        14,
        18,
    )
    # One whole segment may keep its own AAC track; any join with sound rebuilds it; a silent film has no track.
    alone = plan([source(48, pcm=False)])
    assert (alone.video_operation, alone.audio_operation) == ("copy", "copy")
    assert plan([source(48, pcm=False), source(48, pcm=False)]).audio_operation == "encode"
    quiet = plan([source(48, silent=True), source(24, silent=True)])
    assert (quiet.video_operation, quiet.audio_operation, quiet.samples, quiet.sample_rate) == ("copy", None, 0, 0)
    mixed = plan([source(48), source(24, silent=True), source(48)])
    assert [entry.audio for entry in mixed.entries] == ["pcm", "none", "pcm"] and [entry.samples for entry in mixed.entries][1] == (
        64000,
        96000,
    )
    assert "anullsrc=r=32000:cl=stereo,atrim=end_sample=32000" in " ".join(export_argv("ffmpeg", mixed, "s", "o"))

    # Decisions the user must make come back as needs, and the plan still shows provisional totals.
    hevc = replace(three[1], probe=replace(three[1].probe, video=video(221, codec="hevc", tag="hvc1")))
    wide = replace(three[1], pcm=PcmSource("/o/w.wav", 48000, 2, 442000))
    odd = replace(three[0], probe=replace(three[0].probe, video=video(243, width=63)))
    lost = replace(three[1], pcm=None, pcm_lost=True)
    needs = {
        "mixed codecs": ([three[0], hevc], "choose_codec"),
        "mixed sample rates": ([three[0], wide], "confirm_output"),
        "mixed frame rates": (
            [three[0], replace(three[1], probe=replace(three[1].probe, video=video(221, Fraction(30))))],
            "confirm_output",
        ),
        "variable rate": ([replace(three[0], probe=replace(three[0].probe, video=video(243, constant=False)))], "confirm_output"),
        "odd size": ([odd], "confirm_output"),
        "rate aac cannot carry": ([replace(three[0], pcm=PcmSource("/o/a.wav", 12345, 2, 125000))], "confirm_output"),
        "lost pcm": ([three[0], lost], "switch_audio"),
    }
    for case, (sources, kind) in needs.items():
        made = plan(sources)
        assert [need["kind"] for need in made.needs] == [kind] and not made.ready and made.frames > 0, f"case={case!r}"
    assert plan([odd]).needs[0]["suggested"]["width"] == 64
    # A source at another rate is placed by presentation time on the confirmed timeline.
    thirty = replace(three[1], probe=replace(three[1].probe, video=video(300, Fraction(30))))
    timed = plan([three[0], thirty], output=spec, encoding="encode")
    assert [entry.frames for entry in timed.entries] == [(0, 243), (243, 483)] and timed.entries[1].by_time and timed.ready
    assert "fps=24/1,tpad=stop=-1:stop_mode=clone,trim=end_frame=240" in " ".join(export_argv("ffmpeg", timed, "s", "o"))
    # A head skip moves the audio start to the same time boundary, and a short source is reported, not hidden.
    skipped = plan([three[0], replace(three[1], pcm=replace(three[1].pcm, samples=200000))], rows=[row(), row(range=[3, 221])])
    assert skipped.entries[1].audio_offset == 4000 and skipped.entries[1].samples == (324000, 614667)
    assert len(skipped.warnings) == 1 and "entry 2" in skipped.warnings[0] and "shorter" in skipped.warnings[0] and skipped.ready
    # A picture that starts after its embedded sound takes that lead into the audio offset; saved PCM starts with the picture.
    delayed = replace(three[1], pcm=None, probe=replace(three[1].probe, video=video(221, start=Fraction(1, 2))))
    assert (
        plan([three[0], delayed]).entries[1].audio_offset == 16000
        and plan([three[0], replace(delayed, pcm=three[1].pcm)]).entries[1].audio_offset == 0
    )
    # States and capabilities that block a plan outright.
    assert plan([three[0], replace(three[1], state="changed")]).states[1][1] == "changed"
    assert plan([three[0]], rows=[row(range=[0, 999])]).states[0][1:] == ("unusable", "the frame interval is outside the video")
    assert plan(three, rows=[row(included=False) for _ in three]).errors == ("select at least one video",)
    bare = plan(three, encoding="encode", codec="h265", caps=Capabilities("ffmpeg", frozenset({"libx264"}), frozenset({"hevc"})))
    assert not bare.ready and "no h265 encoder" in bare.errors[0] and "entry 1" in bare.errors[1] and "h264 decoder" in bare.errors[1]

    # Probe parsing: cover art is not a video stream, a millisecond container is still constant, and
    # a listing without ffprobe carries timing but no evidence for a packet copy.
    packets = [{"stream_index": 1, "pts": stamp, "duration": 42} for stamp in (0, 42, 83, 125)]
    listing = {
        "format": {"format_name": "matroska,webm"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {
                "index": 1,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 64,
                "height": 64,
                "avg_frame_rate": "24/1",
                "time_base": "1/1000",
            },
        ],
        "packets": packets,
    }
    probed = parse_ffprobe(json.dumps(listing))
    assert (probed.video.codec, probed.video.frames, probed.video.constant, probed.audio, probed.evidence) == ("h264", 4, True, None, True)
    packets[2]["pts"] = 99
    assert not parse_ffprobe(json.dumps(listing)).video.constant
    for case in ("{", json.dumps({"format": {}, "streams": []}), json.dumps({**listing, "packets": [{"stream_index": 1}]})):
        with pytest.raises(UnsupportedMedia):
            parse_ffprobe(case)
            pytest.fail(f"case={case!r}")
    crc = (
        "#tb 0: 1/12288\n#media_type 0: video\n#codec_id 0: h264\n#dimensions 0: 64x64\n#sar 0: 1/1\n#tb 1: 1/32000\n#media_type 1: audio\n"
    )
    crc += "#codec_id 1: aac\n#sample_rate 1: 32000\n#channel_layout_name 1: stereo\n"
    crc += "0, -1024, 0, 512, 3015, 0x9aa06fe8\n1, -1024, -1024, 1024, 23, 0x0\n0, -512, 512, 512, 80, 0x1\n1, 0, 0, 1024, 23, 0x0\n"
    listed = parse_framecrc(crc)
    assert (listed.video.frames, listed.video.fps, listed.video.pix_fmt, listed.audio.samples, listed.evidence) == (
        2,
        Fraction(24),
        "",
        1024,
        False,
    )
    assert parse_encoders(" V....D libx264              libx264 H.264 (codec h264)\n A....D aac                  AAC\n ------\n") == {
        "libx264",
        "aac",
    }
    assert parse_decoders(" V....D libdav1d             dav1d AV1 decoder (codec av1)\n VFS..D h264                 H.264\n") == {
        "av1",
        "h264",
    }

    # A correction is suggested only for a persistent step: beyond normal variation, with every frame on one side.
    level = [(0.25, 0.0, 0.0)] * 12
    stepped = suggest_correction(level, [(0.33 + index * 0.0005, 0.0, 0.01) for index in range(12)])
    assert stepped["stable"] and stepped["correction"]["luma_offset"] == -0.06 and stepped["correction"]["cr_offset"] == -0.01
    for case, incoming in {
        "same level": level,
        "moving shot": [(0.25 + index * 0.02, 0.0, 0.0) for index in range(12)],
        "flash": [(0.9, 0.0, 0.0), *level[1:]],
    }.items():
        assert suggest_correction(level, incoming) == {"stable": False, "correction": None}, f"case={case!r}"
    assert suggest_correction(level[:1], level) is None
