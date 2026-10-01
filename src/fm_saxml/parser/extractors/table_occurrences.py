"""Extract table occurrences from the FileMaker relationship graph."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path, modification_info


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
            **_external_details(to_elem),
            "modified": modification_info(to_elem),
            "source_xml_path": xml_path(to_elem),
        })
    return results


def _external_details(to_elem: etree._Element) -> dict[str, str | None]:
    """Details of a ``type="External"`` TO: which data source and which base table in it.

    The base table of such a TO lives in another file, so its base table
    id must never be looked up among this file's tables. Everything is kept so
    a later multi-file run can resolve it against the sister file.
    """
    if attr(to_elem, "type", "Type").lower() != "external":
        return {"external_data_source": None}
    src_ref = find_child(to_elem, "BaseTableSourceReference")
    ds = find_child(src_ref, "DataSourceReference") if src_ref is not None else None
    bt = find_child(src_ref, "BaseTableReference") if src_ref is not None else None
    return {
        "external_data_source": (attr(ds, "name", "Name") if ds is not None else "") or "(external file)",
        "external_data_source_id": (attr(ds, "id", "ID") or None) if ds is not None else None,
        "external_data_source_uuid": (attr(ds, "uuid", "UUID") or None) if ds is not None else None,
        "external_base_table": (attr(bt, "name", "Name") or None) if bt is not None else None,
        "external_base_table_id": (attr(bt, "id", "ID") or None) if bt is not None else None,
        "external_base_table_uuid": (attr(bt, "uuid", "UUID") or None) if bt is not None else None,
    }


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
