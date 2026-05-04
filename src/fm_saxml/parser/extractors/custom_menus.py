"""Extract custom menus and custom menu sets from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, calc_text_of, xml_path


def extract_custom_menus(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "CustomMenuCatalog")
    if catalog is None:
        return []

    results = []
    for menu_elem in find_all_descendants(catalog, "CustomMenu"):
        base_elem = find_child(menu_elem, "Base")
        base_menu_name = attr(base_elem, "name", "Name") if base_elem is not None else None

        install_condition = None
        conditions_elem = find_child(menu_elem, "Conditions")
        if conditions_elem is not None:
            install_elem = find_child(conditions_elem, "Install")
            if install_elem is not None:
                calc_elem = find_child(install_elem, "Calculation")
                install_condition = calc_text_of(calc_elem) or None

        options_elem = find_child(menu_elem, "Options")
        browse_mode = True
        find_mode = True
        preview_mode = True
        if options_elem is not None:
            browse_mode = options_elem.get("browseMode", "True").lower() != "false"
            find_mode = options_elem.get("findMode", "True").lower() != "false"
            preview_mode = options_elem.get("previewMode", "True").lower() != "false"

        items = []
        item_list = find_child(menu_elem, "MenuItemList")
        if item_list is not None:
            for item_elem in find_all_descendants(item_list, "MenuItem"):
                item_base = find_child(item_elem, "Base")
                items.append({
                    "id": attr(item_elem, "id", "ID"),
                    "name": attr(item_elem, "name", "Name"),
                    "action_type": attr(item_elem, "type", "Type", default=""),
                    "base_name": attr(item_base, "name", "Name") if item_base is not None else None,
                })

        results.append({
            "id": attr(menu_elem, "id", "ID"),
            "name": attr(menu_elem, "name", "Name"),
            "base_menu_name": base_menu_name,
            "install_condition": install_condition,
            "browse_mode": browse_mode,
            "find_mode": find_mode,
            "preview_mode": preview_mode,
            "items": items,
            "source_xml_path": xml_path(menu_elem),
        })
    return results


def extract_custom_menu_sets(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "CustomMenuSetsCatalog")
    if catalog is None:
        return []

    results = []
    for set_elem in find_all_descendants(catalog, "CustomMenuSet"):
        menu_refs = []
        for ref in find_all_descendants(set_elem, "CustomMenuReference"):
            menu_refs.append({
                "id": attr(ref, "id", "ID"),
                "name": attr(ref, "name", "Name"),
            })

        results.append({
            "id": attr(set_elem, "id", "ID"),
            "name": attr(set_elem, "name", "Name"),
            "menu_refs": menu_refs,
            "source_xml_path": xml_path(set_elem),
        })
    return results
