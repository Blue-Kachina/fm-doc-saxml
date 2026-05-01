"""Extract value lists from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_value_lists(database_elem: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(database_elem, "ValueListCatalog")
    if catalog is None:
        return []

    results = []
    for vl_elem in find_all_descendants(catalog, "ValueList"):
        results.append(_parse_value_list(vl_elem))
    return results


def _parse_value_list(elem: etree._Element) -> dict[str, Any]:
    list_type = attr(elem, "type", "Type") or "Custom"
    list_type_lower = list_type.lower()

    values = []
    source_field = None
    second_field = None
    source_table_name = None

    if "custom" in list_type_lower:
        normalized_type = "customValues"
        custom_values = find_child(elem, "CustomValues")
        if custom_values is not None:
            for val_elem in find_all_descendants(custom_values, "Value"):
                v = text_of(val_elem)
                if v:
                    values.append(v)
        # Also try direct <Value> children
        if not values:
            for val_elem in find_all_descendants(elem, "Value"):
                v = text_of(val_elem)
                if v:
                    values.append(v)
    elif "field" in list_type_lower or "related" in list_type_lower:
        normalized_type = "field" if "field" in list_type_lower else "related"
        src = find_child(elem, "SourceField", "Field")
        if src is not None:
            source_field = {
                "id": attr(src, "id", "ID"),
                "name": attr(src, "name", "Name"),
                "table": attr(src, "table", "Table", "tableName"),
            }
            source_table_name = source_field["table"]
        second = find_child(elem, "SecondField")
        if second is not None:
            second_field = {
                "id": attr(second, "id", "ID"),
                "name": attr(second, "name", "Name"),
                "table": attr(second, "table", "Table", "tableName"),
            }
    else:
        normalized_type = "customValues"

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "list_type": normalized_type,
        "values": values,
        "source_field": source_field,
        "second_field": second_field,
        "source_table_name": source_table_name,
        "source_xml_path": xml_path(elem),
    }
