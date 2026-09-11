"""Startup configuration and its fail-closed filesystem boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.arisu_nodes.common import paths


def test_external_roots_are_local_validated_and_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    config = tmp_path / "arisu_paths.json"
    photos = tmp_path / "photos"
    photos.mkdir()
    monkeypatch.setattr(paths, "CONFIG_PATH", config)
    paths.external_roots.cache_clear()
    try:
        assert paths.image_roots("input", "output") == {"input": "input", "output": "output"}
        config.write_text(json.dumps({"roots": {"photos": str(photos)}}))
        # Runtime edits do not silently expand authorization.
        assert "photos" not in paths.external_roots()
        paths.external_roots.cache_clear()
        assert paths.select_root(paths.external_roots(), "photos") == str(photos)
        with pytest.raises(ValueError):
            paths.select_root(paths.external_roots(), "unknown")
        for text in [
            "{",
            "[]",
            '{"roots": []}',
            '{"roots": {"photos": "relative"}}',
            json.dumps({"roots": {"input": str(photos)}}),
            json.dumps({"roots": {"disk": str(tmp_path.anchor)}}),
            json.dumps({"roots": {"gone": str(tmp_path / "missing")}}),
            '{"roots": {"photos": "/one", "photos": "/two"}}',
        ]:
            config.write_text(text)
            paths.external_roots.cache_clear()
            assert paths.external_roots() == {}, f"case={text!r}"
            assert paths.image_roots("input", "output") == {"input": "input", "output": "output"}
        assert any(record.levelname == "ERROR" for record in caplog.records)
    finally:
        paths.external_roots.cache_clear()
