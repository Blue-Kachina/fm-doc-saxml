"""Name normalization utilities."""

from __future__ import annotations

import hashlib
import re


def normalize_name(name: str) -> str:
    """Return a display name with no leading/trailing whitespace."""
    return name.strip()


def qualified_name(table: str, field: str) -> str:
    return f"{table}::{field}"


_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Keeps full output paths comfortably under Windows' 260-character limit.
MAX_SLUG_LENGTH = 80


def safe_slug(name: str) -> str:
    """Convert a name to a safe filesystem slug, preserving case.

    Handles characters that are invalid on Windows/macOS/Linux, Windows
    reserved device names (CON, NUL, ...), and overlong names (truncated with
    a short hash so distinct names stay distinct).
    """
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    slug = slug.strip(". ")
    if not slug:
        return "_"
    if slug.split(".")[0].upper() in _RESERVED_NAMES:
        slug = f"_{slug}"
    if len(slug) > MAX_SLUG_LENGTH:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[: MAX_SLUG_LENGTH - 9].rstrip('. ')}-{digest}"
    return slug


def folder_parts(path: str) -> list[str]:
    """Split a folder path like 'Accounting/Transactions' into parts."""
    if not path:
        return []
    return [p.strip() for p in path.replace("\\", "/").split("/") if p.strip()]
