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
            "paths": [text_of(p) for p in find_all_descendants(ds, "UniversalPathList") if text_of(p)],
        })
    return results
