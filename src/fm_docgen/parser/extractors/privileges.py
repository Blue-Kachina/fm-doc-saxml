"""Extract privilege sets from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_privilege_sets(database_elem: etree._Element) -> list[dict[str, Any]]:
    # v2 uses PrivilegeSetsCatalog (plural); v1 uses PrivilegesCatalog / PrivilegeSetCatalog
    catalog = find_child(
        database_elem,
        "PrivilegeSetsCatalog", "PrivilegesCatalog", "PrivilegeSetCatalog", "AccountCatalog",
    )
    if catalog is None:
        return []

    results = []
    for ps_elem in find_all_descendants(catalog, "PrivilegeSet", "Privilege"):
        description = (
            attr(ps_elem, "description", "Description")
            or text_of(find_child(ps_elem, "Description"))
            or None
        )
        results.append({
            "id": attr(ps_elem, "id", "ID"),
            "name": attr(ps_elem, "name", "Name"),
            "description": description,
            "source_xml_path": xml_path(ps_elem),
        })
    return results
