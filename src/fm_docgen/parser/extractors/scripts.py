"""Extract scripts and script steps from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_scripts(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw script dicts (each containing their steps)."""
    catalog = find_child(database_elem, "ScriptCatalog")
    if catalog is None:
        return []

    results = []
    _walk_script_folder(catalog, folder_path="", results=results)
    return results


def _walk_script_folder(elem: etree._Element, folder_path: str, results: list[dict[str, Any]]) -> None:
    """Recursively walk script folders, collecting scripts with their folder path."""
    for child in elem:
        local = _local(child.tag)
        if local in ("Script",):
            results.append(_parse_script(child, folder_path))
        elif local in ("ScriptFolder", "Folder", "Group"):
            folder_name = attr(child, "name", "Name")
            sub_path = f"{folder_path}/{folder_name}".lstrip("/")
            _walk_script_folder(child, sub_path, results)


def _parse_script(elem: etree._Element, folder_path: str) -> dict[str, Any]:
    step_list = find_child(elem, "StepList")
    steps = []
    if step_list is not None:
        for idx, step_elem in enumerate(find_all_descendants(step_list, "Step")):
            steps.append(_parse_step(step_elem, idx))

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "folder_path": folder_path or None,
        "steps": steps,
        "source_xml_path": xml_path(elem),
    }


def _parse_step(elem: etree._Element, fallback_index: int) -> dict[str, Any]:
    # FileMaker uses 'id' for the step type (e.g., 68 = Go to Layout), 'index' for position
    step_type_id = attr(elem, "id", "ID") or ""
    index = attr(elem, "index", "Index")
    try:
        index = int(index)
    except (ValueError, TypeError):
        index = fallback_index

    enabled_raw = attr(elem, "enable", "Enable", "enabled", "Enabled")
    enabled = enabled_raw.lower() not in ("false", "0", "no") if enabled_raw else True

    name = attr(elem, "name", "Name")

    # Collect step parameters — layout refs, field refs, script refs, calculations
    layout_ref = _extract_layout_ref(elem)
    field_refs = _extract_field_refs(elem)
    script_ref = _extract_script_ref(elem)
    calc = _extract_calculation(elem)

    # Build raw_text from available info
    raw_parts = [name]
    if layout_ref:
        raw_parts.append(f"[ {layout_ref['name']} ]")
    elif field_refs:
        raw_parts.append(f"[ {field_refs[0]['table']}::{field_refs[0]['name']} ]")
    elif script_ref:
        raw_parts.append(f"[ {script_ref['name']} ]")
    elif calc:
        raw_parts.append(f"[ {calc[:80]} ]")
    raw_text = " ".join(raw_parts)

    return {
        "step_type_id": step_type_id,
        "index": index,
        "name": name,
        "enabled": enabled,
        "raw_text": raw_text,
        "layout_ref": layout_ref,
        "field_refs": field_refs,
        "script_ref": script_ref,
        "calculation": calc,
    }


def _extract_layout_ref(elem: etree._Element) -> dict[str, Any] | None:
    layout = find_child(elem, "Layout")
    if layout is None:
        return None
    return {
        "id": attr(layout, "id", "ID"),
        "name": attr(layout, "name", "Name"),
    }


def _extract_field_refs(elem: etree._Element) -> list[dict[str, Any]]:
    refs = []
    for field in find_all_descendants(elem, "Field"):
        refs.append({
            "id": attr(field, "id", "ID"),
            "name": attr(field, "name", "Name"),
            "table": attr(field, "table", "Table", "tableName"),
            "table_id": attr(field, "tableID", "tableId"),
        })
    return refs


def _extract_script_ref(elem: etree._Element) -> dict[str, Any] | None:
    script = find_child(elem, "Script")
    if script is None:
        return None
    return {
        "id": attr(script, "id", "ID"),
        "name": attr(script, "name", "Name"),
    }


def _extract_calculation(elem: etree._Element) -> str | None:
    calc = find_child(elem, "Calculation")
    if calc is None:
        return None
    return text_of(calc) or None


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag
