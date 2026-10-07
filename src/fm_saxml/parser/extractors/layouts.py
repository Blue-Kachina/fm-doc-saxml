"""Extract layouts and layout objects from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children, find_all_descendants, xml_path, modification_info
from .chunk_lists import ChunkLists, collect_calcs
from .scripts import _parse_step, _sibling_data_source


def extract_layouts(database_elem: etree._Element, chunk_lists: ChunkLists | None = None) -> list[dict[str, Any]]:
    """Return a list of raw layout dicts.

    Each layout dict carries:

    - id, name, uuid, theme
    - table_occurrence_id, table_occurrence_name
    - referenced_fields: deduplicated list of {field_id, field_name, table_name}
    - layout_objects: list of object dicts (one per LayoutObject in the XML, nested ones included)
    - script_triggers / calculations: layout-level triggers and their parameter calcs
    - source_xml_path
    """
    catalog = find_child(database_elem, "LayoutCatalog")
    if catalog is None:
        return []

    results: list[dict[str, Any]] = []
    _walk_layout_catalog(catalog, "", results, chunk_lists)
    return results


def _walk_layout_catalog(
    elem: etree._Element,
    folder_path: str,
    results: list[dict[str, Any]],
    chunk_lists: ChunkLists | None = None,
) -> None:
    """Collect layouts, skipping folders and dividers (which are ``<Layout>`` elements too).

    v2 catalogs are flat: ``<Layout isFolder="True">`` opens a folder, its items
    follow as siblings, and ``<Layout isFolder="Marker">`` closes it. Dividers are
    ``<Layout isSeparatorItem="True">``. Folders are tracked on a stack so real
    layouts still get a folder path.
    """
    open_folders: list[str] = []
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        if _local(child.tag) != "Layout":
            _walk_layout_catalog(child, folder_path, results, chunk_lists)  # wrapper elements (older formats)
            continue
        is_folder = attr(child, "isFolder", "IsFolder").lower()
        if attr(child, "isSeparatorItem", "IsSeparatorItem").lower() == "true":
            continue
        if is_folder == "marker":
            if open_folders:
                open_folders.pop()
            continue
        if is_folder == "true":
            open_folders.append(attr(child, "name", "Name"))
            continue
        layout = _parse_layout(child, chunk_lists)
        layout["folder_path"] = "/".join(p for p in [folder_path, *open_folders] if p) or None
        results.append(layout)


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _parse_layout(elem: etree._Element, chunk_lists: ChunkLists | None = None) -> dict[str, Any]:
    # v1: tableOccurrenceID is a direct attribute
    # v2: <TableOccurrenceReference id="..." name="..."> child element
    to_id = attr(elem, "tableOccurrenceID", "tableOccurrenceId", "tableID")
    to_name = attr(elem, "tableOccurrenceName", "tableName")
    if not to_id:
        to_ref = find_child(elem, "TableOccurrenceReference")
        if to_ref is not None:
            to_id = attr(to_ref, "id", "ID")
            to_name = to_name or attr(to_ref, "name", "Name")

    # v2: theme is in a <LayoutThemeReference> child; v1 keeps it as an attribute.
    theme = attr(elem, "theme", "Theme") or None
    if not theme:
        theme_ref = find_child(elem, "LayoutThemeReference")
        if theme_ref is not None:
            theme = attr(theme_ref, "name", "Name") or None

    # Collect every LayoutObject inside this layout (across all parts)
    layout_objects = _collect_layout_objects(elem, chunk_lists)
    triggers_elem = find_child(elem, "ScriptTriggers")

    # Backward-compatible referenced_fields list (deduped) — derived from objects
    referenced_fields = _dedupe_field_refs(layout_objects)

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": _layout_uuid(elem),
        "table_occurrence_id": to_id,
        "table_occurrence_name": to_name,
        "theme": theme,
        "referenced_fields": referenced_fields,
        "layout_objects": layout_objects,
        "script_triggers": _parse_script_triggers(elem),
        "calculations": (
            collect_calcs(triggers_elem, chunk_lists, lambda _path: "scriptTriggerParameter")
            if triggers_elem is not None else []
        ),
        "modified": modification_info(elem),
        "source_xml_path": xml_path(elem),
    }


def _layout_uuid(elem: etree._Element) -> str | None:
    """v1 stores uuid as an attribute; v2 has a <UUID> child element."""
    val = attr(elem, "uuid", "UUID") or None
    if val:
        return val
    uuid_child = find_child(elem, "UUID")
    if uuid_child is not None and uuid_child.text:
        return uuid_child.text.strip() or None
    return None


def _collect_layout_objects(
    layout_elem: etree._Element,
    chunk_lists: ChunkLists | None = None,
) -> list[dict[str, Any]]:
    """Walk every <LayoutObject> (or legacy v1 <Object type="...">) under this layout.

    The SaveAsXML v2 format wraps objects in ``<Part><ObjectList><LayoutObject>``.
    Objects nest: a portal's fields, a tab or slide panel's contents, a button bar's
    segments and a popover's panel are ``<LayoutObject>`` elements inside their
    container object; each is collected with ``parent_id`` set to its container.
    Older v1 exports use ``<Object type="FieldObj">`` / ``<Object type="Field">``.
    Both are handled here.
    """
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fallback_index = 0

    def collect(lo: etree._Element, part_label: str, parent_id: str | None) -> None:
        nonlocal fallback_index
        fallback_index += 1
        obj = _parse_layout_object(lo, part_label, fallback_index, chunk_lists)
        obj["parent_id"] = parent_id
        obj_key = obj["id"] or f"_idx{fallback_index}"
        if obj_key in seen_ids:
            return
        seen_ids.add(obj_key)
        results.append(obj)
        for child in _nested_objects(lo):
            collect(child, part_label, obj["id"] or None)

    # v2 path — <PartsList><Part><ObjectList><LayoutObject>
    parts_list = find_child(layout_elem, "PartsList")
    if parts_list is not None:
        for part_elem in find_all_children(parts_list, "Part"):
            part_label = attr(part_elem, "type", "Type") or attr(part_elem, "kind", "Kind") or ""
            obj_list = find_child(part_elem, "ObjectList")
            if obj_list is None:
                continue
            for lo in find_all_children(obj_list, "LayoutObject"):
                collect(lo, part_label, None)
        if results:
            return results

    # v1 path — <Object type="FieldObj"> nested anywhere within the layout
    for obj in find_all_descendants(layout_elem, "Object"):
        obj_type = attr(obj, "type", "Type")
        if not obj_type:
            continue
        fallback_index += 1
        parsed = _parse_v1_object(obj, fallback_index)
        if parsed is None:
            continue
        obj_key = parsed["id"] or f"_idx{fallback_index}"
        if obj_key in seen_ids:
            continue
        seen_ids.add(obj_key)
        results.append(parsed)

    return results


def _nested_objects(lo: etree._Element) -> list[etree._Element]:
    """LayoutObjects directly contained by ``lo`` (not those nested deeper inside them)."""
    found: list[etree._Element] = []

    def walk(node: etree._Element) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if _local(child.tag) == "LayoutObject":
                found.append(child)
            else:
                walk(child)

    walk(lo)
    return found


# Role of a calc inside a layout object: the first of these tags found on the path to it.
# Anything else is named after the element holding it (e.g. a portal <Filter> -> "filter").
_OBJECT_CALC_ROLES = (
    ("ScriptTrigger", "scriptTriggerParameter"),
    ("Hide", "hideCondition"),
    ("Formatting", "conditionalFormatting"),
    ("Tooltip", "tooltip"),
    ("Placeholder", "placeholder"),
    ("WebViewer", "webViewer"),
    ("Step", "buttonAction"),        # a calc in a single-step button's step (e.g. Set Field)
    ("action", "buttonParameter"),   # the script parameter of a Perform Script button
    ("Label", "label"),
    ("Title", "popoverTitle"),
    ("Select", "activeSegment"),
    ("TabPanel", "tabLabel"),
)


def _object_calc_role(path: list[str]) -> str:
    for tag, role in _OBJECT_CALC_ROLES:
        if tag in path:
            return role
    named = [t for t in path if t != "Calculation"]
    return named[-1][:1].lower() + named[-1][1:] if named else "calculation"


def _script_ref_dict(script_ref: etree._Element) -> dict[str, Any]:
    return {
        "id": attr(script_ref, "id", "ID"),
        "uuid": attr(script_ref, "uuid", "UUID"),
        "name": attr(script_ref, "name", "Name"),
        "data_source": _sibling_data_source(script_ref),
    }


def _parse_script_triggers(elem: etree._Element) -> list[dict[str, Any]]:
    """``<ScriptTriggers><ScriptTrigger action="OnLayoutEnter"><ScriptReference/>`` on a layout or object."""
    container = find_child(elem, "ScriptTriggers")
    triggers = []
    for trig in find_all_children(container, "ScriptTrigger") if container is not None else []:
        script_ref = find_child(trig, "ScriptReference")
        if script_ref is None or not attr(script_ref, "name", "Name"):
            continue
        triggers.append({"event": attr(trig, "action", "Action"), "script": _script_ref_dict(script_ref)})
    return triggers


def _field_ref_dict(fr: etree._Element) -> dict[str, str]:
    to_ref = find_child(fr, "TableOccurrenceReference")
    return {
        "field_id": attr(fr, "id", "ID") or "",
        "field_name": attr(fr, "name", "Name") or "",
        "field_uuid": attr(fr, "uuid", "UUID") or "",
        "table_name": attr(to_ref, "name", "Name") if to_ref is not None else "",
        "to_id": attr(to_ref, "id", "ID") if to_ref is not None else "",
    }


def _parse_portal(portal: etree._Element | None) -> dict[str, Any] | None:
    """A portal's table occurrence and the fields it sorts by."""
    if portal is None:
        return None
    to_ref = find_child(portal, "TableOccurrenceReference")
    sort_spec = find_child(portal, "SortSpecification")
    sort_fields = [
        _field_ref_dict(fr)
        for fr in (find_all_descendants(sort_spec, "FieldReference") if sort_spec is not None else [])
        if attr(fr, "name", "Name")
    ]
    return {
        "to_id": attr(to_ref, "id", "ID") if to_ref is not None else "",
        "to_name": attr(to_ref, "name", "Name") if to_ref is not None else "",
        "sort_fields": sort_fields,
    }


