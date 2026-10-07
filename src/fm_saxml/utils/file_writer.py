"""Safe file writing utilities."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

_write_hook: Callable[[Path], None] | None = None


@contextmanager
def on_write(callback: Callable[[Path], None]) -> Iterator[None]:
    """Call ``callback(path)`` after every file written inside the ``with`` block.

    Lets the CLI show page-by-page progress without threading a callback
    through every renderer function.
    """
    global _write_hook
    previous, _write_hook = _write_hook, callback
    try:
        yield
    finally:
        _write_hook = previous


def write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps output byte-identical across Windows/macOS/Linux
    with path.open("w", encoding=encoding, newline="\n") as fh:
        fh.write(content)
    if _write_hook:
        _write_hook(path)


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if _write_hook:
        _write_hook(path)
