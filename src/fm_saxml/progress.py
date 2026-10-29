"""Progress reporting for ``build``: Rich bars in a terminal, plain lines or JSON lines through a pipe.

The pipeline calls one reporter the same way in every mode::

    with reporter.stage("analyze", len(files)):    # stage_start ... stage_done
        reporter.file_start(name)
        ...
        reporter.file_done(name)
    reporter.done()

``plain`` and ``json`` write straight to ``sys.stdout`` (not through Rich, which wraps long
lines and, with ``TERM=dumb``, holds output back), one line per event, flushed at once.
Rich-only extras (``group``/``step`` for the single-file 7-step bar) do nothing in the other
modes. ``unit_done`` (one page or file of a stage with ``units``) ticks the Rich bar, and in
the other modes becomes a ``stage_progress`` event, throttled.
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Iterator, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


class ProgressMode(str, Enum):
    rich = "rich"
    plain = "plain"
    json = "json"


# Stage ids are stable (the agentic-fm companion reads them); labels are for people.
STAGE_LABELS = {
    "read": "Reading",
    "scrub": "Scrubbing",
    "analyze": "Analyzing",
    "write_raw": "Writing raw XML",
    "write_pages": "Writing pages",
    "write_viewer": "Writing HTML viewer",
    "check": "Checking redactions",
}
# What a stage with ``units`` counts.
STAGE_UNITS = {"write_pages": "pages", "write_viewer": "pages", "check": "files"}
# The Rich bar's description once such a stage ends.
_RICH_DONE_LABELS = {"write_pages": "Wrote {} pages", "write_viewer": "Wrote {} viewer pages",
                     "check": "Checked {} files"}
# What the Rich bar says before its first file.
_RICH_STAGE_LABELS = {**STAGE_LABELS, "analyze": "Analyzing files"}


def default_mode() -> ProgressMode:
    """``rich`` when stdout is a terminal, ``plain`` otherwise (a pipe, a file, a test runner)."""
    try:
        return ProgressMode.rich if sys.stdout.isatty() else ProgressMode.plain
    except (AttributeError, ValueError):
        return ProgressMode.plain


def make_reporter(mode: Optional[ProgressMode], console: Console) -> "Reporter":
    mode = mode or default_mode()
    if mode == ProgressMode.json:
        return JsonReporter()
    if mode == ProgressMode.plain:
        return PlainReporter()
    return RichReporter(console)


def rich_progress(console: Console) -> Progress:
    """Spinner + bar + elapsed time. Rich degrades gracefully when output is piped."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


class Reporter:
    """The interface. ``label`` arguments are Rich bar descriptions; the other modes ignore them."""

    def stage_start(self, stage: str, total: int, *, label: Optional[str] = None,
                    units: Optional[int] = None) -> None:
        pass

    def file_start(self, name: str, *, label: Optional[str] = None) -> None:
        pass

    def file_done(self, name: str) -> None:
        pass

    def stage_done(self) -> None:
        pass

    def done(self) -> None:
        pass

    def abort(self) -> None:
        """A stage stopped on an error: put the terminal back, report nothing."""

    @contextmanager
    def stage(self, stage: str, total: int, *, label: Optional[str] = None,
              units: Optional[int] = None) -> Iterator[None]:
        """``stage_start`` ... ``stage_done``, or ``abort`` if the block raises."""
        self.stage_start(stage, total, label=label, units=units)
        try:
            yield
        except BaseException:
            self.abort()
            raise
        self.stage_done()

    @contextmanager
    def group(self, label: str, steps: int) -> Iterator[None]:
        """Rich: one bar of ``steps`` steps for everything inside (stage events don't draw)."""
        yield

    def step(self, label: str) -> None:
        """Rich: advance the ``group`` bar."""

    def unit_done(self) -> None:
        """One of the stage's ``units`` (a page, a file) is finished."""