def _parse_layout_object(
    lo: etree._Element,
    part_label: str,
    fallback_index: int,
    chunk_lists: ChunkLists | None = None,
) -> dict[str, Any]:
    """Parse a v2 <LayoutObject>."""
    obj_type = attr(lo, "type", "Type")
    obj_id = attr(lo, "id", "ID")
    obj_name = attr(lo, "name", "Name")
    obj_kind = attr(lo, "kind", "Kind") or None
    obj_uuid = _layout_uuid(lo)

    bounds = _parse_bounds(find_child(lo, "Bounds"))

    # Field reference (Edit Box, Drop Down, etc. with an associated field)
    field_elem = find_child(lo, "Field")
    field_info = _parse_field_block(field_elem)

    # Value list attached to the control (<Field><Display><ValueListReference/>)
    value_list = None
    display = find_child(field_elem, "Display") if field_elem is not None else None
    vl_ref = find_child(display, "ValueListReference") if display is not None else None
    if vl_ref is not None and attr(vl_ref, "name", "Name"):
        value_list = {"id": attr(vl_ref, "id", "ID"), "name": attr(vl_ref, "name", "Name")}

    # Plain text content for "Text" objects
    raw_text = _parse_text_content(find_child(lo, "Text"))

    # Button action: <Button><action><ScriptReference/> (Perform Script) or <action><Step/> (single step).
    # Popover buttons carry the same <action>.
    button_script = None
    button_step = None
    button_elem = find_child(lo, "Button", "PopoverButton")
    action_elem = find_child(button_elem, "action") if button_elem is not None else None
    script_ref = find_child(action_elem, "ScriptReference") if action_elem is not None else None
    if script_ref is not None and attr(script_ref, "name", "Name"):
        button_script = _script_ref_dict(script_ref)
    step_elem = find_child(action_elem, "Step") if action_elem is not None else None
    if step_elem is not None:
        step = _parse_step(step_elem, 0)  # its calcs are collected below with the object's own
        button_step = {k: step[k] for k in ("name", "raw_text", "layout_ref", "field_refs", "value_list_refs")}
        if button_script is None and step["script_ref"]:
            button_script = step["script_ref"]

    return {
        "id": obj_id,
        "name": obj_name,
        "uuid": obj_uuid,
        "type": obj_type,
        "kind": obj_kind,
        "part": part_label or None,
        "bounds": bounds,
        "field": field_info,
        "value_list": value_list,
        "raw_text": raw_text,
        "button_script": button_script,
        "button_step": button_step,
        "portal": _parse_portal(find_child(lo, "Portal")),
        "script_triggers": _parse_script_triggers(lo),
        "calculations": collect_calcs(lo, chunk_lists, _object_calc_role, stop_at=("LayoutObject",)),
        "fallback_index": fallback_index,
        "source_xml_path": xml_path(lo),
    }


