"""Extract the External Data Sources catalog (the other files this file reaches into)."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of


def extract_external_data_sources(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "ExternalDataSourceCatalog")
    if catalog is None:
        return []
    results = []
    for ds in find_all_descendants(catalog, "ExternalDataSource"):
        uuid_elem = find_child(ds, "UUID")
        results.append({
            "name": attr(ds, "name", "Name"),
            "id": attr(ds, "id", "ID"),
            "uuid": text_of(uuid_elem) or None,
            "type": attr(ds, "type", "Type") or "FileMaker",
            "paths": [path for pl in find_all_descendants(ds, "UniversalPathList") for path in _paths(pl)],
        })
    return results


def _paths(path_list: etree._Element) -> list[str]:
    """One entry per path. FileMaker tries them in order; they come either as lines of the
    element's text (``file:afile:b``) or as ``<ObjectList><Location>`` children."""
    locations = find_all_descendants(path_list, "Location")
    lines = [text_of(loc) for loc in locations] if locations else (path_list.text or "").splitlines()
    return [line.strip() for line in lines if line.strip()]
