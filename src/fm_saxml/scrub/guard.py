"""Output guard: prove no redacted value made it into a written file.

The engine knows exactly which values it replaced, so after rendering every
output file is searched for them (raw, JSON-escaped, HTML-escaped, and as the HTML viewer
embeds JSON in its .js files). A hit means some code path copied a string the walker
never saw, and the run fails.
"""

from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# .js: the --html viewer copies every page, and --webmcp the model data, into scripts under _viewer/.
_TEXT_SUFFIXES = {".md", ".json", ".txt", ".html", ".js", ".csv", ".xml", ".yaml", ".yml"}


@dataclass(frozen=True)
class Leak:
    path: Path
    line: int
    placeholder: str


def _script_escaped(text: str) -> str:
    """JSON as the HTML viewer embeds it in a script (render/html/viewer.py ``_js_literal``)."""
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _variants(value: str) -> set[str]:
    as_json = json.dumps(value, ensure_ascii=False)[1:-1]
    ascii_json = json.dumps(value)[1:-1]
    return {value, as_json, ascii_json, html.escape(value, quote=True),
            _script_escaped(as_json), _script_escaped(ascii_json)}


def _pattern(values: dict[str, str]) -> tuple[re.Pattern, dict[str, str]]:
    lookup: dict[str, str] = {}
    for value, ph in values.items():
        for v in _variants(value):
            if v:
                lookup.setdefault(v, ph)
    alt = "|".join(re.escape(v) for v in sorted(lookup, key=len, reverse=True))
    return re.compile(f"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])"), lookup


def _read(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def find_leaks_in_text(path: Path, text: str, values: dict[str, str], limit: int = 50) -> list[Leak]:
    if not values:
        return []
    pattern, lookup = _pattern(values)
    leaks = []
    for m in pattern.finditer(text):
        leaks.append(Leak(path, text.count("\n", 0, m.start()) + 1, lookup[m.group()]))
        if len(leaks) >= limit:
            break
    return leaks


def _read_or_none(path: Path) -> str | None:
    try:
        return _read(path)
    except OSError:
        return None


# Files are read a chunk at a time on a few threads: opening a file that was just
# written is slow where antivirus scans it on first read (seconds per thousand files
# on Windows), and those waits overlap. Matching stays in order, in this thread.
_READ_THREADS = 8
_READ_CHUNK = 256


def find_leaks(paths: Iterable[Path], values: dict[str, str], limit: int = 50) -> list[Leak]:
    """Every occurrence of a guarded value in ``paths``. ``values`` maps value -> placeholder."""
    if not values:
        return []
    pattern, lookup = _pattern(values)
    leaks: list[Leak] = []
    paths = list(paths)
    with ThreadPoolExecutor(max_workers=_READ_THREADS) as pool:
        for start in range(0, len(paths), _READ_CHUNK):
            chunk = paths[start:start + _READ_CHUNK]
            for path, text in zip(chunk, pool.map(_read_or_none, chunk)):
                if text is None:
                    continue
                for m in pattern.finditer(text):
                    leaks.append(Leak(path, text.count("\n", 0, m.start()) + 1, lookup[m.group()]))
                    if len(leaks) >= limit:
                        return leaks
    return leaks


def guard_output(target: Path, values: dict[str, str]) -> list[Leak]:
    """Scan one written file, or every text file under a written directory."""
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = [p for p in sorted(target.rglob("*")) if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES]
    else:
        files = []
    return find_leaks(files, values)
