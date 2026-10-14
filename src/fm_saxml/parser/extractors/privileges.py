"""Extract privilege sets from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path, modification_info

# The <access> categories, in the order FileMaker's Edit Privilege Set dialog shows them.
_CATEGORIES = (("Records", "records"), ("Layouts", "layouts"), ("ValueLists", "value_lists"),
               ("Scripts", "scripts"))
_REFERENCE_TAGS = ("BaseTableReference", "TableOccurrenceReference", "LayoutReference", "ScriptReference",
                   "ValueListReference")


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
            "access": _parse_access(find_child(ps_elem, "access")),
            "modified": modification_info(ps_elem),
            "source_xml_path": xml_path(ps_elem),
        })
    return results


def _parse_access(access: etree._Element | None) -> dict[str, Any] | None:
    """``<access>``: one entry per category, plus ``<Other>`` (extended rights) and its password rule.

    A category is either a blanket setting (``<Records Create="True" Edit="True" Delete="True"/>``,
    ``<Layouts View="ReadOnly"/>``) or ``Custom="True"`` with a per-object list. The list's items
    are read generically: the object they name, every child carrying an ``access`` value (View,
    Edit, Create, Delete, Fields, ...), and the calculation of a "limited" access, so no column
    is dropped for an object kind not seen yet.
    """
    if access is None:
        return None
    out: dict[str, Any] = {"default": attr(access, "default").lower() == "true"}
    for tag, key in _CATEGORIES:
        elem = find_child(access, tag)
        if elem is not None:
            out[key] = _parse_category(elem)
    other = find_child(access, "Other")
    if other is not None:
        flags = {k: v for k, v in other.attrib.items() if k != "value"}
        password = find_child(other, "Password")
        if password is not None and attr(password, "prohibitModification"):
            flags["passwordChangeProhibited"] = attr(password, "prohibitModification")
        out["other"] = flags
    return out


def _parse_category(elem: etree._Element) -> dict[str, Any]:
    settings = {k: v for k, v in elem.attrib.items() if k != "Custom"}
    custom = find_child(elem, "Custom")
    if attr(elem, "Custom").lower() != "true" and custom is None:
        return {"settings": settings, "custom": None}
    items = []
    obj_list = find_child(custom, "ObjectList") if custom is not None else None
    for item in (obj_list if obj_list is not None else custom if custom is not None else []):
        if isinstance(item.tag, str):
            items.append(_parse_custom_item(item))
    return {"settings": settings, "custom": items}


def _parse_custom_item(item: etree._Element) -> dict[str, Any]:
    ref = find_child(item, *_REFERENCE_TAGS)
    ref_tag = ref.tag.split("}")[-1] if ref is not None else None
    access: dict[str, str] = {}
    calcs: dict[str, str] = {}
    for child in item:
        if not isinstance(child.tag, str):
            continue
        column = child.tag.split("}")[-1]
        if column in _REFERENCE_TAGS:
            continue
        value = attr(child, "access", "value")
        if value:
            access[column] = value
        calc = find_descendant_text(child, "Calculation")
        if calc:
            calcs[column] = calc
    return {
        "kind": item.tag.split("}")[-1],             # Table, Layout, Script, ValueList, ...
        "type": attr(item, "type") or None,          # "existing" | "New" (the row for new objects)
        "reference_kind": ref_tag,
        "name": attr(ref, "name", "Name") if ref is not None else "",
        "id": attr(ref, "id", "ID") if ref is not None else "",
        "attributes": {k: v for k, v in item.attrib.items() if k != "type"},
        "access": access,
        "calculations": [{"column": col, "calculation": text} for col, text in calcs.items()],
    }


def find_descendant_text(elem: etree._Element, tag: str) -> str | None:
    """Text of the first ``<Calculation><Text>`` (or a bare ``<Calculation>``) under ``elem``."""
    for calc in find_all_descendants(elem, tag):
        text_elem = find_child(calc, "Text")
        text = text_of(text_elem) if text_elem is not None else None
        if text:
            return text
    return None
