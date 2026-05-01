"""Extract custom functions from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_custom_functions(database_elem: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(database_elem, "CustomFunctionCatalog")
    if catalog is None:
        return []

    results = []
    for cf_elem in find_all_descendants(catalog, "CustomFunction"):
        results.append(_parse_cf(cf_elem))
    return results


def _parse_cf(elem: etree._Element) -> dict[str, Any]:
    # Parameters may be semicolon-separated string or child elements
    params_raw = attr(elem, "parameters", "Parameters", "pramaters") or ""
    if params_raw:
        params = [p.strip() for p in params_raw.replace(";", ",").split(",") if p.strip()]
    else:
        params = [attr(p, "name", "Name") for p in find_all_descendants(elem, "Parameter") if attr(p, "name", "Name")]

    calc_elem = find_child(elem, "Calculation")

    return {
        "id": attr(elem, "id", "ID"),
        "name": attr(elem, "name", "Name"),
        "uuid": attr(elem, "uuid", "UUID") or None,
        "parameters": params,
        "calculation": text_of(calc_elem) or None,
        "source_xml_path": xml_path(elem),
    }