def _parse_v1_object(obj: etree._Element, fallback_index: int) -> dict[str, Any] | None:
    """Parse a legacy v1 <Object type="..."> element.

    Field placements appear as ``<Object type="FieldObj"><FieldObj><Name field="..."/>``.
    """
    obj_type = attr(obj, "type", "Type")
    obj_id = attr(obj, "id", "ID")
    obj_name = attr(obj, "name", "Name")

    field_info: dict[str, str] | None = None
    if obj_type in ("FieldObj", "Field", "FieldObject"):
        field_obj = find_child(obj, "FieldObj", "Field")
        if field_obj is not None:
            name_elem = find_child(field_obj, "Name")
            if name_elem is not None:
                field_info = {
                    "field_id": attr(name_elem, "id", "ID", "fieldID") or "",
                    "field_name": attr(name_elem, "field", "Field", "name", "Name") or "",
                    "table_name": attr(name_elem, "table", "Table", "tableName") or "",
                    "to_id": attr(name_elem, "tableID", "TableId") or "",
                }

    bounds = _parse_bounds(find_child(obj, "Bounds"))

    return {
        "id": obj_id,
        "name": obj_name,
        "uuid": attr(obj, "uuid", "UUID") or None,
        "type": obj_type,
        "kind": attr(obj, "kind", "Kind") or None,
        "part": None,
        "bounds": bounds,
        "field": field_info,
        "raw_text": None,
        "fallback_index": fallback_index,
        "source_xml_path": xml_path(obj),
    }


