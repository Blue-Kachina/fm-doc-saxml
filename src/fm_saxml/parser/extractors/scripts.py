"""Extract scripts and script steps from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import (
    attr, calc_text_of, find_all_children, find_all_descendants, find_child, modification_info, text_of, uuid_of,
    xml_path,
)
from .chunk_lists import chunk_refs_for, step_text_for


def extract_scripts(
    database_elem: etree._Element,
    v2_steps_elem: etree._Element | None = None,
    chunk_lists: dict[str, list[dict]] | None = None,
) -> list[dict[str, Any]]:
    """Return a list of raw script dicts (each containing their steps).

    ``chunk_lists`` (v2, from ``extract_chunk_lists``) supplies the resolved field /
    custom function references of each step calculation.
    """
    catalog = find_child(database_elem, "ScriptCatalog")
    if catalog is None:
        return []

    # Build script id → steps list from v2 StepsForScripts section
    steps_map: dict[str, list] = {}
    if v2_steps_elem is not None:
        for script_wrapper in find_all_descendants(v2_steps_elem, "Script"):
            sc_ref = find_child(script_wrapper, "ScriptReference")
            sc_id = attr(sc_ref, "id", "ID") if sc_ref is not None else ""
            if not sc_id:
                continue
            obj_list = find_child(script_wrapper, "ObjectList")
            steps = []
            if obj_list is not None:
                for idx, step_elem in enumerate(find_all_descendants(obj_list, "Step")):
                    steps.append(_parse_step(step_elem, idx, chunk_lists))
            steps_map[sc_id] = steps

    results = []
    _walk_script_folder(catalog, folder_path="", results=results, steps_map=steps_map)
    return results


def _walk_script_folder(
    elem: etree._Element,
    folder_path: str,
    results: list[dict[str, Any]],
    steps_map: dict[str, list] | None = None,
) -> None:
    """Recursively walk script folders, collecting scripts with their folder path.

    Folders and dividers are not scripts. In v2 exports the catalog is flat:
    ``<Script isFolder="True">`` opens a folder, the folder's items follow as
    siblings, and ``<Script isFolder="Marker">`` closes it. Dividers are
    ``<Script isSeparatorItem="True">``. Folders are tracked on a stack so
    real scripts still get a folder path.
    """
    open_folders: list[str] = []
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        local = _local(child.tag)
        if local == "Script":
            is_folder = attr(child, "isFolder", "IsFolder").lower()
            if attr(child, "isSeparatorItem", "IsSeparatorItem").lower() == "true":
                continue
            if is_folder == "marker":
                if open_folders:
                    open_folders.pop()
                continue
            if is_folder == "true":
                name = attr(child, "name", "Name")
                base = "/".join(p for p in [folder_path, *open_folders] if p)
                sub_path = f"{base}/{name}".lstrip("/")
                if any(_local(c.tag) == "Script" for c in child if isinstance(c.tag, str)):
                    _walk_script_folder(child, sub_path, results, steps_map)  # nested form
                else:
                    open_folders.append(name)
                continue
            path = "/".join(p for p in [folder_path, *open_folders] if p)
            results.append(_parse_script(child, path, steps_map or {}))
        elif local in ("ScriptFolder", "Folder", "Group"):
            folder_name = attr(child, "name", "Name")
            sub_path = f"{folder_path}/{folder_name}".lstrip("/")
            _walk_script_folder(child, sub_path, results, steps_map)


def _parse_script(elem: etree._Element, folder_path: str, steps_map: dict[str, list]) -> dict[str, Any]:
    sc_id = attr(elem, "id", "ID")

    # v1: steps live in a <StepList> child of the <Script> element
    # v2: steps come from the steps_map (StepsForScripts section)
    steps = steps_map.get(sc_id)
    if steps is None:
        step_list = find_child(elem, "StepList")
        steps = []
        if step_list is not None:
            for idx, step_elem in enumerate(find_all_descendants(step_list, "Step")):
                steps.append(_parse_step(step_elem, idx))

    return {
        "id": sc_id,
        "name": attr(elem, "name", "Name"),
        "uuid": uuid_of(elem),
        "folder_path": folder_path or None,
        "steps": steps,
        "options": _script_options(elem),
        "modified": modification_info(elem),
        "source_xml_path": xml_path(elem),
    }


def _script_options(elem: etree._Element) -> dict[str, Any] | None:
    """v2 ``<Options hidden="True" runwithfullaccess="False" SiriShortcutVisible="False" .../>`` on a script."""
    opts = find_child(elem, "Options")
    if opts is None or not attr(opts, "runwithfullaccess", "hidden"):
        return None

    def flag(name: str) -> bool | None:
        value = attr(opts, name)
        return value.lower() == "true" if value else None

    hidden = flag("hidden")
    return {
        "run_with_full_access": flag("runwithfullaccess"),
        "show_in_menu": None if hidden is None else not hidden,
        "siri_shortcut": flag("SiriShortcutVisible"),
    }


def _parse_step(
    elem: etree._Element,
    fallback_index: int,
    chunk_lists: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
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
    params: list[dict[str, Any]] = []
    if find_child(elem, "ParameterValues") is not None:
        # v2: references are nested in <ParameterValues><Parameter> as *Reference elements
        layout_ref, field_refs, script_ref, calcs, value_list_refs, calc_index = _extract_v2_step_refs(
            elem, chunk_lists)
        params = _step_params(elem, name, calc_index)
    else:
        layout_ref = _extract_layout_ref(elem)
        field_refs = _extract_field_refs(elem)
        script_ref = _extract_script_ref(elem)
        v1_calc = _extract_calculation(elem)
        calcs = [_calc_entry(v1_calc)] if v1_calc else []
        value_list_refs = []
    calc = "\n".join(c["text"] for c in calcs) or None

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
        "value_list_refs": value_list_refs,
        "calculation": calc,
        "calculations": calcs,
        "variable": _variable_name(elem),
        "params": params,
        # FileMaker's own text for the step (DDR_INFO StepText); preferred over ours when present
        "fm_text": step_text_for(elem, chunk_lists),
    }


def _variable_name(elem: etree._Element) -> str | None:
    """Set Variable's target, from v2 ``<Parameter type="Variable"><Name value="$x"/>``."""
    pv = find_child(elem, "ParameterValues")
    if pv is None:
        return None
    for param in find_all_children(pv, "Parameter"):
        if attr(param, "type", "Type") == "Variable":
            name = find_child(param, "Name")
            value = attr(name, "value", "Value") if name is not None else ""
            return value or None
    return None


