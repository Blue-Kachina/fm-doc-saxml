"""Extract value lists from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children, find_all_descendants, text_of, xml_path


def extract_value_lists(
    database_elem: etree._Element,
    v2_options_elem: etree._Element | None = None,
) -> list[dict[str, Any]]:
    catalog = find_child(database_elem, "ValueListCatalog")
    if catalog is None:
        return []

    # Build id → options dict from v2 OptionsForValueLists section
    options_map: dict[str, dict] = {}
    if v2_options_elem is not None:
        for vl_wrapper in find_all_children(v2_options_elem, "ValueList"):
            vl_ref = find_child(vl_wrapper, "ValueListReference")
            vl_id = attr(vl_ref, "id", "ID") if vl_ref is not None else ""
            if not vl_id:
                continue
            options_map[vl_id] = _parse_options_entry(vl_wrapper)

    results = []
    for vl_elem in find_all_descendants(catalog, "ValueList"):
        results.append(_parse_value_list(vl_elem, options_map))
    return results


def _parse_options_entry(vl_wrapper: etree._Element) -> dict:
    """Parse one <ValueList> entry from <OptionsForValueLists>."""
    source_elem = find_child(vl_wrapper, "Source")
    source_val = attr(source_elem, "value", "Value") if source_elem is not None else ""

    values = []
    source_field = None

    if source_val == "Custom":
        custom_values = find_child(vl_wrapper, "CustomValues")
        if custom_values is not None:
            text_elem = find_child(custom_values, "Text")
            raw_text = (text_elem.text or "") if text_elem is not None else ""
            values = [v.strip() for v in raw_text.splitlines() if v.strip()]
    elif source_val == "FromField":
        field_wrapper = find_child(vl_wrapper, "Field")
        if field_wrapper is not None:
            primary = find_child(field_wrapper, "PrimaryField")
            if primary is not None:
                field_ref = find_child(primary, "FieldReference")
                if field_ref is not None:
                    to_ref = find_child(field_ref, "TableOccurrenceReference")
                    source_field = {
                        "id": attr(field_ref, "id", "ID"),
                        "name": attr(field_ref, "name", "Name"),
                        "table": attr(to_ref, "name", "Name") if to_ref is not None else "",
                    }

    return {"values": values, "source_field": source_field}


def _parse_value_list(elem: etree._Element, options_map: dict[str, dict]) -> dict[str, Any]:
    vl_id = attr(elem, "id", "ID")

    # Determine list type from <Source value="..."> (v2) or type attribute (v1)
    source_elem = find_child(elem, "Source")
    if source_elem is not None:
        source_val = attr(source_elem, "value", "Value")
        if source_val == "Custom":
            list_type_lower = "custom"
        elif source_val == "FromField":
            list_type_lower = "field"
        else:
            list_type_lower = source_val.lower()
    else:
        list_type_lower = (attr(elem, "type", "Type") or "custom").lower()

    values: list[str] = []
    source_field = None
    second_field = None
    source_table_name = None

    # Merge from options map (v2 supplementary data)
    opt = options_map.get(vl_id, {})

    if "custom" in list_type_lower:
        normalized_type = "customValues"
        values = opt.get("values") or []
        if not values:
            # v1: values as child elements
            custom_values = find_child(elem, "CustomValues")
            if custom_values is not None:
                for val_elem in find_all_descendants(custom_values, "Value"):
                    v = text_of(val_elem)
                    if v:
                        values.append(v)
        if not values:
            for val_elem in find_all_descendants(elem, "Value"):
                v = text_of(val_elem)
                if v:
                    values.append(v)
    elif "field" in list_type_lower or "related" in list_type_lower:
        normalized_type = "field" if "field" in list_type_lower else "related"
        source_field = opt.get("source_field")
        if source_field is None:
            src = find_child(elem, "SourceField", "Field")
            if src is not None:
                source_field = {
                    "id": attr(src, "id", "ID"),
                    "name": attr(src, "name", "Name"),
                    "table": attr(src, "table", "Table", "tableName"),
                }
        if source_field:
            source_table_name = source_field.get("table")
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
        "id": vl_id,
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "list_type": normalized_type,
        "values": values,
        "source_field": source_field,
        "second_field": second_field,
        "source_table_name": source_table_name,
        "source_xml_path": xml_path(elem),
    }