def _parse_bounds(b: etree._Element | None) -> dict[str, float] | None:
    if b is None:
        return None
    out: dict[str, float] = {}
    for k in ("top", "left", "bottom", "right"):
        v = attr(b, k, k.capitalize())
        if v:
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out or None


def _parse_field_block(field_elem: etree._Element | None) -> dict[str, str] | None:
    """Parse a v2 ``<Field>`` block on a LayoutObject.

    Structure::

        <Field>
            <FieldReference id="6" name="textField" repetition="1" UUID="...">
                <TableOccurrenceReference id="1065089" name="EverythingBagel" UUID="..."/>
            </FieldReference>
        </Field>
    """
    if field_elem is None:
        return None
    fr = find_child(field_elem, "FieldReference")
    if fr is None:
        return None
    to_ref = find_child(fr, "TableOccurrenceReference")
    table_name = attr(to_ref, "name", "Name") if to_ref is not None else ""
    to_id = attr(to_ref, "id", "ID") if to_ref is not None else ""
    return {
        "field_id": attr(fr, "id", "ID") or "",
        "field_name": attr(fr, "name", "Name") or "",
        "field_uuid": attr(fr, "uuid", "UUID") or "",
        "table_name": table_name,
        "to_id": to_id,
        "repetition": attr(fr, "repetition", "Repetition") or "",
    }


def _parse_text_content(text_elem: etree._Element | None) -> str | None:
    """Pull plaintext content out of a ``<Text>`` block (StyledText/Data)."""
    if text_elem is None:
        return None
    styled = find_child(text_elem, "StyledText")
    if styled is not None:
        data = find_child(styled, "Data")
        if data is not None and data.text:
            return data.text.strip() or None
    if text_elem.text:
        return text_elem.text.strip() or None
    return None


def _dedupe_field_refs(layout_objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deduped list of {field_id, field_name, table_name} from objects."""
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for obj in layout_objects:
        f = obj.get("field")
        if not f:
            continue
        fn = f.get("field_name", "")
        tn = f.get("table_name", "")
        if not fn:
            continue
        key = (tn, fn)
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "field_id": f.get("field_id", ""),
            "field_name": fn,
            "table_name": tn,
        })
    return refs