def _calc_entry(
    text: str,
    position: int | None = None,
    parameter: str | None = None,
    slot: str | None = None,
    references: list[dict] | None = None,
) -> dict[str, Any]:
    """One calculated step parameter. ``references`` is None when it has no ChunkList."""
    return {"position": position, "parameter": parameter, "slot": slot,
            "text": text, "references": references}


def _extract_v2_step_refs(
    elem: etree._Element,
    chunk_lists: dict[str, list[dict]] | None = None,
) -> tuple[dict | None, list[dict], dict | None, list[dict], list[dict], dict]:
    """Pull layout / field / script / value-list references and calculations from a v2 step.

    In v2 a field reference's table half is a ``<TableOccurrenceReference>``
    child of ``<FieldReference>`` (i.e. a table *occurrence* name). The last item
    maps each calc's ``<Calculation>`` element to its index in the calcs list.
    """
    layout_ref = None
    script_ref = None
    field_refs: list[dict] = []
    value_list_refs: list[dict] = []
    calcs: list[dict] = []
    calc_index: dict[etree._Element, int] = {}

    for node in elem.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local(node.tag)
        name = attr(node, "name", "Name")
        if tag == "FieldReference" and name:
            to_ref = find_child(node, "TableOccurrenceReference")
            field_refs.append({
                "id": attr(node, "id", "ID"),
                "uuid": attr(node, "uuid", "UUID"),
                "name": name,
                "table": attr(to_ref, "name", "Name") if to_ref is not None else "",
                "table_id": attr(to_ref, "id", "ID") if to_ref is not None else "",
            })
        elif tag == "LayoutReference" and name and layout_ref is None:
            layout_ref = {"id": attr(node, "id", "ID"), "uuid": attr(node, "uuid", "UUID"),
                          "name": name, "via_to": _related_context_to(node)}
        elif tag == "ScriptReference" and name and script_ref is None:
            script_ref = {"id": attr(node, "id", "ID"), "uuid": attr(node, "uuid", "UUID"),
                          "name": name, "data_source": _sibling_data_source(node)}
        elif tag == "ValueListReference" and name:
            value_list_refs.append({"id": attr(node, "id", "ID"), "name": name})
        elif tag == "Calculation" and find_child(node, "Text") is not None:
            text = calc_text_of(node)
            if text:
                calc_index[node] = len(calcs)
                calcs.append(_v2_calc_entry(node, text, chunk_lists))

    return layout_ref, field_refs, script_ref, calcs, value_list_refs, calc_index


