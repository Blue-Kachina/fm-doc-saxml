"""Extract fields from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import (
    attr, find_child, find_all_children, find_all_descendants, calc_text_of, text_of, xml_path, modification_info, uuid_of,
)
from .chunk_lists import ChunkLists, collect_calcs


def extract_fields(
    database_elem: etree._Element,
    v2_fields_elem: etree._Element | None = None,
    chunk_lists: ChunkLists | None = None,
) -> list[dict[str, Any]]:
    """Return a list of raw field dicts, each tagged with its parent table id/name."""
    if v2_fields_elem is not None:
        return _extract_fields_v2(v2_fields_elem, chunk_lists)
    return _extract_fields_v1(database_elem)


def _extract_fields_v1(database_elem: etree._Element) -> list[dict[str, Any]]:
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


def _extract_fields_v2(fields_for_tables: etree._Element, chunk_lists: ChunkLists | None) -> list[dict[str, Any]]:
    """v2: <FieldsForTables><FieldCatalog><BaseTableReference id name>...<ObjectList><Field...>"""
    fields = []
    for fc in find_all_children(fields_for_tables, "FieldCatalog"):
        table_ref = find_child(fc, "BaseTableReference")
        table_id = attr(table_ref, "id", "ID") if table_ref is not None else ""
        table_name = attr(table_ref, "name", "Name") if table_ref is not None else ""
        obj_list = find_child(fc, "ObjectList")
        if obj_list is None:
            continue
        for field_elem in find_all_children(obj_list, "Field"):
            fields.append(_parse_field(field_elem, table_id, table_name, chunk_lists))
    return fields


def _field_calc_role(path: list[str]) -> str:
    """Role of a calc inside a ``<Field>``, from the tags leading to it."""
    for tag, role in (("AutoEnter", "autoEnter"), ("MessageCalc", "validationMessage"), ("Validation", "validation"),
                      ("Storage", "storageLocation")):
        if tag in path:
            return role
    return "calculation"


def _parse_field(
    elem: etree._Element,
    table_id: str,
    table_name: str,
    chunk_lists: ChunkLists | None = None,
) -> dict[str, Any]:
    auto_enter = _parse_auto_enter(find_child(elem, "AutoEnter"))
    validation = _parse_validation(find_child(elem, "Validation"))
    storage = _parse_storage(find_child(elem, "Storage"))
    calculation_elem = find_child(elem, "Calculation")
    summary_info = find_child(elem, "SummaryInfo")  # v2 wraps <SummaryField> in <SummaryInfo operation=...>
    summary_field = _parse_summary_field(
        find_child(summary_info if summary_info is not None else elem, "SummaryField"), table_name)
    ae_elem = find_child(elem, "AutoEnter")

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": uuid_of(elem),
        "comment": attr(elem, "comment", "Comment") or None,
        # v1 uses dataType/fieldType (camelCase); v2 uses datatype/fieldtype (lower)
        "data_type": attr(elem, "dataType", "DataType", "datatype", "fieldDataType") or "Text",
        "field_type": attr(elem, "fieldType", "FieldType", "fieldtype") or "Normal",
        "table_id": table_id,
        "table_name": table_name,
        "calculation": calc_text_of(calculation_elem) or None,
        "calculations": collect_calcs(elem, chunk_lists, _field_calc_role),
        "auto_enter": auto_enter,
        "validation": validation,
        "storage": storage,
        "summary_field": summary_field,
        "summary": _parse_summary_info(summary_info),
        "annotation": text_of(find_child(elem, "Annotation")) or None,
        # Calculation fields: <AutoEnter alwaysEvaluate="True"> = "Do not evaluate if all referenced
        # fields are empty" is unchecked.
        "always_evaluate": (
            attr(ae_elem, "alwaysEvaluate").lower() == "true"
            if ae_elem is not None and attr(ae_elem, "alwaysEvaluate") and not attr(ae_elem, "type") else None
        ),
        "modified": modification_info(elem),
        "source_xml_path": xml_path(elem),
    }


def _parse_summary_field(elem: etree._Element | None, owning_table_name: str) -> dict[str, str] | None:
    """A summary field's source: ``<SummaryField><FieldReference/><BaseTableReference/></SummaryField>``.

    A summary field always aggregates a field on its own table, so fall back
    to the owning field's own table name if no ``<BaseTableReference>`` is
    present.
    """
    if elem is None:
        return None
    field_ref = find_child(elem, "FieldReference")
    if field_ref is None:
        return None
    field_name = attr(field_ref, "name", "Name")
    if not field_name:
        return None
    base_table_ref = find_child(elem, "BaseTableReference")
    table_name = attr(base_table_ref, "name", "Name") if base_table_ref is not None else ""
    return {"name": field_name, "table": table_name or owning_table_name}


def _parse_summary_info(elem: etree._Element | None) -> dict[str, Any] | None:
    """``<SummaryInfo operation="Total" restartEachGroup="False" summarizeRepetition="Together">``."""
    if elem is None or not attr(elem, "operation"):
        return None
    return {
        "operation": attr(elem, "operation"),  # Total, Average, Count, Minimum, Maximum, StdDev, FractionOfTotal, List
        "restart_each_group": attr(elem, "restartEachGroup").lower() == "true",
        "summarize_repetition": attr(elem, "summarizeRepetition") or None,  # Together | Individually
    }


def _parse_auto_enter(elem: etree._Element | None) -> dict[str, Any] | None:
    if elem is None:
        return None
    ae_type = "none"
    value = None
    calculation = None

    v2_type = attr(elem, "type")  # v2: type="Calculated" | "ConstantData" | "SerialNumber" | "CreationTimestamp" ...
    if v2_type:
        return _parse_auto_enter_v2(elem, v2_type)

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


def _parse_auto_enter_v2(elem: etree._Element, v2_type: str) -> dict[str, Any]:
    """v2 auto-enter: the kind is the ``type`` attribute, its detail a child named after it.

    ``<AutoEnter type="Calculated"><Calculated><Calculation><Text/>``,
    ``<AutoEnter type="ConstantData"><ConstantData>1</ConstantData>``.
    """
    value = None
    calculation = None
    if v2_type == "Calculated":
        ae_type = "calculation"
        calculated = find_child(elem, "Calculated")
        calculation = calc_text_of(find_child(calculated, "Calculation")) if calculated is not None else ""
        calculation = calculation or None
    elif v2_type == "ConstantData":
        ae_type = "data"
        constant = find_child(elem, "ConstantData")
        value = (constant.text or "").strip() if constant is not None else None
    elif v2_type == "SerialNumber":
        ae_type = "serial"
    elif v2_type in ("Lookup", "Looked_up"):
        ae_type = "lookup"
    elif v2_type.startswith("Creation"):
        ae_type = "creation"
        value = v2_type[len("Creation"):] or None  # what is stamped: Timestamp, AccountName ...
    elif v2_type.startswith("Modification"):
        ae_type = "modification"
        value = v2_type[len("Modification"):] or None
    else:
        ae_type = v2_type[:1].lower() + v2_type[1:]  # e.g. LastVisited -> lastVisited
    serial = find_child(elem, "SerialNumber") if v2_type == "SerialNumber" else None
    looked_up = find_child(elem, "Looked_up")
    overwrite = attr(elem, "overwriteExisting")
    return {
        "type": ae_type,
        "value": value,
        "calculation": calculation,
        "no_modify_auto_enter": attr(elem, "prohibitModification").lower() == "true",
        # Calculated value: overwriteExisting="False" = "Do not replace existing value of field (if any)"
        "overwrite_existing": overwrite.lower() == "true" if overwrite else None,
        "serial": {
            "increment": attr(serial, "increment") or None,
            "generate": attr(serial, "generate") or None,  # OnCreation | OnCommit
        } if serial is not None else None,
        "lookup": _parse_lookup(looked_up) if ae_type == "lookup" else None,
    }


def _parse_lookup(elem: etree._Element | None) -> dict[str, Any] | None:
    """``<Looked_up dontCopyIfEmpty noMatchCopyOption><FieldReference/><Context><TableOccurrenceReference/>``.

    Copies the value of the source field (reached through the context TO's relationships).
    """
    if elem is None:
        return None
    fr = find_child(elem, "FieldReference")
    to_ref = find_child(fr, "TableOccurrenceReference") if fr is not None else None
    context = find_child(elem, "Context")
    ctx_ref = find_child(context, "TableOccurrenceReference") if context is not None else None
    return {
        "field_name": attr(fr, "name", "Name") if fr is not None else "",
        "table_name": attr(to_ref, "name", "Name") if to_ref is not None else "",
        "context": attr(ctx_ref, "name", "Name") if ctx_ref is not None else None,
        "dont_copy_if_empty": attr(elem, "dontCopyIfEmpty").lower() == "true",
        "no_match": attr(elem, "noMatchCopyOption") or None,  # DoNotCopy | CopyNext | CopyPrevious | Constant
        "no_match_value": text_of(find_child(elem, "Constant")) or None,
    }


_VALIDATION_KNOWN = {"NotEmpty", "Required", "Unique", "MaximumCharacters", "MaximumSize", "ValueListReference",
                     "Message", "MessageCalc", "Strict", "Calculation", "Calculated", "Range", "UUID"}


def _parse_validation(elem: etree._Element | None) -> dict[str, Any] | None:
    """Validation options; None when the field has no rule at all.

    v2: ``<Validation type="OnlyDuringDataEntry|Always" allowOverride notEmpty unique existing>``
    with ``<Strict>Numeric</Strict>``, ``<Message>…</Message>``, ``<ValueListReference/>`` and a
    ``<Calculation>`` as children. v1 uses child elements (``<NotEmpty value="True"/>``) instead
    of the attributes. Children not recognised here are kept in ``other`` rather than dropped.
    """
    if elem is None:
        return None

    not_empty_elem = find_child(elem, "NotEmpty")
    required_elem = find_child(elem, "Required")
    unique_elem = find_child(elem, "Unique")
    max_chars_elem = find_child(elem, "MaximumCharacters")
    max_size_elem = find_child(elem, "MaximumSize")  # v2: <MaximumSize>140</MaximumSize>

    def _bool_attr(child_elem, inline_name: str) -> bool:
        if child_elem is not None:
            return attr(child_elem, "value", "Value") == "True"
        return attr(elem, inline_name).lower() == "true"

    vl_ref = find_child(elem, "ValueListReference")
    value_list = attr(vl_ref, "name", "Name") if vl_ref is not None else ""
    message_elem = find_child(elem, "Message")
    strict_elem = find_child(elem, "Strict")
    # v2: <Calculated enable="True"><Calculation>; the message may be a calc: <MessageCalc enable="True">
    calc_elem = find_child(elem, "Calculated", "Calculation")
    if calc_elem is not None and attr(calc_elem, "enable").lower() == "false":
        calc_elem = None
    message_calc = find_child(elem, "MessageCalc")
    if message_calc is not None and attr(message_calc, "enable").lower() == "false":
        message_calc = None
    range_elem = find_child(elem, "Range")
    allow_override = attr(elem, "allowOverride")
    always_validate = attr(elem, "alwaysValidate")

    other: dict[str, str] = {}
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.split("}")[-1]
        if tag in _VALIDATION_KNOWN:
            continue
        detail = (child.text or "").strip() or " ".join(f"{k}={v}" for k, v in child.attrib.items())
        other[tag] = detail

    result = {
        "value_list": value_list or None,
        "required": _bool_attr(required_elem, "required"),
        "not_empty": _bool_attr(not_empty_elem, "notEmpty"),
        "unique": _bool_attr(unique_elem, "unique"),
        "existing": _bool_attr(None, "existing"),  # "Existing value"
        "max_characters": None,
        "strict_type": (strict_elem.text or "").strip() or None if strict_elem is not None else None,
        "has_calculation": calc_elem is not None,  # its text is in the field's calculations (role "validation")
        "has_message_calculation": message_calc is not None,  # text: calculations, role "validationMessage"
        # Validated by calculation: alwaysValidate="False" = "Validate only if field has been modified"
        "always_validate": always_validate.lower() == "true" if always_validate else None,
        "range": " ".join(f"{k}={v}" for k, v in range_elem.attrib.items()) or text_of(range_elem) or None
        if range_elem is not None else None,
        "other": other,
        "message": (
            attr(elem, "message", "Message")
            or (text_of(message_elem) if message_elem is not None else "")
            or None
        ),
        "validate": attr(elem, "type") or None,  # Always | OnlyDuringDataEntry
        "allow_override": allow_override.lower() == "true" if allow_override else None,
    }
    if max_chars_elem is not None or max_size_elem is not None:
        raw_max = attr(max_chars_elem, "value", "Value") if max_chars_elem is not None else text_of(max_size_elem)
        try:
            result["max_characters"] = int(raw_max or "0") or None
        except ValueError:
            pass

    if not any([result["required"], result["not_empty"], result["unique"], result["existing"],
                result["max_characters"], result["value_list"], result["strict_type"],
                result["has_calculation"], result["has_message_calculation"], result["range"],
                result["message"], result["other"]]):
        return None
    return result


def _parse_storage(elem: etree._Element | None) -> dict[str, Any]:
    if elem is None:
        return {"global": False, "indexed": False, "index": "None", "autoIndex": False, "maxRepeat": 1}
    global_val = attr(elem, "global", "Global") == "True"
    # "index" and "autoIndex" are two distinct attributes (e.g.
    # `index="Minimal" autoIndex="True"`) — looked up separately so one
    # doesn't mask the other.
    index_raw = attr(elem, "index", "Index") or "None"
    auto_index = attr(elem, "autoIndex", "AutoIndex").lower() == "true"
    indexed = index_raw.lower() not in ("", "none", "false")
    try:
        # The real SaveAsXML attribute is "maxRepetitions"; "maxRepeat" is
        # kept as a fallback in case an older export version used it.
        max_repeat = int(attr(elem, "maxRepetitions", "MaxRepetitions", "maxRepeat", "MaxRepeat") or "1")
    except ValueError:
        max_repeat = 1
    stored = attr(elem, "storeCalculationResults")
    remote = find_child(elem, "Remote")  # container: "Store container data externally"
    base_dir = find_child(remote, "BaseDirectoryReference") if remote is not None else None
    return {
        "global": global_val,
        "stored": stored.lower() == "true" if stored else None,  # calculation fields only
        "external_storage": {
            "type": attr(remote, "type") or None,  # Secure | Open
            "base_directory": attr(base_dir, "name") or None if base_dir is not None else None,
        } if remote is not None else None,
        "indexed": indexed,
        "index": index_raw,
        "autoIndex": auto_index,
        "maxRepeat": max_repeat,
    }
