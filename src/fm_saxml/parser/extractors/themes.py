"""Extract themes from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path, modification_info, uuid_of


def extract_themes(container: etree._Element) -> list[dict[str, Any]]:
    """Each ``<Theme>`` with its ``<Metadata>``. The ``<CSS>`` and ``<Image>`` (thumbnail) aren't kept."""
    catalog = find_child(container, "ThemeCatalog")
    if catalog is None:
        return []

    results = []
    for theme_elem in find_all_descendants(catalog, "Theme"):
        default_str = attr(theme_elem, "defaultTheme", "DefaultTheme", default="False")
        default_theme = default_str.lower() not in ("false", "0", "no")
        metadata = find_child(theme_elem, "Metadata")

        results.append({
            "id": attr(theme_elem, "id", "ID"),
            "name": attr(theme_elem, "name", "Name"),
            "uuid": uuid_of(theme_elem),
            "display_name": attr(theme_elem, "Display", "display", "displayName", default=""),
            "group": attr(theme_elem, "Group", "group") or None,
            "default_theme": default_theme,
            "version": attr(theme_elem, "version") or None,
            "platform": attr(theme_elem, "platform") or None,
            "locale": attr(theme_elem, "locale") or None,
            # A custom theme names the built-in theme it was made from
            "base_name": attr(theme_elem, "baseName") or None,
            "base_version": attr(theme_elem, "baseVersion") or None,
            "named_styles": _section(metadata, "namedstyles"),
            "color_palette": dict(sorted(_section(metadata, "colorpalette").items(), key=_swatch_number)),
            "layout_builder": _section(metadata, "layoutbuilder"),
            "charting": _section(metadata, "charting"),
            "modified": modification_info(theme_elem),
            "source_xml_path": xml_path(theme_elem),
        })
    return results


def _swatch_number(item: tuple[str, str]) -> tuple[int, str]:
    """``swatch10`` after ``swatch9`` (FileMaker writes them last to first)."""
    digits = item[0].lstrip("abcdefghijklmnopqrstuvwxyz")
    return (int(digits) if digits.isdigit() else 0, item[0])


def _section(metadata: etree._Element | None, tag: str) -> dict[str, str]:
    """``<Metadata><tag><key>value</key>…`` as ``{key: value}``, in the export's order."""
    section = find_child(metadata, tag) if metadata is not None else None
    if section is None:
        return {}
    return {child.tag.split("}")[-1]: text_of(child) for child in section if isinstance(child.tag, str)}