# ---------------------------------------------------------------------------
# Structured step parameters
# ---------------------------------------------------------------------------
#
# Each step gets an ordered ``params`` list describing what FileMaker's Script
# Workspace shows between the brackets. Items are small dicts keyed by ``kind``:
#
#   comment   {"text"}                    the comment step's text
#   calc      {"label", "calc"}           ``calc`` indexes the step's calculations
#   field     {"label", "name", "repetition"}   name is "TO::field"
#   variable  {"label", "name", "repetition"}   a variable the step assigns
#   script / layout / to / valueList / file / menuSet / privilegeSet   {"label", "name"}
#             (a script also has "dataSource": the other file it is in, or None)
#   option    {"label", "value"}          a setting: "With dialog: Off", "Animation: None"
#   text      {"label", "text"}           literal text: a path, Insert Text's text
#
# Calcs are referenced by index, not copied, so formatting the step after the
# calculations are scrubbed can only ever show scrubbed text.

_QUIET = {"Options", "Bounds", "SortSpecification", "ImportField", "Export", "FindRequestSet",
          "Send", "PageSetup", "Print"}
"""Containers whose settings are noise next to the step text: only calcs and references inside them are kept."""

_SKIP_BOOLEANS = {"Collapsed", "Commit"}  # editor state (If/Loop collapse); dialog button commit flag
_BOOLEAN_LABELS = {"Password": "Expire password"}  # Reset Account Password / Add Account

_LABELS = {
    "value": "Value", "Name": "Name", "Rename": "New Title", "Label": "Layout",
    "Parameter": "Parameter", "height": "Height", "width": "Width", "top": "Top", "left": "Left",
    "Start": "Start", "End": "End", "To": "To", "CC": "CC", "BCC": "BCC", "Subject": "Subject",
    "Message": "Message", "Title": "Title", "id": "File ID", "size": "Amount", "URL": "URL",
    "Password": "Password", "Install": "Install", "Location": None,
}
_UNLABELLED_PARAMS = {"Calculation", "None", "List", "Boolean", "Records", "Related", "Target",
                      "LayoutReferenceContainer", "FieldReference", "WindowReference", "Parameter"}


def _step_params(
    elem: etree._Element,
    step_name: str,
    calc_index: dict[etree._Element, int],
) -> list[dict[str, Any]]:
    """The step's parameters, in order, as structured items (see above)."""
    pv = find_child(elem, "ParameterValues")
    items: list[dict[str, Any]] = []
    if pv is None:
        return items
    for param in find_all_children(pv, "Parameter"):
        ptype = attr(param, "type", "Type")
        if ptype == "Comment":
            comment = find_child(param, "Comment")
            items.append({"kind": "comment", "text": attr(comment, "value") if comment is not None else ""})
        elif ptype == "Variable":  # Set Variable / Get Folder Path: the target, then its value
            name = find_child(param, "Name")
            items.append({"kind": "variable", "label": None,
                          "name": attr(name, "value", "Value") if name is not None else "",
                          "repetition": _calc_in(find_child(param, "repetition"), calc_index)})
            value = _calc_in(find_child(param, "value"), calc_index)
            if value is not None:
                items.append({"kind": "calc", "label": "Value", "calc": value})
        else:
            if ptype.startswith("Button") and attr(param, "value"):  # Show Custom Dialog
                items.append({"kind": "option", "label": f"Button {ptype[6:]}", "value": attr(param, "value")})
            label = None if ptype in _UNLABELLED_PARAMS else _LABELS.get(ptype, ptype)
            if step_name == "Loop" and ptype == "List":
                label = "Flush"
            start = len(items)
            _param_items(param, label, calc_index, items, quiet=False)
            if ptype == "Related":  # Go to Related Record: name the parts as FileMaker does
                _label_first(items, start, "to", "Get related record from")
                _label_first(items, start, "layout", "Using layout")
            elif ptype == "WindowReference":  # New Window
                _label_first(items, start, "layout", "Using layout")
    return _dedupe(items)


