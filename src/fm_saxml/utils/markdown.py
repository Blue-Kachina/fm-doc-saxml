"""Markdown formatting helpers."""

from __future__ import annotations

import re


def escape(text: str) -> str:
    """Escape Markdown special characters in inline text."""
    # Characters that need escaping in Markdown tables and inline text
    return re.sub(r'([\\`*_{}[\]()#+\-.!|])', r'\\\1', text)


def md_link(label: str, href: str) -> str:
    """Return a Markdown inline link."""
    return f"[{label}]({href})"


def code_span(text: str) -> str:
    return f"`{text}`"


def table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def table_header(columns: list[str], alignments: list[str] | None = None) -> str:
    header = table_row(columns)
    if alignments is None:
        alignments = ["---"] * len(columns)
    sep = table_row(alignments)
    return header + "\n" + sep
