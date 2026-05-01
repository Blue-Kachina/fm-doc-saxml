"""Extract fields from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_fields(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw field dicts, each tagged with its parent table id/name."""
    catalog = find_child(database_elem, "TableCatalog", "BaseTableCatalog")
    if catalog is None:
        return []

    fields = []
    for base_table in find_all_descendants(catalog, "BaseTable"):
        table_id = attr(base_table, "id", "ID")
        table_name = attr(base_table, "name", "Name")
        field_catalog = find_child(base_table, "FieldCatalog")
        if field_catalog is None:
            continue
        for field_elem in find_all_descendants(field_catalog, "Field", "BaseField"):
            fields.append(_parse_field(field_elem, table_id, table_name))
    return fields


def _parse_field(elem: etree._Element, table_id: str, table_name: str) -> dict[str, Any]:
    auto_enter = _parse_auto_enter(find_child(elem, "AutoEnter"))
    validation = _parse_validation(find_child(elem, "Validation"))
    storage = _parse_storage(find_child(elem, "Storage"))
    calculation_elem = find_child(elem, "Calculation")

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "data_type": attr(elem, "dataType", "DataType", "fieldDataType") or "Text",
        "field_type": attr(elem, "fieldType", "FieldType") or "Normal",
        "table_id": table_id,
        "table_name": table_name,
        "calculation": text_of(calculation_elem) or None,
        "auto_enter": auto_enter,
        "validation": validation,
        "storage": storage,
        "source_xml_path": xml_path(elem),
    }


def _parse_auto_enter(elem: etree._Element | None) -> dict[str, Any] | None:
    if elem is None:
        return None
    ae_type = "none"
    value = None
    calculation = None

    if attr(elem, "serial", "Serial") == "True":
        ae_type = "serial"
    elif attr(elem, "lookup", "Lookup") == "True":
        ae_type = "lookup"
    elif attr(elem, "constant", "Constant"):
        ae_type = "data"
        value = attr(elem, "constant", "Constant")

    calc_elem = find_child(elem, "Calculation")
    if calc_elem is not None and text_of(calc_elem):
        ae_type = "calculation"
        calculation = text_of(calc_elem)

    if ae_type == "none" and not value and not calculation:
        return None

    return {
        "type": ae_type,
        "value": value,
        "calculation": calculation,
        "no_modify_auto_enter": attr(elem, "allowEditing", "AllowEditing") == "False",
    }


def _parse_validation(elem: etree._Element | None) -> dict[str, Any] | None:
    if elem is None:
        return None

    not_empty_elem = find_child(elem, "NotEmpty")
    required_elem = find_child(elem, "Required")
    unique_elem = find_child(elem, "Unique")
    max_chars_elem = find_child(elem, "MaximumCharacters")

    result = {
        "required": attr(required_elem, "value", "Value") == "True" if required_elem is not None else False,
        "not_empty": attr(not_empty_elem, "value", "Value") == "True" if not_empty_elem is not None else False,
        "unique": attr(unique_elem, "value", "Value") == "True" if unique_elem is not None else False,
        "max_characters": None,
        "message": attr(elem, "message", "Message") or None,
    }
    if max_chars_elem is not None:
        try:
            result["max_characters"] = int(attr(max_chars_elem, "value", "Value") or "0") or None
        except ValueError:
            pass

    if not any([result["required"], result["not_empty"], result["unique"], result["max_characters"]]):
        return None
    return result


def _parse_storage(elem: etree._Element | None) -> dict[str, Any]:
    if elem is None:
        return {"global": False, "indexed": False, "maxRepeat": 1}
    global_val = attr(elem, "global", "Global") == "True"
    indexed_raw = attr(elem, "index", "Index", "autoIndex", "AutoIndex") or ""
    indexed = indexed_raw.lower() not in ("", "none", "false")
    try:
        max_repeat = int(attr(elem, "maxRepeat", "MaxRepeat") or "1")
    except ValueError:
        max_repeat = 1
    return {"global": global_val, "indexed": indexed, "maxRepeat": max_repeat}
