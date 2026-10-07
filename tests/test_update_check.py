"""Update notifier: must be quiet, cached, and never raise."""

import json
import sys

import pytest
from typer.testing import CliRunner

from fm_saxml import __version__
from fm_saxml.cli import app
from fm_saxml.utils import update_check as uc


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.2.0", "0.1.0", True),
        ("0.10.0", "0.9.0", True),  # numeric, not string, comparison
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("1.0.0rc1", "0.9.0", False),  # pre-releases are ignored
        ("garbage", "0.1.0", False),
    ],
)
def test_is_newer(latest, current, expected):
    assert uc.is_newer(latest, current) is expected


def test_fetches_and_caches(tmp_path):
    cache = tmp_path / "c.json"
    calls = []

    def fetch():
        calls.append(1)
        return "0.3.0"

    assert uc.latest_version(fetch=fetch, cache=cache, now=lambda: 1000.0) == "0.3.0"
    # Within 24h: served from cache, no second fetch
    assert uc.latest_version(fetch=fetch, cache=cache, now=lambda: 1000.0 + 3600) == "0.3.0"
    assert len(calls) == 1
    # After 24h: fetch again
    assert uc.latest_version(fetch=fetch, cache=cache, now=lambda: 1000.0 + 90000) == "0.3.0"
    assert len(calls) == 2


def test_network_failure_returns_none_and_is_cached(tmp_path):
    cache = tmp_path / "c.json"
    calls = []

    def fetch():
        calls.append(1)
        raise OSError("offline")

    assert uc.latest_version(fetch=fetch, cache=cache, now=lambda: 1.0) is None
    assert uc.latest_version(fetch=fetch, cache=cache, now=lambda: 2.0) is None
    assert len(calls) == 1  # offline machines don't retry every run


def test_corrupt_cache_is_ignored(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text("{not json", encoding="utf-8")
    assert uc.latest_version(fetch=lambda: "0.4.0", cache=cache, now=lambda: 5.0) == "0.4.0"
    assert json.loads(cache.read_text(encoding="utf-8"))["latest"] == "0.4.0"


def test_unwritable_cache_does_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    # parent "directory" is actually a file, so mkdir/write must fail quietly
    assert uc.latest_version(fetch=lambda: "0.5.0", cache=blocker / "c.json") == "0.5.0"


@pytest.mark.parametrize("var", ["FM_SAXML_NO_UPDATE_CHECK", "CI"])
def test_disabled_by_environment(monkeypatch, var):
    monkeypatch.setenv(var, "1")
    assert uc.is_disabled()
    assert uc.start("0.1.0", "https://example.invalid") is None


def test_disabled_when_not_a_terminal(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("FM_SAXML_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False, raising=False)
    assert uc.is_disabled()


def test_notifier_message_only_when_newer(tmp_path):
    newer = uc.UpdateNotifier("0.1.0", "https://x", fetch=lambda: "0.2.0", cache=tmp_path / "a.json")
    msg = newer.message(timeout=5)
    assert msg and "0.2.0" in msg and "0.1.0" in msg

    same = uc.UpdateNotifier("0.2.0", "https://x", fetch=lambda: "0.2.0", cache=tmp_path / "b.json")
    assert same.message(timeout=5) is None


def test_notifier_never_waits_long_for_a_slow_check(tmp_path):
    import threading
    import time

    gate = threading.Event()

    def slow():
        gate.wait(5)
        return "9.9.9"

    n = uc.UpdateNotifier("0.1.0", "https://x", fetch=slow, cache=tmp_path / "s.json")
    start = time.monotonic()
    assert n.message(timeout=0.1) is None
    assert time.monotonic() - start < 1
    gate.set()


def test_upgrade_hint_for_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "releases" in uc.upgrade_hint("https://github.com/o/r")


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("C:\\Users\\me\\pipx\\venvs\\fm-saxml-converter", "pipx upgrade"),
        ("/home/me/.local/share/uv/tools/fm-saxml-converter", "uv tool upgrade"),
        ("/usr/lib/python3", "pip install -U"),
    ],
)
def test_upgrade_hint_by_install_method(monkeypatch, prefix, expected):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "prefix", prefix)
    assert expected in uc.upgrade_hint("https://x")


def test_version_flag():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"fm-saxml {__version__}"


def test_help_still_lists_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "build" in result.output and "doctor" in result.output