def _label_first(items: list[dict[str, Any]], start: int, kind: str, label: str) -> None:
    item = next((i for i in items[start:] if i["kind"] == kind and not i.get("label")), None)
    if item is not None:
        item["label"] = label


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeated references (a new window's layout repeats the step's own layout)."""
    seen: set[tuple] = set()
    out = []
    for item in items:
        if item["kind"] in ("layout", "to", "script", "valueList", "file"):
            key = (item["kind"], item.get("name"))
            if key in seen:
                continue
            seen.add(key)
        out.append(item)
    return out


def _calc_in(holder: etree._Element | None, calc_index: dict[etree._Element, int]) -> int | None:
    """Index of the calc held by ``holder`` (``<x><Calculation><Calculation><Text>``), if any."""
    if holder is None:
        return None
    outer = find_child(holder, "Calculation")
    if outer is None:
        return None
    inner = find_child(outer, "Calculation")
    return calc_index.get(inner if inner is not None else outer)


def _param_items(
    node: etree._Element,
    label: str | None,
    calc_index: dict[etree._Element, int],
    items: list[dict[str, Any]],
    quiet: bool,
) -> None:
    """Describe ``node``'s children. ``label`` names a calc held directly by ``node``."""
    for child in node:
        if not isinstance(child.tag, str):
            continue
        tag = _local(child.tag)
        name = attr(child, "name", "Name")
        if tag == "Calculation":
            inner = find_child(child, "Calculation")
            idx = calc_index.get(inner if inner is not None else child)
            if idx is not None:
                items.append({"kind": "calc", "label": label, "calc": idx})
        elif tag == "FieldReference":
            to_ref = find_child(child, "TableOccurrenceReference")
            to_name = attr(to_ref, "name", "Name") if to_ref is not None else ""
            items.append({"kind": "field", "label": label if label != "Value" else None,
                          "name": f"{to_name}::{name}" if to_name else name,
                          "repetition": _calc_in(find_child(child, "repetition"), calc_index)})
        elif tag == "Variable":  # a Target: Insert from URL, Insert Calculated Result, ...
            items.append({"kind": "variable", "label": "Target",
                          "name": attr(child, "value", "Value"),
                          "repetition": _calc_in(find_child(child, "repetition"), calc_index)})
        elif tag in _REF_KINDS:
            kind = _REF_KINDS[tag]
            if name:
                item: dict[str, Any] = {"kind": kind, "label": None, "name": name}
                if kind == "script":
                    item["dataSource"] = _sibling_data_source(child)
                items.append(item)
            _param_items(child, None, calc_index, items, quiet)
        elif tag == "DataSourceReference":
            if name:
                items.append({"kind": "file", "label": None, "name": name})
            _param_items(child, None, calc_index, items, quiet)
        elif tag in ("UUID", "DDRREF"):
            continue
        elif tag == "repetition":
            # Install OnTimer Script keeps its script parameter here; elsewhere it is an
            # object's repetition (Go to Object). Field and variable repetitions are read above.
            rep_label = "Parameter" if _local(node.tag) == "ScriptReference" else "Repetition"
            _param_items(child, rep_label, calc_index, items, quiet)
        elif tag == "LayoutReferenceContainer" and len(child) == 0:
            continue  # no layout chosen: the current one
        elif quiet or tag in _QUIET:
            _param_items(child, _LABELS.get(tag), calc_index, items, quiet=True)
        elif tag == "Boolean":
            btype = attr(child, "type", "Type")
            if btype not in _SKIP_BOOLEANS:
                on = attr(child, "value", "Value").lower() == "true"
                items.append({"kind": "option", "label": _BOOLEAN_LABELS.get(btype, btype) or None,
                              "value": "On" if on else "Off"})
            _param_items(child, btype or label, calc_index, items, quiet)
        elif tag == "List":
            name = name.rstrip(": ")
            has_calc = find_child(child, "Calculation") is not None
            if has_calc:  # e.g. Perform Script "By name": the calc is the script name
                _param_items(child, name or label, calc_index, items, quiet)
                continue
            if name and not (name == "From list" and find_child(child, "ScriptReference") is not None):
                items.append({"kind": "option", "label": label, "value": name})
            _param_items(child, None, calc_index, items, quiet)
        elif tag == "Animation":
            items.append({"kind": "option", "label": "Animation", "value": name})
        elif tag == "Restore":
            if attr(child, "value", "Value").lower() == "true":
                items.append({"kind": "option", "label": None, "value": "Restore"})
        elif tag == "Style":
            items.append({"kind": "option", "label": "Style", "value": name})
        elif tag == "Select" and attr(child, "type", "Type"):  # WindowReference
            wtype = attr(child, "type", "Type")
            if wtype.lower() == "current":
                items.append({"kind": "option", "label": None, "value": "Current Window"})
            _param_items(child, "Window name", calc_index, items, quiet)
        elif len(child) == 0 and (child.text or "").strip():
            items.append({"kind": "text", "label": _LABELS.get(tag, tag), "text": child.text.strip()})
        elif len(child) == 0 and (name or attr(child, "value", "Value")):
            items.append({"kind": "option", "label": _LABELS.get(tag, tag), "value": name or attr(child, "value")})
        else:
            _param_items(child, _LABELS.get(tag, tag), calc_index, items, quiet)