class RichReporter(Reporter):
    """The Rich bars ``build`` has always drawn: one per stage, left on screen when it ends."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._progress: Optional[Progress] = None
        self._task = None
        self._grouped = False
        self._stage = ""
        self._units: Optional[int] = None
        self._written = 0

    def _open(self, label: str, total: int) -> None:
        self._progress = rich_progress(self.console)
        self._progress.start()
        self._task = self._progress.add_task(label, total=total)

    def _close(self) -> None:
        if self._progress is not None:
            self._progress.stop()
        self._progress = self._task = None

    def stage_start(self, stage, total, *, label=None, units=None):
        if self._grouped:
            return
        self._stage, self._units, self._written = stage, units, 0
        self._open(label or _RICH_STAGE_LABELS[stage], units if units is not None else total)

    def file_start(self, name, *, label=None):
        if not self._grouped and label is not None and self._progress is not None:
            self._progress.update(self._task, description=label)

    def file_done(self, name):
        if not self._grouped and self._units is None and self._progress is not None:
            self._progress.advance(self._task)

    def unit_done(self):
        if self._progress is not None and self._units is not None:
            self._written += 1
            self._progress.update(self._task, completed=self._written, total=max(self._units, self._written))

    def stage_done(self):
        if self._grouped:
            return
        if self._units is not None and self._progress is not None:
            done_label = _RICH_DONE_LABELS.get(self._stage, "Done: {}")
            self._progress.update(self._task, completed=self._written, total=self._written,
                                  description=done_label.format(self._written))
        self._units = None
        self._close()

    def abort(self):
        if not self._grouped:
            self._units = None
            self._close()

    @contextmanager
    def group(self, label, steps):
        self._open(label, steps)
        self._grouped = True
        try:
            yield
        finally:
            self._grouped = False
            self._close()

    def step(self, label):
        if self._progress is not None:
            self._progress.update(self._task, advance=1, description=label)


class _EventReporter(Reporter):
    """Turns the calls into events with N of M and timings; subclasses write them.

    ``stage_progress`` goes out at most once per ``interval`` seconds, and only from a
    ``unit_done``, so never when nothing changed. ``clock`` and ``interval`` are for tests.
    """

    interval = 1.0

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, interval: Optional[float] = None) -> None:
        self._clock = clock
        if interval is not None:
            self.interval = interval
        self._started = clock()
        self._stage: Optional[str] = None
        self._stage_started = 0.0
        self._total = 0
        self._index = 0
        self._file: Optional[str] = None
        self._file_started = 0.0
        self._units: Optional[int] = None
        self._done = 0
        self._reported_at = 0.0

    def _emit(self, event: str, *, file: Optional[str] = None, seconds: Optional[float] = None,
              **extra) -> None:
        obj = {
            "event": event,
            "stage": self._stage if event != "done" else None,
            "file": file,
            "index": self._index if event != "done" else 0,
            "total": self._total if event != "done" else 0,
            "elapsed": round(self._clock() - self._started, 1),
        }
        if seconds is not None:
            obj["seconds"] = round(seconds, 1)
        obj.update(extra)
        self.write(obj)

    def write(self, obj: dict) -> None:
        raise NotImplementedError

    @staticmethod
    def _line(text: str) -> None:
        # sys.stdout looked up each time: a test runner may have replaced it.
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    def stage_start(self, stage, total, *, label=None, units=None):
        self._stage, self._total, self._index, self._file = stage, total, 0, None
        self._units, self._done = units, 0
        self._stage_started = self._reported_at = self._clock()
        self._emit("stage_start")

    def file_start(self, name, *, label=None):
        self._index += 1
        self._file = name
        self._file_started = self._clock()
        self._emit("file_start", file=name)

    def file_done(self, name):
        self._emit("file_done", file=name, seconds=self._clock() - self._file_started)

    def unit_done(self):
        if self._units is None:
            return
        self._done += 1
        now = self._clock()
        if now - self._reported_at >= self.interval:
            self._reported_at = now
            self._emit("stage_progress", file=self._file, done=self._done, units=self._units,
                       unit=STAGE_UNITS.get(self._stage or "", "pages"))

    def stage_done(self):
        self._index = self._total
        extra = {}
        if self._units is not None:
            extra = {"done": self._done, "unit": STAGE_UNITS.get(self._stage or "", "pages")}
        self._emit("stage_done", seconds=self._clock() - self._stage_started, **extra)
        self._units = None

    def done(self):
        self._emit("done")


class JsonReporter(_EventReporter):
    """One JSON object per line: ``event``, ``stage``, ``file``, ``index``, ``total``, ``elapsed`` (+ ``seconds``,
    and ``done``/``units``/``unit`` for a stage that counts pages or files)."""

    def write(self, obj):
        self._line(json.dumps(obj))


class PlainReporter(_EventReporter):
    """One line per event, e.g. ``[3/12] Analyzing Invoices (4.2s)``; progress every 5 s at most."""

    interval = 5.0

    def write(self, obj):
        event = obj["event"]
        label = STAGE_LABELS.get(obj["stage"] or "", "")
        if event == "stage_start":
            text = f"{label}: {obj['total']} file(s)"
        elif event == "file_start":
            text = f"[{obj['index']}/{obj['total']}] {label} {obj['file']}..."
        elif event == "file_done":
            text = f"[{obj['index']}/{obj['total']}] {label} {obj['file']} ({obj['seconds']}s)"
        elif event == "stage_progress":
            seconds = round(self._clock() - self._stage_started, 1)
            text = f"{label}: {obj['done']}/{obj['units']} {obj['unit']} ({seconds}s)"
        elif event == "stage_done":
            text = f"{label} done ({obj['seconds']}s)"
        else:
            text = f"Done ({obj['elapsed']}s)"
        self._line(text)
