"""Name normalization utilities."""

from __future__ import annotations

import re


def normalize_name(name: str) -> str:
    """Return a display name with no leading/trailing whitespace."""
    return name.strip()


def qualified_name(table: str, field: str) -> str:
    return f"{table}::{field}"


def safe_slug(name: str) -> str:
    """Convert a name to a safe filesystem slug, preserving case."""
    # Replace characters that are unsafe on common filesystems
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    slug = slug.strip(". ")
    return slug or "_"


def folder_parts(path: str) -> list[str]:
    """Split a folder path like 'Accounting/Transactions' into parts."""
    if not path:
        return []
    return [p.strip() for p in path.replace("\\", "/").split("/") if p.strip()]
