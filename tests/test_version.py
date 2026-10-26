"""Tests for the self-version detection module."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fm_saxml import __version__
from fm_saxml.version import (
    REPO_LABEL,
    REPO_URL,
    _find_git_root,
    _is_own_checkout,
    _format_iso_date,
    get_self_updated_at_display,
    get_self_version_info,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_repo_url():
    assert REPO_URL == "https://dev.azure.com/directimpact/SWAT/_git/fm-saxml-converter"


def test_repo_label():
    assert REPO_LABEL == "fm-saxml-converter"


# ---------------------------------------------------------------------------
# get_self_version_info
# ---------------------------------------------------------------------------

def test_version_info_always_returns_version():
    info = get_self_version_info()
    assert info["version"] == __version__


def test_version_info_has_all_keys():
    info = get_self_version_info()
    for key in (
        "version",
        "commit_hash",
        "commit_short",
        "commit_date_iso",
        "commit_date_display",
        "source",
    ):
        assert key in info, f"missing key {key}"


def test_version_info_source_is_known():
    info = get_self_version_info()
    assert info["source"] in ("git", "build", "package")


def test_version_info_when_in_repo_returns_git():
    """When the package is installed editable from a clone, we expect git source."""
    # The test suite itself runs from a git checkout, so this should be 'git'.
    # If it's not, we're probably running from an installed wheel — skip.
    info = get_self_version_info()
    if info["source"] == "package":
        pytest.skip("Not running from a git checkout")
    assert info["commit_hash"] is not None
    assert len(info["commit_hash"]) == 40  # full SHA-1
    assert info["commit_short"] == info["commit_hash"][:7]


# ---------------------------------------------------------------------------
# get_self_updated_at_display
# ---------------------------------------------------------------------------

def test_display_is_string():
    assert isinstance(get_self_updated_at_display(), str)


def test_display_format_when_git_available():
    info = get_self_version_info()
    if info["source"] == "package":
        pytest.skip("Not running from a git checkout")
    display = get_self_updated_at_display()
    # Either "<date> (commit <short>)" or "commit <short>"
    assert "commit" in display
    # 7-char short hash should appear somewhere
    assert info["commit_short"] in display


def test_display_format_fallback_to_version(monkeypatch):
    """Force the package fallback by hiding any git binary."""
    import fm_saxml.version as v

    monkeypatch.setattr(v, "_find_git_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(v, "_build_info", lambda: (None, None))
    display = v.get_self_updated_at_display()
    assert display == f"v{__version__}"


# ---------------------------------------------------------------------------
# Installed inside another project's git repo (e.g. a .venv in a harness)
# ---------------------------------------------------------------------------

def _host_repo(tmp_path):
    """A git repo of some other project, with this package in its .venv."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "some-harness"\n', encoding="utf-8")
    pkg = tmp_path / ".venv" / "Lib" / "site-packages" / "fm_saxml"
    pkg.mkdir(parents=True)
    return pkg


def test_is_own_checkout(tmp_path):
    assert not _is_own_checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "some-harness"\n', encoding="utf-8")
    assert not _is_own_checkout(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fm-saxml-converter"\n', encoding="utf-8")
    assert _is_own_checkout(tmp_path)


def test_host_repo_head_is_not_reported(tmp_path, monkeypatch):
    """The .git found above site-packages belongs to another project: ignore it."""
    import fm_saxml.version as v

    pkg = _host_repo(tmp_path)
    monkeypatch.setattr(v, "__file__", str(pkg / "version.py"))
    monkeypatch.setattr(v, "_git", lambda *_a, **_k: pytest.fail("asked the host repo's git"))
    monkeypatch.setattr(v, "_build_info", lambda: (None, None))
    info = v.get_self_version_info()
    assert info["source"] == "package"
    assert v.get_self_updated_at_display() == f"v{__version__}"


def test_build_info_used_outside_a_checkout(tmp_path, monkeypatch):
    import fm_saxml.version as v

    pkg = _host_repo(tmp_path)
    monkeypatch.setattr(v, "__file__", str(pkg / "version.py"))
    monkeypatch.setattr(v, "_build_info", lambda: ("8460954126dec1f8f31de2c646c156b755213e2f",
                                                   "2026-10-26T10:00:00-04:00"))
    info = v.get_self_version_info()
    assert info["source"] == "build"
    assert info["commit_short"] == "8460954"
    assert v.get_self_updated_at_display() == "2026-10-26 14:00 UTC (commit 8460954)"


# ---------------------------------------------------------------------------
# _find_git_root
# ---------------------------------------------------------------------------

def test_find_git_root_returns_none_for_orphan_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _find_git_root(nested) is None


def test_find_git_root_finds_local_dot_git(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "deep" / "tree"
    nested.mkdir(parents=True)
    assert _find_git_root(nested) == tmp_path


def test_find_git_root_handles_git_file_worktree(tmp_path):
    """Worktrees use a .git *file* pointing to the real .git directory."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/abc")
    assert _find_git_root(tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# _format_iso_date
# ---------------------------------------------------------------------------

def test_format_iso_date_none_returns_none():
    assert _format_iso_date(None) is None


def test_format_iso_date_empty_returns_none():
    assert _format_iso_date("") is None


def test_format_iso_date_converts_to_utc():
    out = _format_iso_date("2026-05-04T12:30:00+00:00")
    assert out == "2026-05-04 12:30 UTC"


def test_format_iso_date_normalizes_offset_to_utc():
    out = _format_iso_date("2026-05-04T07:30:00-05:00")
    assert out == "2026-05-04 12:30 UTC"


def test_format_iso_date_returns_input_for_unparseable():
    weird = "not-a-real-date"
    assert _format_iso_date(weird) == weird


# ---------------------------------------------------------------------------
# Smoke test against the real renderer wiring
# ---------------------------------------------------------------------------

def test_index_template_includes_creation_details(tmp_path):
    """End-to-end: render against the small sample fixture and inspect index.md."""
    from fm_saxml.parser.saxml_reader import parse_savexml
    from fm_saxml.normalize.normalize import normalize
    from fm_saxml.render.markdown.renderer import render_markdown

    fixture = Path(__file__).parent / "fixtures" / "v2_sample.xml"
    if not fixture.exists():
        pytest.skip("v2 sample fixture not available")

    raw = parse_savexml(fixture)
    model = normalize(raw, source_file=str(fixture), source_path=fixture)
    out_dir = tmp_path / "site"
    render_markdown(model, out_dir)

    index_text = (out_dir / "index.md").read_text(encoding="utf-8")
    assert "## Creation Details" in index_text
    assert f"[{REPO_LABEL}]({REPO_URL}) Updated At" in index_text
    # Old section name should be gone
    assert "## Timestamps" not in index_text
