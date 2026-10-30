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
# Per-file stages, then the ones that run once over the whole output (total 1, file = the solution).
FILE_STAGES = ["read", "scrub", "analyze", "write_raw", "write_pages"]
STAGES = FILE_STAGES + ["check"]
HTML_STAGES = FILE_STAGES + ["write_viewer", "check"]
UNIT_STAGES = {"write_pages": "pages", "write_viewer": "pages", "check": "files"}
FIELDS = {"event", "stage", "file", "index", "total", "elapsed"}
runner = CliRunner()

needs_batch = pytest.mark.skipif(not BATCH.exists(), reason="multi-file samples not present")


def _build(tmp_path: Path, src: Path, *extra: str):
    result = runner.invoke(app, ["build", str(src), "-o", str(tmp_path / "docs"), "-f", *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _secret_xml(tmp_path: Path) -> Path:
    """The small sample with a password in a calculation, so the guard has a value to look for."""
    xml = SINGLE.read_text(encoding="utf-8").replace(
        "<Calculation>Active</Calculation>",
        '<Calculation><![CDATA[Let ( $password = "Hunter2Secret!" ; "Active" )]]></Calculation>',
    )
    path = tmp_path / "Secrets.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _events(output: str) -> list[dict]:
    """Every line that is a JSON object with an "event" (the rest is ordinary output)."""
    events = []
    for line in output.splitlines():
        if line.startswith("{"):
            obj = json.loads(line)
            if isinstance(obj, dict) and "event" in obj:
                events.append(obj)
    return events


def _check_events(events: list[dict], files: list[str], stages: list[str] = STAGES,
                  solution: str = "") -> list[dict]:
    """Stages in order; in each, stage_start, then file_start/file_done for 1..M, then stage_done; done last.

    Returns the ``stage_progress`` events, which are left out of that order.
    """
    for e in events:
        assert FIELDS <= e.keys(), e
        assert isinstance(e["elapsed"], float)
        assert ("seconds" in e) == (e["event"] in ("file_done", "stage_done")), e
        unit = UNIT_STAGES.get(e["stage"])
        if e["event"] == "stage_progress":
            assert unit and e.keys() == FIELDS | {"done", "units", "unit"} and e["unit"] == unit, e
        elif e["event"] == "stage_done" and unit:
            assert e.keys() == FIELDS | {"seconds", "done", "unit"} and e["unit"] == unit, e
        else:
            assert "done" not in e and "unit" not in e, e
    assert [e["elapsed"] for e in events] == sorted(e["elapsed"] for e in events)

    assert events[-1] == {"event": "done", "stage": None, "file": None, "index": 0, "total": 0,
                          "elapsed": events[-1]["elapsed"]}
    ticks = [e for e in events if e["event"] == "stage_progress"]
    body = [e for e in events[:-1] if e["event"] != "stage_progress"]
    for stage in stages:
        names = files if stage in FILE_STAGES else [solution or files[0]]
        m = len(names)
        chunk, body = body[:2 + 2 * m], body[2 + 2 * m:]
        assert all(e["stage"] == stage for e in chunk), chunk
        assert all(e["total"] == m for e in chunk), chunk
        start, *pairs, end = chunk
        assert (start["event"], start["file"], start["index"]) == ("stage_start", None, 0)
        assert (end["event"], end["file"], end["index"]) == ("stage_done", None, m)
        for i, name in enumerate(names, 1):
            begin, finish = pairs[2 * i - 2], pairs[2 * i - 1]
            assert (begin["event"], begin["file"], begin["index"]) == ("file_start", name, i)
            assert (finish["event"], finish["file"], finish["index"]) == ("file_done", name, i)
    assert body == []
    return ticks


def _check_ticks(events: list[dict], ticks: list[dict], stage: str, file: str) -> None:
    """With no throttling, one stage_progress per unit, 1..N, ending at stage_done's count."""
    mine = [e for e in ticks if e["stage"] == stage]
    done = next(e for e in events if e["event"] == "stage_done" and e["stage"] == stage)
    assert [e["done"] for e in mine] == list(range(1, done["done"] + 1))
    assert all(e["file"] == file and e["index"] == 1 for e in mine), mine
    if stage != "write_pages":  # write_pages's units are an estimate
        assert all(e["units"] == done["done"] for e in mine), mine


def _no_rich_bars(output: str) -> None:
    # the summary table's heavy rules (┏━━┳ / ┡━━╇) use ━ too, wherever the console can draw them
    bars = [ln for ln in output.splitlines() if "━" in ln and not ln.lstrip().startswith(("┏", "┡"))]
    assert not bars and "100%" not in output and "Wrote " not in output


def test_json_single_file(tmp_path):
    output = _build(tmp_path, SINGLE, "--progress", "json")
    _check_events(_events(output), ["small_sample_v2"])
    _no_rich_bars(output)


@needs_batch
def test_json_batch(tmp_path):
    output = _build(tmp_path, BATCH, "--progress", "json")
    _check_events(_events(output), ["FileA", "FileB"], solution=BATCH.name)
    _no_rich_bars(output)


def test_no_check_without_scrubbing(tmp_path):
    events = _events(_build(tmp_path, SINGLE, "--progress", "json", "--disable-scrubbing"))
    _check_events(events, ["small_sample_v2"], stages=FILE_STAGES)


def test_json_single_file_viewer_and_check(tmp_path, monkeypatch):
    monkeypatch.setattr(progress_mod.JsonReporter, "interval", 0)  # every unit reported
    output = _build(tmp_path, _secret_xml(tmp_path), "--progress", "json", "--html")
    events = _events(output)
    ticks = _check_events(events, ["Secrets"], stages=HTML_STAGES)
    for stage in ("write_pages", "write_viewer", "check"):
        _check_ticks(events, ticks, stage, "Secrets")
    checked = next(e for e in events if e["event"] == "stage_done" and e["stage"] == "check")
    viewer = next(e for e in events if e["event"] == "stage_done" and e["stage"] == "write_viewer")
    assert checked["done"] > viewer["done"] > 0  # the guard also scans the viewer's scripts and the JSON
    _no_rich_bars(output)


@needs_batch
def test_json_batch_viewer(tmp_path, monkeypatch):
    monkeypatch.setattr(progress_mod.JsonReporter, "interval", 0)
    events = _events(_build(tmp_path, BATCH, "--progress", "json", "--html"))
    ticks = _check_events(events, ["FileA", "FileB"], stages=HTML_STAGES, solution=BATCH.name)
    _check_ticks(events, ticks, "write_viewer", BATCH.name)
    pages = [e for e in ticks if e["stage"] == "write_pages"]
    assert {e["file"] for e in pages} == {"FileA", "FileB"}
    assert [e["done"] for e in pages] == list(range(1, len(pages) + 1))  # counted across the stage


def test_stage_progress_is_throttled(capsys):
    now = [0.0]
    reporter = progress_mod.JsonReporter(clock=lambda: now[0])
    reporter.stage_start("write_viewer", 1, units=10)
    reporter.file_start("Sol")
    for t in (0.2, 0.5, 1.0, 1.4, 1.9, 2.0, 2.1, 5.0):
        now[0] = t
        reporter.unit_done()
    now[0] = 9.0  # time passes, nothing written: no event
    reporter.file_done("Sol")
    reporter.stage_done()
    reporter.stage_start("analyze", 1)
    reporter.unit_done()  # a stage without units never reports progress
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    ticks = [e for e in events if e["event"] == "stage_progress"]
    assert [(e["elapsed"], e["done"]) for e in ticks] == [(1.0, 3), (2.0, 6), (5.0, 8)]
    assert ticks[0] == {"event": "stage_progress", "stage": "write_viewer", "file": "Sol", "index": 1, "total": 1,
                        "elapsed": 1.0, "done": 3, "units": 10, "unit": "pages"}
    done = next(e for e in events if e["event"] == "stage_done")
    assert (done["done"], done["unit"], done["seconds"]) == (8, "pages", 9.0)


def test_plain_progress_lines(capsys):
    now = [0.0]
    reporter = progress_mod.PlainReporter(clock=lambda: now[0])
    now[0] = 10.0
    reporter.stage_start("check", 1, units=300)
    reporter.file_start("Sol")
    for i in range(300):
        now[0] = 10.0 + i / 10  # one file every 0.1 s: a line every 5 s
        reporter.unit_done()
    reporter.file_done("Sol")
    reporter.stage_done()
    lines = capsys.readouterr().out.splitlines()
    assert [ln for ln in lines if "/300" in ln] == [
        "Checking redactions: 51/300 files (5.0s)",
        "Checking redactions: 101/300 files (10.0s)",
        "Checking redactions: 151/300 files (15.0s)",
        "Checking redactions: 201/300 files (20.0s)",
        "Checking redactions: 251/300 files (25.0s)",
    ]
    assert lines[0] == "Checking redactions: 1 file(s)"
    assert lines[-1] == "Checking redactions done (29.9s)"


def test_plain_single_file(tmp_path):
    output = _build(tmp_path, SINGLE, "--progress", "plain")
    lines = output.splitlines()
    assert "Reading: 1 file(s)" in lines
    assert any(re.fullmatch(r"\[1/1\] Analyzing small_sample_v2 \(\d+\.\ds\)", ln) for ln in lines)
    assert any(re.fullmatch(r"Writing pages done \(\d+\.\ds\)", ln) for ln in lines)
    assert any(re.fullmatch(r"Checking redactions done \(\d+\.\ds\)", ln) for ln in lines)
    assert re.fullmatch(r"Done \(\d+\.\ds\)", lines[-1])
    assert not _events(output)
    _no_rich_bars(output)


@needs_batch
def test_plain_batch(tmp_path):
    output = _build(tmp_path, BATCH, "--progress", "plain", "--html")
    lines = output.splitlines()
    progress_lines = [ln for ln in lines if re.match(r"(\[\d+/\d+\] |\w[\w ]*: \d+ file\(s\)$|\w[\w ]* done \()", ln)]
    expected = []
    for label in ("Reading", "Scrubbing", "Analyzing", "Writing raw XML", "Writing pages",
                  "Writing HTML viewer", "Checking redactions"):
        names = ["FileA", "FileB"] if label not in ("Writing HTML viewer", "Checking redactions") else [BATCH.name]
        expected.append(f"{label}: {len(names)} file(s)")
        for i, name in enumerate(names, 1):
            expected += [f"[{i}/{len(names)}] {label} {name}...", f"[{i}/{len(names)}] {label} {name} (s)"]
        expected.append(f"{label} done (s)")
    assert [re.sub(r"\(\d+\.\ds\)", "(s)", ln) for ln in progress_lines] == expected
    assert re.fullmatch(r"Done \(\d+\.\ds\)", lines[-1])
    _no_rich_bars(output)


def test_default_is_plain_when_not_a_terminal(tmp_path):
    output = _build(tmp_path, SINGLE)  # CliRunner's stdout is not a terminal
    assert "Reading: 1 file(s)" in output.splitlines()
    _no_rich_bars(output)


def test_rich_draws_the_bars(tmp_path):
    output = _build(tmp_path, _secret_xml(tmp_path), "--progress", "rich", "--html")
    assert "Wrote " in output and "100%" in output
    assert re.search(r"Wrote \d+ viewer pages", output) and re.search(r"Checked \d+ files", output)
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
