"""Resolve ``Table::Field`` references to field docIds.

In FileMaker XML the "table" half of a field reference is almost always a
*table occurrence* name, which need not match the base table's name. This
module is the single place that translates such references to the real field
entity, so every reference source (layouts, scripts, value lists, calcs, ...)
links consistently.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..model.document_model import DocumentModel
from .ids import field_doc_id


def _table_name(table_doc_id: str) -> str:
    return table_doc_id.split(":", 1)[1] if ":" in table_doc_id else table_doc_id


def build_field_resolver(model: DocumentModel) -> Callable[[str, str], Optional[str]]:
    """Return ``resolve(table_or_to_name, field_name) -> docId | None``.

    Resolution order (FileMaker names are case-insensitive, so each step falls
    back to a case-insensitive match):
      1. the name is a table occurrence -> use its base table
      2. the name is a base table name
    Returns None when no real field entity matches.
    """
    exact: dict[tuple[str, str], str] = {}
    folded: dict[tuple[str, str], str] = {}
    for f in model.entities.fields.values():
        tbl = _table_name(f.base_table_doc_id)
        exact[(tbl, f.name)] = f.doc_id
        folded.setdefault((tbl.casefold(), f.name.casefold()), f.doc_id)

    to_base_exact: dict[str, str] = {}
    to_base_folded: dict[str, str] = {}
    for to in model.entities.table_occurrences.values():
        if not to.base_table_doc_id:
            continue
        base = _table_name(to.base_table_doc_id)
        to_base_exact[to.name] = base
        to_base_folded.setdefault(to.name.casefold(), base)

    def resolve(table_name: str, field_name: str) -> Optional[str]:
        if not table_name or not field_name:
            return None
        table_name = table_name.strip()
        field_name = field_name.strip()

        base = to_base_exact.get(table_name)
        if base is not None:
            hit = exact.get((base, field_name))
            if hit:
                return hit
        hit = exact.get((table_name, field_name))
        if hit:
            return hit

        base = to_base_folded.get(table_name.casefold())
        if base is not None:
            hit = folded.get((base.casefold(), field_name.casefold()))
            if hit:
                return hit
        return folded.get((table_name.casefold(), field_name.casefold()))

    return resolve


def resolve_field_or_fallback(
    resolve: Callable[[str, str], Optional[str]], table_name: str, field_name: str
) -> Optional[str]:
    """Resolve, else fabricate a docId from the raw names (kept so unresolved
    references remain visible rather than silently vanishing)."""
    if not field_name:
        return None
    hit = resolve(table_name, field_name)
    if hit:
        return hit
    return field_doc_id(table_name, field_name) if table_name else None
