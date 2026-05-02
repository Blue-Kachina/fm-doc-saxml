"""Extract custom functions from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children, find_all_descendants, calc_text_of, xml_path


def extract_custom_functions(
    database_elem: etree._Element,
    v2_calcs_elem: etree._Element | None = None,
) -> list[dict[str, Any]]:
    # v2 uses CustomFunctionsCatalog (with 's'); v1 uses CustomFunctionCatalog
    catalog = find_child(database_elem, "CustomFunctionCatalog", "CustomFunctionsCatalog")
    if catalog is None:
        return []

    # Build id→calc map from v2 CalcsForCustomFunctions section if present
    calc_map: dict[str, str] = {}
    if v2_calcs_elem is not None:
        for obj_list in find_all_children(v2_calcs_elem, "ObjectList"):
            for cf_calc in find_all_children(obj_list, "CustomFunctionCalc"):
                cf_ref = find_child(cf_calc, "CustomFunctionReference")
                cf_id = attr(cf_ref, "id", "ID") if cf_ref is not None else ""
                calc_elem = find_child(cf_calc, "Calculation")
                calc_text = calc_text_of(calc_elem)
                if cf_id and calc_text:
                    calc_map[cf_id] = calc_text

    results = []
    # v2 wraps custom functions in an <ObjectList>
    obj_list = find_child(catalog, "ObjectList")
    cf_elems = find_all_children(obj_list, "CustomFunction") if obj_list is not None else []
    if not cf_elems:
        cf_elems = find_all_descendants(catalog, "CustomFunction")

    for cf_elem in cf_elems:
        results.append(_parse_cf(cf_elem, calc_map))
    return results


def _parse_cf(elem: etree._Element, calc_map: dict[str, str]) -> dict[str, Any]:
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
    calculation = calc_text_of(calc_elem) or calc_map.get(cf_id) or None

    return {
        "id": cf_id,
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "parameters": params,
        "calculation": calculation,
        "source_xml_path": xml_path(elem),
    }
