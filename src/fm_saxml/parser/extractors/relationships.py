"""Extract relationships from the FileMaker relationship graph."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path, modification_info

_OPERATOR_MAP = {
    # v1 numeric codes
    "0": "=",
    "1": "≠",
    "2": "<",
    "3": "≤",
    "4": ">",
    "5": "≥",
    "6": "×",
    # v2 names
    "Equal": "=",
    "NotEqual": "≠",
    "Less": "<",
    "LessOrEqual": "≤",
    "Greater": ">",
    "GreaterOrEqual": "≥",
    "CartesianProduct": "×",
}


def extract_relationships(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw relationship dicts."""
    # v2: <RelationshipCatalog> is a direct child of the container
    # v1: it lives under <RelationshipGraph>
    catalog = find_child(database_elem, "RelationshipCatalog")
    if catalog is None:
        graph = find_child(database_elem, "RelationshipGraph")
        if graph is not None:
            catalog = find_child(graph, "RelationshipCatalog")
    if catalog is None:
        return []

    results = []
    for rel_elem in find_all_descendants(catalog, "Relationship"):
        results.append(_parse_relationship(rel_elem))
    return results


def _parse_relationship(elem: etree._Element) -> dict[str, Any]:
    left_table = find_child(elem, "LeftTable")
    right_table = find_child(elem, "RightTable")

    predicates = []
    predicate_list = find_child(elem, "JoinPredicateList")
    if predicate_list is not None:
        for pred in find_all_descendants(predicate_list, "JoinPredicate"):
            predicates.append(_parse_predicate(pred))

    options_elem = find_child(elem, "Options")
    left_side = _parse_side(left_table)
    right_side = _parse_side(right_table)

    def legacy_flag(*names: str) -> bool:
        return attr(options_elem, *names) == "True" if options_elem is not None else False

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "left_table_id": _get_to_id(left_table),
        "left_table_name": _get_to_name(left_table),
        "right_table_id": _get_to_id(right_table),
        "right_table_name": _get_to_name(right_table),
        "predicates": predicates,
        "left": left_side,
        "right": right_side,
        # Flat flags: true when either side has the option (older consumers; v1 <Options>)
        "allow_create_related": (legacy_flag("allowCreateRelatedRecords", "createRelated")
                                 or left_side["allow_create"] or right_side["allow_create"]),
        "delete_related": (legacy_flag("deleteRelatedRecords", "deleteRelated")
                           or left_side["delete"] or right_side["delete"]),
        "sort_related": (legacy_flag("sortRelatedRecords", "sortRelated")
                         or bool(left_side["sort"]) or bool(right_side["sort"])),
        "modified": modification_info(elem),
        "source_xml_path": xml_path(elem),
    }


def _parse_side(table_elem: etree._Element | None) -> dict[str, Any]:
    """One side's options: ``<LeftTable cascadeCreate cascadeDelete>`` and its ``<SortSpecification>``.

    Each option is about the records of *this* side's table occurrence: allow creating
    them through the relationship, delete them when the other side's record is deleted,
    sort them.
    """
    if table_elem is None:
        return {"allow_create": False, "delete": False, "sort": []}
    return {
        "allow_create": attr(table_elem, "cascadeCreate").lower() == "true",
        "delete": attr(table_elem, "cascadeDelete").lower() == "true",
        "sort": parse_sort_spec(find_child(table_elem, "SortSpecification")),
    }


def parse_sort_spec(spec: etree._Element | None) -> list[dict[str, Any]]:
    """``<SortSpecification><SortList><Sort type="Ascending|Descending|Custom">`` -> sort fields in order.

    A custom sort names the value list that gives the order.
    """
    if spec is None or attr(spec, "value").lower() == "false":
        return []
    out = []
    for sort in find_all_descendants(spec, "Sort"):
        primary = find_child(sort, "PrimaryField")
        fr = find_child(primary, "FieldReference") if primary is not None else None
        # No field, or name="": a field FileMaker can't find any more. Kept, shown as missing.
        to_ref = find_child(fr, "TableOccurrenceReference") if fr is not None else None
        vl_ref = find_child(sort, "ValueListReference")
        out.append({
            "field_id": attr(fr, "id", "ID") if fr is not None else "",
            "field_name": attr(fr, "name", "Name") if fr is not None else "",
            "field_uuid": attr(fr, "UUID", "uuid") if fr is not None else "",
            "table_name": attr(to_ref, "name", "Name") if to_ref is not None else "",
            "order": attr(sort, "type") or "Ascending",
            "value_list": attr(vl_ref, "name", "Name") or None if vl_ref is not None else None,
        })
    return out


