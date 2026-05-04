"""Safe file writing utilities."""

from __future__ import annotations

from pathlib import Path


def write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
