"""Extract accounts from FileMaker SaveAsXML."""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_descendants, text_of, xml_path


def extract_accounts(container: etree._Element) -> list[dict[str, Any]]:
    catalog = find_child(container, "AccountsCatalog")
    if catalog is None:
        return []

    results = []
    for acct_elem in find_all_descendants(catalog, "Account"):
        # AccountName may be a direct child or nested under <Authentication>
        name_elem = find_child(acct_elem, "AccountName")
        if name_elem is None:
            auth_elem = find_child(acct_elem, "Authentication")
            if auth_elem is not None:
                name_elem = find_child(auth_elem, "AccountName")
        name = text_of(name_elem) if name_elem is not None else attr(acct_elem, "name", "Name")

        ps_ref = find_child(acct_elem, "PrivilegeSetReference")
        privilege_set_id = attr(ps_ref, "id", "ID") if ps_ref is not None else None
        privilege_set_name = attr(ps_ref, "name", "Name") if ps_ref is not None else None

        desc_elem = find_child(acct_elem, "Description")
        description = text_of(desc_elem) or attr(acct_elem, "description", "Description") or None

        enabled_str = attr(acct_elem, "enable", "Enable", "enabled", default="True")
        enabled = enabled_str.lower() not in ("false", "0", "no")

        results.append({
            "id": attr(acct_elem, "id", "ID"),
            "name": name,
            "account_type": attr(acct_elem, "type", "Type", default="FileMaker"),
            "enabled": enabled,
            "description": description or None,
            "privilege_set_id": privilege_set_id,
            "privilege_set_name": privilege_set_name,
            "source_xml_path": xml_path(acct_elem),
        })
    return results
