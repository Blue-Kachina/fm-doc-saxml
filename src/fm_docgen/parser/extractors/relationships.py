"""Extract relationships from the FileMaker relationship graph."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path

_OPERATOR_MAP = {
    "0": "=",
    "1": "!=",
    "2": "<",
    "3": "<=",
    "4": ">",
    "5": ">=",
    "6": "cartesian",
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

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "left_table_id": _get_to_id(left_table),
        "left_table_name": _get_to_name(left_table),
        "right_table_id": _get_to_id(right_table),
        "right_table_name": _get_to_name(right_table),
        "predicates": predicates,
        "allow_create_related": attr(options_elem or elem, "allowCreateRelatedRecords", "createRelated") == "True" if options_elem is not None else False,
        "delete_related": attr(options_elem or elem, "deleteRelatedRecords", "deleteRelated") == "True" if options_elem is not None else False,
        "sort_related": attr(options_elem or elem, "sortRelatedRecords", "sortRelated") == "True" if options_elem is not None else False,
        "source_xml_path": xml_path(elem),
    }


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
    operator = _OPERATOR_MAP.get(op_code, op_code.lower() if op_code else "=")

    return {
        "left_field_id": _field_ref_id(left_field_wrapper),
        "left_field_name": _field_ref_name(left_field_wrapper),
        "left_table_name": _field_ref_to_name(left_field_wrapper),
        "right_field_id": _field_ref_id(right_field_wrapper),
        "right_field_name": _field_ref_name(right_field_wrapper),
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