def _get_to_id(table_elem: etree._Element | None) -> str:
    if table_elem is None:
        return ""
    # v1: id/name directly on <LeftTable>/<RightTable>
    direct_id = attr(table_elem, "id", "ID")
    if direct_id:
        return direct_id
    # v2: <TableOccurrenceReference id="...">
    to_ref = find_child(table_elem, "TableOccurrenceReference")
    return attr(to_ref, "id", "ID") if to_ref is not None else ""


def _get_to_name(table_elem: etree._Element | None) -> str:
    if table_elem is None:
        return ""
    # v1: id/name directly on <LeftTable>/<RightTable>
    direct_name = attr(table_elem, "name", "Name")
    if direct_name:
        return direct_name
    # v2: <TableOccurrenceReference name="...">
    to_ref = find_child(table_elem, "TableOccurrenceReference")
    return attr(to_ref, "name", "Name") if to_ref is not None else ""


def _parse_predicate(elem: etree._Element) -> dict[str, Any]:
    left_field_wrapper = find_child(elem, "LeftField")
    right_field_wrapper = find_child(elem, "RightField")

    op_code = attr(elem, "fieldCompareOp", "operator", "op", "type") or "0"
    # v2 uses type="Equal" string; v1 uses numeric codes
    operator = _OPERATOR_MAP.get(op_code, op_code or "=")

    return {
        "left_field_id": _field_ref_id(left_field_wrapper),
        "left_field_name": _field_ref_name(left_field_wrapper),
        "left_field_uuid": _field_ref_uuid(left_field_wrapper),
        "left_table_name": _field_ref_to_name(left_field_wrapper),
        "right_field_id": _field_ref_id(right_field_wrapper),
        "right_field_name": _field_ref_name(right_field_wrapper),
        "right_field_uuid": _field_ref_uuid(right_field_wrapper),
        "right_table_name": _field_ref_to_name(right_field_wrapper),
        "operator": operator,
    }


def _field_ref_id(wrapper: etree._Element | None) -> str:
    if wrapper is None:
        return ""
    # v1: <LeftField id="..."> directly
    direct = attr(wrapper, "id", "ID")
    if direct:
        return direct
    # v2: <FieldReference id="..."> child
    ref = find_child(wrapper, "FieldReference")
    return attr(ref, "id", "ID") if ref is not None else ""


def _field_ref_uuid(wrapper: etree._Element | None) -> str:
    if wrapper is None:
        return ""
    ref = find_child(wrapper, "FieldReference")
    return attr(ref, "uuid", "UUID") if ref is not None else ""


def _field_ref_name(wrapper: etree._Element | None) -> str:
    if wrapper is None:
        return ""
    direct = attr(wrapper, "name", "Name")
    if direct:
        return direct
    ref = find_child(wrapper, "FieldReference")
    return attr(ref, "name", "Name") if ref is not None else ""


def _field_ref_to_name(wrapper: etree._Element | None) -> str:
    if wrapper is None:
        return ""
    # v1: tableName on <LeftField>/<RightField>
    direct = attr(wrapper, "tableName", "table")
    if direct:
        return direct
    # v2: <FieldReference><TableOccurrenceReference name="...">
    ref = find_child(wrapper, "FieldReference")
    if ref is not None:
        to_ref = find_child(ref, "TableOccurrenceReference")
        return attr(to_ref, "name", "Name") if to_ref is not None else ""
    return ""
