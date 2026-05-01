"""Extract table occurrences from the FileMaker relationship graph."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path


def extract_table_occurrences(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw table occurrence dicts."""
    graph = find_child(database_elem, "RelationshipGraph")
    if graph is None:
        return []
    catalog = find_child(graph, "TableOccurrenceCatalog")
    if catalog is None:
        return []

    results = []
    for to_elem in find_all_descendants(catalog, "TableOccurrence"):
        results.append({
            "id": attr(to_elem, "id", "ID"),
            "name": attr(to_elem, "name", "Name"),
            "uuid": attr(to_elem, "uuid", "UUID") or None,
            "base_table_id": attr(to_elem, "baseTableID", "baseTableId", "tableID") or "",
            "source_xml_path": xml_path(to_elem),
        })
    return results
