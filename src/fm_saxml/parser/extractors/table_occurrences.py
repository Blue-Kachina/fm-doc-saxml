"""Extract table occurrences from the FileMaker relationship graph."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path


def extract_table_occurrences(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw table occurrence dicts."""
    # v2: <TableOccurrenceCatalog> is a direct child of the container
    # v1: it lives under <RelationshipGraph>
    catalog = find_child(database_elem, "TableOccurrenceCatalog")
    if catalog is None:
        graph = find_child(database_elem, "RelationshipGraph")
        if graph is not None:
            catalog = find_child(graph, "TableOccurrenceCatalog")
    if catalog is None:
        return []

    results = []
    for to_elem in find_all_descendants(catalog, "TableOccurrence"):
        base_table_id = _get_base_table_id(to_elem)
        results.append({
            "id": attr(to_elem, "id", "ID"),
            "name": attr(to_elem, "name", "Name"),
            "uuid": attr(to_elem, "uuid", "UUID") or None,
            "base_table_id": base_table_id,
            "source_xml_path": xml_path(to_elem),
        })
    return results


def _get_base_table_id(to_elem: etree._Element) -> str:
    # v1: baseTableID is a direct attribute
    direct = attr(to_elem, "baseTableID", "baseTableId", "tableID")
    if direct:
        return direct
    # v2: <BaseTableSourceReference><BaseTableReference id="...">
    src_ref = find_child(to_elem, "BaseTableSourceReference")
    if src_ref is not None:
        bt_ref = find_child(src_ref, "BaseTableReference")
        if bt_ref is not None:
            return attr(bt_ref, "id", "ID")
    return ""
