"""Extract layouts from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path


def extract_layouts(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw layout dicts."""
    catalog = find_child(database_elem, "LayoutCatalog")
    if catalog is None:
        return []

    results = []
    for layout_elem in find_all_descendants(catalog, "Layout"):
        results.append(_parse_layout(layout_elem))
    return results


def _parse_layout(elem: etree._Element) -> dict[str, Any]:
    # Collect fields referenced on the layout via field objects
    referenced_fields = _collect_referenced_fields(elem)

    # v1: tableOccurrenceID is a direct attribute
    # v2: <TableOccurrenceReference id="..." name="..."> child element
    to_id = attr(elem, "tableOccurrenceID", "tableOccurrenceId", "tableID")
    to_name = attr(elem, "tableOccurrenceName", "tableName")
    if not to_id:
        to_ref = find_child(elem, "TableOccurrenceReference")
        if to_ref is not None:
            to_id = attr(to_ref, "id", "ID")
            to_name = to_name or attr(to_ref, "name", "Name")

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "table_occurrence_id": to_id,
        "table_occurrence_name": to_name,
        "theme": attr(elem, "theme", "Theme") or None,
        "referenced_fields": referenced_fields,
        "source_xml_path": xml_path(elem),
    }


def _collect_referenced_fields(layout_elem: etree._Element) -> list[dict[str, Any]]:
    """Walk <ObjectList> and pull field references from <FieldObj> children."""
    refs = []
    seen = set()
    for obj in find_all_descendants(layout_elem, "Object"):
        obj_type = attr(obj, "type", "Type")
        if obj_type in ("FieldObj", "Field", "FieldObject"):
            field_obj = find_child(obj, "FieldObj", "Field")
            if field_obj is not None:
                name_elem = find_child(field_obj, "Name")
                if name_elem is not None:
                    field_name = attr(name_elem, "field", "Field", "name", "Name")
                    table_name = attr(name_elem, "table", "Table", "tableName")
                    field_id = attr(name_elem, "id", "ID", "fieldID") or ""
                    key = f"{table_name}::{field_name}"
                    if key not in seen:
                        seen.add(key)
                        refs.append({
                            "field_id": field_id,
                            "field_name": field_name,
                            "table_name": table_name,
                        })
    return refs
