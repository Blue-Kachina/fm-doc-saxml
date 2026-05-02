"""Extract themes from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, xml_path


def extract_themes(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "ThemeCatalog")
    if catalog is None:
        return []

    results = []
    for theme_elem in find_all_descendants(catalog, "Theme"):
        default_str = attr(theme_elem, "defaultTheme", "DefaultTheme", default="False")
        default_theme = default_str.lower() not in ("false", "0", "no")

        results.append({
            "id": attr(theme_elem, "id", "ID"),
            "name": attr(theme_elem, "name", "Name"),
            "display_name": attr(theme_elem, "Display", "display", "displayName", default=""),
            "group": attr(theme_elem, "Group", "group") or None,
            "default_theme": default_theme,
            "source_xml_path": xml_path(theme_elem),
        })
    return results
