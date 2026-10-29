"""``build --progress rich|plain|json``: progress that survives a pipe."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml import progress as progress_mod
from fm_saxml.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
SINGLE = FIXTURES / "small_sample_v2.xml"
BATCH = Path(__file__).parent.parent / "samples" / "multi_file_export" / "SaXML_no_separate_catalogue"
STAGES = ["read", "scrub", "analyze", "write_raw", "write_pages"]
FIELDS = {"event", "stage", "file", "index", "total", "elapsed"}
runner = CliRunner()

needs_batch = pytest.mark.skipif(not BATCH.exists(), reason="multi-file samples not present")


def _build(tmp_path: Path, src: Path, *extra: str):
    result = runner.invoke(app, ["build", str(src), "-o", str(tmp_path / "docs"), "-f", *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _events(output: str) -> list[dict]:
    """Every line that is a JSON object with an "event" (the rest is ordinary output)."""
    events = []
    for line in output.splitlines():
        if line.startswith("{"):
            obj = json.loads(line)
            if isinstance(obj, dict) and "event" in obj:
                events.append(obj)
    return events


def _check_events(events: list[dict], files: list[str]) -> None:
    """Stages in order; in each, stage_start, then file_start/file_done for 1..M, then stage_done; done last."""
    for e in events:
        assert FIELDS <= e.keys(), e
        assert isinstance(e["elapsed"], float)
        assert ("seconds" in e) == (e["event"] in ("file_done", "stage_done")), e
    assert [e["elapsed"] for e in events] == sorted(e["elapsed"] for e in events)

    assert events[-1] == {"event": "done", "stage": None, "file": None, "index": 0, "total": 0,
                          "elapsed": events[-1]["elapsed"]}
    body = events[:-1]
    m = len(files)
    per_stage = 2 + 2 * m
    assert len(body) == len(STAGES) * per_stage
    for n, stage in enumerate(STAGES):
        chunk = body[n * per_stage:(n + 1) * per_stage]
        assert all(e["stage"] == stage for e in chunk), chunk
        assert all(e["total"] == m for e in chunk), chunk
        start, *pairs, end = chunk
        assert (start["event"], start["file"], start["index"]) == ("stage_start", None, 0)
        assert (end["event"], end["file"], end["index"]) == ("stage_done", None, m)
        for i, name in enumerate(files, 1):
            begin, finish = pairs[2 * i - 2], pairs[2 * i - 1]
            assert (begin["event"], begin["file"], begin["index"]) == ("file_start", name, i)
            assert (finish["event"], finish["file"], finish["index"]) == ("file_done", name, i)


def _no_rich_bars(output: str) -> None:
    assert "━" not in output and "100%" not in output and "Wrote " not in output


def test_json_single_file(tmp_path):
    output = _build(tmp_path, SINGLE, "--progress", "json")
    _check_events(_events(output), ["small_sample_v2"])
    _no_rich_bars(output)


@needs_batch
def test_json_batch(tmp_path):
    output = _build(tmp_path, BATCH, "--progress", "json")
    _check_events(_events(output), ["FileA", "FileB"])
    _no_rich_bars(output)


def test_plain_single_file(tmp_path):
    output = _build(tmp_path, SINGLE, "--progress", "plain")
    lines = output.splitlines()
    assert "Reading: 1 file(s)" in lines
    assert any(re.fullmatch(r"\[1/1\] Analyzing small_sample_v2 \(\d+\.\ds\)", ln) for ln in lines)
    assert any(re.fullmatch(r"Writing pages done \(\d+\.\ds\)", ln) for ln in lines)
    assert re.fullmatch(r"Done \(\d+\.\ds\)", lines[-1])
    assert not _events(output)
    _no_rich_bars(output)


@needs_batch
def test_plain_batch(tmp_path):
    output = _build(tmp_path, BATCH, "--progress", "plain")
    lines = output.splitlines()
    progress_lines = [ln for ln in lines if re.match(r"(\[\d+/\d+\] |\w[\w ]*: \d+ file\(s\)$|\w[\w ]* done \()", ln)]
    expected = []
    for label in ("Reading", "Scrubbing", "Analyzing", "Writing raw XML", "Writing pages"):
        expected.append(f"{label}: 2 file(s)")
        for i, name in enumerate(["FileA", "FileB"], 1):
            expected += [f"[{i}/2] {label} {name}...", f"[{i}/2] {label} {name} (s)"]
        expected.append(f"{label} done (s)")
    assert [re.sub(r"\(\d+\.\ds\)", "(s)", ln) for ln in progress_lines] == expected
    assert re.fullmatch(r"Done \(\d+\.\ds\)", lines[-1])
    _no_rich_bars(output)


def test_default_is_plain_when_not_a_terminal(tmp_path):
    output = _build(tmp_path, SINGLE)  # CliRunner's stdout is not a terminal
    assert "Reading: 1 file(s)" in output.splitlines()
    _no_rich_bars(output)


def test_rich_draws_the_bars(tmp_path):
    output = _build(tmp_path, SINGLE, "--progress", "rich")
    assert "Wrote " in output and "100%" in output
    assert "Reading: 1 file(s)" not in output and not _events(output)


def test_default_mode_follows_the_terminal(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdout", Tty())
    assert progress_mod.default_mode() is progress_mod.ProgressMode.rich
    monkeypatch.setattr("sys.stdout", io.StringIO())
    assert progress_mod.default_mode() is progress_mod.ProgressMode.plain


def test_render_keeps_its_rich_bar(tmp_path):
    # Other commands share the helpers but have no --progress: they still draw Rich bars.
    model = tmp_path / "model.json"
    assert runner.invoke(app, ["parse", str(SINGLE), "-o", str(model)]).exit_code == 0
    result = runner.invoke(app, ["render", "markdown", "-m", str(model), "-o", str(tmp_path / "docs"), "-f"])
    assert result.exit_code == 0, result.output
    assert "Wrote " in result.output and not _events(result.output)
    assert "Writing pages: " not in result.output
