"""Tests for the CLI path-handling and output-directory helpers.

Covers:
- ``_normalize_path`` expands ~ and env vars regardless of host platform.
- ``_confirm_output_directory`` no-ops on missing or empty dirs.
- ``_confirm_output_directory`` wipes contents when ``force=True``.
- ``_confirm_output_directory`` rejects when the path is a file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import typer

from fm_saxml.cli import _normalize_path, _confirm_output_directory


# ---------------------------------------------------------------------------
# _normalize_path
# ---------------------------------------------------------------------------

def test_normalize_path_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows fallback
    p = _normalize_path(Path("~/example.xml"))
    assert str(p).startswith(str(tmp_path))
    assert p.name == "example.xml"


def test_normalize_path_expands_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("FM_TEST_DIR", str(tmp_path))
    if os.name == "nt":
        p = _normalize_path(Path("%FM_TEST_DIR%/foo.xml"))
    else:
        p = _normalize_path(Path("$FM_TEST_DIR/foo.xml"))
    assert str(p).startswith(str(tmp_path))
    assert p.name == "foo.xml"


def test_normalize_path_relative_becomes_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _normalize_path(Path("relative/dir"))
    assert p.is_absolute()


# ---------------------------------------------------------------------------
# _confirm_output_directory
# ---------------------------------------------------------------------------

def test_confirm_missing_dir_is_noop(tmp_path):
    target = tmp_path / "does_not_exist"
    # Should not raise and not create the directory
    _confirm_output_directory(target, force=False)
    assert not target.exists()


def test_confirm_empty_dir_is_noop(tmp_path):
    target = tmp_path / "empty"
    target.mkdir()
    _confirm_output_directory(target, force=False)
    # Still empty, still exists
    assert target.exists()
    assert not any(target.iterdir())


def test_confirm_force_wipes_contents(tmp_path):
    target = tmp_path / "non_empty"
    target.mkdir()
    (target / "old.txt").write_text("stale")
    (target / "subdir").mkdir()
    (target / "subdir" / "deeper.txt").write_text("nested")

    _confirm_output_directory(target, force=True)

    assert target.exists()
    assert not any(target.iterdir())


def test_confirm_rejects_file_path(tmp_path):
    target = tmp_path / "I am a file.txt"
    target.write_text("oops")
    with pytest.raises(typer.Exit):
        _confirm_output_directory(target, force=True)
