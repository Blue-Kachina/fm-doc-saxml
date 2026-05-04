"""Extract layouts and layout objects from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children, find_all_descendants, xml_path


def extract_layouts(database_elem: etree._Element) -> list[dict[str, Any]]:
    """Return a list of raw layout dicts.

    Each layout dict carries:

    - id, name, uuid, theme
    - table_occurrence_id, table_occurrence_name
    - referenced_fields: deduplicated list of {field_id, field_name, table_name}
    - layout_objects: list of object dicts (one per LayoutObject in the XML)
    - source_xml_path
    """
    catalog = find_child(database_elem, "LayoutCatalog")
    if catalog is None:
        return []

    results = []
    for layout_elem in find_all_descendants(catalog, "Layout"):
        results.append(_parse_layout(layout_elem))
    return results


def _parse_layout(elem: etree._Element) -> dict[str, Any]:
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
    layout_objects = _collect_layout_objects(elem)

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


def _collect_layout_objects(layout_elem: etree._Element) -> list[dict[str, Any]]:
    """Walk every <LayoutObject> (or legacy v1 <Object type="...">) under this layout.

    The SaveAsXML v2 format wraps objects in ``<Part><ObjectList><LayoutObject>``.
    Older v1 exports use ``<Object type="FieldObj">`` / ``<Object type="Field">``.
    Both are handled here.
    """
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fallback_index = 0

    # v2 path — <PartsList><Part><ObjectList><LayoutObject>
    parts_list = find_child(layout_elem, "PartsList")
    if parts_list is not None:
        for part_elem in find_all_children(parts_list, "Part"):
            part_label = attr(part_elem, "type", "Type") or attr(part_elem, "kind", "Kind") or ""
            obj_list = find_child(part_elem, "ObjectList")
            if obj_list is None:
                continue
            for lo in find_all_children(obj_list, "LayoutObject"):
                fallback_index += 1
                obj = _parse_layout_object(lo, part_label, fallback_index)
                obj_key = obj["id"] or f"_idx{fallback_index}"
                if obj_key in seen_ids:
                    continue
                seen_ids.add(obj_key)
                results.append(obj)
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


def _parse_layout_object(
    lo: etree._Element,
    part_label: str,
    fallback_index: int,
) -> dict[str, Any]:
    """Parse a v2 <LayoutObject>."""
    obj_type = attr(lo, "type", "Type")
    obj_id = attr(lo, "id", "ID")
    obj_name = attr(lo, "name", "Name")
    obj_kind = attr(lo, "kind", "Kind") or None
    obj_uuid = _layout_uuid(lo)

    bounds = _parse_bounds(find_child(lo, "Bounds"))

    # Field reference (Edit Box, Drop Down, etc. with an associated field)
    field_info = _parse_field_block(find_child(lo, "Field"))

    # Plain text content for "Text" objects
    raw_text = _parse_text_content(find_child(lo, "Text"))

    return {
        "id": obj_id,
        "name": obj_name,
        "uuid": obj_uuid,
        "type": obj_type,
        "kind": obj_kind,
        "part": part_label or None,
        "bounds": bounds,
        "field": field_info,
        "raw_text": raw_text,
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
