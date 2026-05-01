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
    graph = find_child(database_elem, "RelationshipGraph")
    if graph is None:
        return []
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
        "left_table_id": attr(left_table, "id", "ID") if left_table is not None else "",
        "left_table_name": attr(left_table, "name", "Name") if left_table is not None else "",
        "right_table_id": attr(right_table, "id", "ID") if right_table is not None else "",
        "right_table_name": attr(right_table, "name", "Name") if right_table is not None else "",
        "predicates": predicates,
        "allow_create_related": attr(options_elem or elem, "allowCreateRelatedRecords", "createRelated") == "True" if options_elem is not None else False,
        "delete_related": attr(options_elem or elem, "deleteRelatedRecords", "deleteRelated") == "True" if options_elem is not None else False,
        "sort_related": attr(options_elem or elem, "sortRelatedRecords", "sortRelated") == "True" if options_elem is not None else False,
        "source_xml_path": xml_path(elem),
    }


def _parse_predicate(elem: etree._Element) -> dict[str, Any]:
    left_field = find_child(elem, "LeftField")
    right_field = find_child(elem, "RightField")

    op_code = attr(elem, "fieldCompareOp", "operator", "op") or "0"
    operator = _OPERATOR_MAP.get(op_code, "=")

    return {
        "left_field_id": attr(left_field, "id", "ID") if left_field is not None else "",
        "left_field_name": attr(left_field, "name", "Name") if left_field is not None else "",
        "left_table_name": attr(left_field, "tableName", "table") if left_field is not None else "",
        "right_field_id": attr(right_field, "id", "ID") if right_field is not None else "",
        "right_field_name": attr(right_field, "name", "Name") if right_field is not None else "",
        "right_table_name": attr(right_field, "tableName", "table") if right_field is not None else "",
        "operator": operator,
    }
