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
            for item_elem in find_all_descendants(item_list, "MenuItem", "CustomMenuItem"):
                items.append(_parse_menu_item(item_elem))

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


def _parse_menu_item(item_elem: etree._Element) -> dict[str, Any]:
    """One menu item. v2 items are ``<CustomMenuItem>``: a separator, a submenu
    (``<CustomMenuReference>``), a built-in ``<Command>``, or an ``<action>``
    holding a script step (typically Perform Script)."""
    item_base = find_child(item_elem, "Base")  # v1
    item: dict[str, Any] = {
        "id": attr(item_elem, "id", "ID"),
        "name": attr(item_elem, "name", "Name"),
        "action_type": attr(item_elem, "type", "Type", default=""),
        "base_name": attr(item_base, "name", "Name") if item_base is not None else None,
        "script_ref": None,
        "submenu_name": None,
    }
    if attr(item_elem, "isSeparatorItem").lower() == "true":
        item.update(name=item["name"] or "-", action_type="separator")
        return item

    submenu = find_child(item_elem, "CustomMenuReference")
    command = find_child(item_elem, "Command")
    action = find_child(item_elem, "action")
    if submenu is not None:
        item.update(name=item["name"] or attr(submenu, "name", "Name"), action_type="submenu",
                    submenu_name=attr(submenu, "name", "Name"))
    elif command is not None:
        item.update(name=item["name"] or attr(command, "name", "Name"), action_type="command")
    elif action is not None:
        from .scripts import _parse_step
        step_elem = find_child(action, "Step")
        if step_elem is not None:
            step = _parse_step(step_elem, 0)
            script = step.get("script_ref")
            item.update(
                name=item["name"] or (f"{step['name']} [ {script['name']} ]" if script else step["name"]),
                action_type="script" if script else "action",
                script_ref=script,
            )
    return item


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
