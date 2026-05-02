"""Extract file references (FileAccessCatalog) from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_file_references(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "FileAccessCatalog")
    if catalog is None:
        return []

    results = []
    for auth_elem in find_all_descendants(catalog, "Authorization"):
        display_elem = find_child(auth_elem, "Display")
        display_name = text_of(display_elem) if display_elem is not None else attr(auth_elem, "name", "Name")

        self_str = attr(auth_elem, "self", "Self", default="False")
        is_self = self_str.lower() not in ("false", "0", "no")

        results.append({
            "id": attr(auth_elem, "id", "ID"),
            "ref_type": attr(auth_elem, "type", "Type", default="Local"),
            "is_self": is_self,
            "display_name": display_name,
            "source_xml_path": xml_path(auth_elem),
        })
    return results
