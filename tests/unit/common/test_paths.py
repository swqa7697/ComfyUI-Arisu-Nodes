"""Startup configuration and its fail-closed filesystem boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.arisu_nodes.common import paths


def test_external_roots_are_local_validated_and_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    directory = tmp_path / "__arisu_nodes"
    config = directory / "config.arisu.jsonc"
    photos = tmp_path / "photos"
    photos.mkdir()
    monkeypatch.setattr(paths, "_roots", None)
    # Neither requests nor a legacy pack-local allowlist initialize roots.
    (tmp_path / "arisu_paths.json").write_text(json.dumps({"roots": {"photos": str(photos)}}))
    assert paths.image_roots("input", "output") == {"input": "input", "output": "output"}
    assert not directory.exists()
    paths.initialize_roots(directory)
    template = config.read_bytes()
    assert paths.parse_roots(template.decode()) == {}
    config.write_text(json.dumps({"roots": {"photos": str(photos)}}))
    # Runtime edits and repeated startup callbacks do not expand authorization or overwrite files.
    paths.initialize_roots(directory)
    assert "photos" not in paths.external_roots()
    assert config.read_bytes() != template

    def restart():
        monkeypatch.setattr(paths, "_roots", None)
        paths.initialize_roots(directory)

    restart()
    assert paths.select_root(paths.external_roots(), "photos") == str(photos)
    with pytest.raises(TypeError):
        paths.external_roots()["extra"] = str(photos)
    with pytest.raises(ValueError):
        paths.select_root(paths.external_roots(), "unknown")
    # Comment markers inside a quoted filesystem path must remain literal.
    unusual = photos / 'quote"back\\slash' / "*literal"
    unusual.mkdir(parents=True)
    payload = json.dumps({"roots": {"photos": str(unusual)}})
    for text in [payload, "// header\r\n" + payload + " // eof", "/* header\n */" + payload.replace('"roots":', '"roots" /* key */ :')]:
        config.write_text(text)
        restart()
        assert paths.external_roots() == {"photos": str(unusual)}, f"case={text!r}"
        assert config.read_bytes() == text.encode()
    for text in [
        "{",
        "[]",
        '{"roots": []}',
        '{"roots": {},}',
        '{"roots": {}} /* unfinished',
        '{"roots": {"photos": "relative"}}',
        json.dumps({"roots": {"input": str(photos)}}),
        json.dumps({"roots": {"disk": str(tmp_path.anchor)}}),
        json.dumps({"roots": {"gone": str(tmp_path / "missing")}}),
        '{"roots": {"photos": "/one", /* duplicate */ "photos": "/two"}}',
        '{"roots": {}, "roots": {}}',
        '{"roots": {"broken": "unterminated // }}',
        '{"ro/**/ots": {}}',
        '{"roots": {"a": 1/* must not join tokens */2}}',
    ]:
        config.write_text(text)
        restart()
        assert paths.external_roots() == {}, f"case={text!r}"
        assert config.read_bytes() == text.encode()
        assert paths.image_roots("input", "output") == {"input": "input", "output": "output"}
    # An unreadable file is preserved and disables roots, as does a non-file destination.
    original_open = paths.os.open

    def refuse_read(target: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if str(target) == str(config) and flags & paths.os.O_ACCMODE == paths.os.O_RDONLY:
            raise PermissionError("configuration is unreadable")
        return original_open(target, flags, *args, **kwargs)

    contents = config.read_bytes()
    with monkeypatch.context() as access:
        access.setattr(paths.os, "open", refuse_read)
        restart()
    assert paths.external_roots() == {}
    assert config.read_bytes() == contents
    config.unlink()
    config.mkdir()
    restart()
    assert paths.external_roots() == {}
    assert config.is_dir()
    config.rmdir()
    config.write_text("{}")
    # A symlink, including a dangling one, is never read or replaced.
    config.unlink()
    outside = tmp_path / "outside.jsonc"
    outside.write_text(json.dumps({"roots": {"photos": str(photos)}}))
    sentinel = outside.read_bytes()
    for target in [outside, tmp_path / "missing.jsonc"]:
        config.symlink_to(target)
        restart()
        assert paths.external_roots() == {}
        assert config.is_symlink()
        config.unlink()
    assert outside.read_bytes() == sentinel
    assert not (tmp_path / "missing.jsonc").exists()
    directory.rmdir()
    directory.symlink_to(photos, target_is_directory=True)
    restart()
    assert paths.external_roots() == {}
    assert not (photos / config.name).exists()
    directory.unlink()
    # Simulate an unwritable directory independent of the test runner's UID.
    original_mkdir = Path.mkdir

    def refuse_config(self: Path, *args: Any, **kwargs: Any):
        if self == directory:
            raise PermissionError("read-only user directory")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_config)
    restart()
    assert paths.external_roots() == {}
    assert not directory.exists()
    assert any(record.levelname == "ERROR" for record in caplog.records)
