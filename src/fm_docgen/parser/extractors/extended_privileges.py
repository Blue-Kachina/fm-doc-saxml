"""Extract extended privileges from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_extended_privileges(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "ExtendedPrivilegesCatalog")
    if catalog is None:
        return []

    results = []
    for ep_elem in find_all_descendants(catalog, "ExtendedPrivilege"):
        desc_elem = find_child(ep_elem, "Description")
        description = text_of(desc_elem) or attr(ep_elem, "description", "Description") or None

        ps_refs = []
        for ps_ref in find_all_descendants(ep_elem, "PrivilegeSetReference"):
            ps_refs.append({
                "id": attr(ps_ref, "id", "ID"),
                "name": attr(ps_ref, "name", "Name"),
            })

        results.append({
            "id": attr(ep_elem, "id", "ID"),
            "name": attr(ep_elem, "name", "Name"),
            "description": description,
            "privilege_set_refs": ps_refs,
            "source_xml_path": xml_path(ep_elem),
        })
    return results
