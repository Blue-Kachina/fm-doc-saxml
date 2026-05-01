"""Extract base tables from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path


def extract_tables(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw table dicts from the DatabaseElement."""
    catalog = find_child(database_elem, "TableCatalog", "BaseTableCatalog")
    if catalog is None:
        return []

    tables = []
    for base_table in find_all_descendants(catalog, "BaseTable"):
        tables.append(_parse_table(base_table))
    return tables


def _parse_table(elem: etree._Element) -> dict[str, Any]:
    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "source_xml_path": xml_path(elem),
    }
