"""Extract custom functions from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children, find_all_descendants, calc_text_of, xml_path, modification_info
from .chunk_lists import ChunkLists, calc_entry


def extract_custom_functions(
    database_elem: etree._Element,
    v2_calcs_elem: etree._Element | None = None,
    chunk_lists: ChunkLists | None = None,
) -> list[dict[str, Any]]:
    # v2 uses CustomFunctionsCatalog (with 's'); v1 uses CustomFunctionCatalog
    catalog = find_child(database_elem, "CustomFunctionCatalog", "CustomFunctionsCatalog")
    if catalog is None:
        return []

    # Build id→calc map from v2 CalcsForCustomFunctions section if present
    calc_map: dict[str, dict] = {}
    if v2_calcs_elem is not None:
        for obj_list in find_all_children(v2_calcs_elem, "ObjectList"):
            for cf_calc in find_all_children(obj_list, "CustomFunctionCalc"):
                cf_ref = find_child(cf_calc, "CustomFunctionReference")
                cf_id = attr(cf_ref, "id", "ID") if cf_ref is not None else ""
                calc_elem = find_child(cf_calc, "Calculation")
                entry = calc_entry(calc_elem, "calculation", chunk_lists) if calc_elem is not None else None
                if cf_id and entry:
                    calc_map[cf_id] = entry

    results = []
    # v2 wraps custom functions in an <ObjectList>
    obj_list = find_child(catalog, "ObjectList")
    cf_elems = find_all_children(obj_list, "CustomFunction") if obj_list is not None else []
    if not cf_elems:
        cf_elems = find_all_descendants(catalog, "CustomFunction")

    for cf_elem in cf_elems:
        results.append(_parse_cf(cf_elem, calc_map))
    return results


def _parse_cf(elem: etree._Element, calc_map: dict[str, dict]) -> dict[str, Any]:
    cf_id = attr(elem, "id", "ID")

    # Parameters may be semicolon-separated string or child elements
    params_raw = attr(elem, "parameters", "Parameters", "pramaters") or ""
    if params_raw:
        params = [p.strip() for p in params_raw.replace(";", ",").split(",") if p.strip()]
    else:
        # v2: <ObjectList><Parameter name="...">
        obj_list = find_child(elem, "ObjectList")
        param_container = obj_list if obj_list is not None else elem
        params = [
            attr(p, "name", "Name")
            for p in find_all_descendants(param_container, "Parameter")
            if attr(p, "name", "Name")
        ]

    calc_elem = find_child(elem, "Calculation")
    v2_entry = calc_map.get(cf_id)
    calculation = calc_text_of(calc_elem) or (v2_entry["text"] if v2_entry else None)

    return {
        "id": cf_id,
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "parameters": params,
        "calculation": calculation,
        "calculations": [v2_entry] if v2_entry else [],
        "modified": modification_info(elem),
        "source_xml_path": xml_path(elem),
    }