_REF_KINDS = {
    "ScriptReference": "script", "LayoutReference": "layout", "TableOccurrenceReference": "to",
    "ValueListReference": "valueList", "CustomMenuSetReference": "menuSet",
    "PrivilegeSetReference": "privilegeSet",
}


def _v2_calc_entry(
    calc: etree._Element,
    text: str,
    chunk_lists: dict[str, list[dict]] | None,
) -> dict[str, Any]:
    """Describe where a step calculation sits, plus the references from its ChunkList.

    Structure: ``<Parameter type="Variable"><value><Calculation position="1"><Calculation>
    <DDRREF kind="ChunkList">key</DDRREF><Text/>``. ``slot`` is the element holding the
    calc inside its parameter (``value``, ``repetition``, ``top`` ...), or None when the
    calc is the parameter itself.
    """
    outer = calc.getparent()
    if outer is not None and _local(outer.tag) == "Calculation":
        holder = outer.getparent()
        position = attr(outer, "position")
    else:
        holder, position = outer, ""
    slot = _local(holder.tag) if holder is not None else None
    param = next((a for a in calc.iterancestors()
                  if isinstance(a.tag, str) and _local(a.tag) == "Parameter"), None)

    return _calc_entry(
        text,
        position=int(position) if position.isdigit() else None,
        parameter=(attr(param, "type", "Type") or None) if param is not None else None,
        slot=None if slot == "Parameter" else slot,
        references=chunk_refs_for(calc, chunk_lists),
    )


def _sibling_data_source(script_ref: etree._Element) -> str | None:
    """File name from a ``<DataSourceReference>`` beside a ScriptReference (Perform Script "from file").

    "Current File" (id 0) means the script is local.
    """
    parent = script_ref.getparent()
    ds = find_child(parent, "DataSourceReference") if parent is not None else None
    if ds is None:
        return None
    name = attr(ds, "name", "Name")
    if not name or name == "Current File" or attr(ds, "id", "ID") in ("", "0"):
        return None
    return name


def _related_context_to(layout_ref: etree._Element) -> str | None:
    """TO name given as the context of a "Go to Related Record" step, if the layout ref belongs to one.

    Structure: ``<Parameter type="Related"><TableOccurrenceReference/><LayoutReferenceContainer><LayoutReference/>``
    """
    container = layout_ref.getparent()
    param = container.getparent() if container is not None else None
    if param is None or attr(param, "type", "Type") != "Related":
        return None
    to_ref = find_child(param, "TableOccurrenceReference")
    return attr(to_ref, "name", "Name") if to_ref is not None else None


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
