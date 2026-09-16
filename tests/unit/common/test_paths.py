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
    # Preference updates preserve comments, root text, unknown fields and the startup snapshot.
    original = '{\r\n  "roots": {}, // keep roots\r\n  "future": {"url": "https://example/a/*b"}\r\n} // eof'
    config.write_bytes(original.encode())
    paths.save_workbench_preferences(directory, {"codex": {"model": "first", "effort": "low"}})
    contents = config.read_bytes().decode()
    assert '"roots": {}, // keep roots\r\n' in contents
    assert '"future": {"url": "https://example/a/*b"}' in contents
    assert contents.endswith("} // eof")
    contents = contents.replace('"model": "first"', '"model": /* preserve */ "first"')
    config.write_bytes(contents.encode())
    paths.save_workbench_preferences(directory, {"codex": {"model": "second"}, "grok": {"model": "other"}})
    updated = paths.read_configuration(directory)
    assert updated["workbench"]["codex"] == {"model": "second", "effort": "low"}
    assert updated["workbench"]["grok"] == {"model": "other"}
    assert "/* preserve */" in config.read_text()
    assert paths.external_roots() == {}
    assert paths.parse_roots(config.read_text()) == {}
    paths.save_workbench_preferences(directory, {"codex": {}})
    assert paths.read_configuration(directory)["workbench"] == {"codex": {}, "grok": {"model": "other"}}
    # A failed atomic replacement leaves the original document and no temporary file.
    before_failure = config.read_bytes()

    def refuse_replace(*args: Any, **kwargs: Any):
        raise PermissionError("read-only destination")

    with monkeypatch.context() as access:
        access.setattr(paths.os, "replace", refuse_replace)
        with pytest.raises(PermissionError):
            paths.save_workbench_preferences(directory, {"grok": {"model": "failed"}})
    assert config.read_bytes() == before_failure
    assert not list(directory.glob("config-*.tmp"))
    config.write_text(json.dumps({"roots": {"photos": str(photos)}, "workbench": {"codex": {"model": "selected"}}}))
    restart()
    assert paths.external_roots() == {"photos": str(photos)}
    # Later preference writes do not reload changed root grants.
    config.write_text('{"roots": {}, "workbench": {}}')
    paths.save_workbench_preferences(directory, {"codex": {"model": "updated"}})
    assert paths.external_roots() == {"photos": str(photos)}
    for invalid in ['{"roots": {}, "workbench": []}', '{"roots": {}, "workbench": {"codex": 1}}', '{"roots": {}, "roots": {}}']:
        config.write_text(invalid)
        with pytest.raises(ValueError):
            paths.save_workbench_preferences(directory, {"codex": {"model": "refused"}})
        assert config.read_text() == invalid
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
        with pytest.raises((OSError, ValueError)):
            paths.save_workbench_preferences(directory, {"codex": {"model": "refused"}})
        config.unlink()
    assert outside.read_bytes() == sentinel
    assert not (tmp_path / "missing.jsonc").exists()
    # Startup leaves existing skills and symlink destinations alone, including dangling links.
    skills = directory / "skills"
    skills.rmdir()
    config.write_text(json.dumps({"roots": {"photos": str(photos)}}))
    for target in [photos, tmp_path / "missing-skills"]:
        skills.symlink_to(target, target_is_directory=True)
        restart()
        assert skills.is_symlink()
        assert paths.external_roots() == {"photos": str(photos)}
        skills.unlink()
    assert not (tmp_path / "missing-skills").exists()
    skills.write_text("existing file")
    restart()
    assert skills.read_text() == "existing file"
    assert paths.external_roots() == {"photos": str(photos)}
    skills.unlink()
    config.unlink()
    directory.rmdir()
    directory.symlink_to(photos, target_is_directory=True)
    restart()
    assert paths.external_roots() == {}
    with pytest.raises((OSError, ValueError)):
        paths.save_workbench_preferences(directory, {"codex": {"model": "refused"}})
    assert not (photos / config.name).exists()
    assert not (photos / "skills").exists()
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
