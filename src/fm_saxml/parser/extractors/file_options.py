"""Extract File Options from the root ``<Metadata>`` block of v2 SaveAsXML.

    <Metadata><AddAction>
        <Minimum version="17.0" value="1700"/>
        <Login type="-1"/>
        <Defaults><LayoutReference id="2" name="Contrat - Liste"/></Defaults>
        <ScriptTriggers><ScriptTrigger action="OnFirstWindowOpen"><ScriptReference/></ScriptTrigger></ScriptTriggers>
        ...
    </AddAction></Metadata>

The block's ``IconData`` (the file icon) and ``PageSetup`` are left out: binary or
print-only data an analysis has no use for.
"""

from __future__ import annotations

from typing import Any
from lxml import etree

from ._helpers import attr, find_child, find_all_children


def extract_file_options(root: etree._Element) -> dict[str, Any] | None:
    """File Options of the file, or None when the export has no ``Metadata`` block."""
    metadata = find_child(root, "Metadata")
    container = find_child(metadata, "AddAction") if metadata is not None else None
    if container is None:
        return None

    def enabled(tag: str, name: str = "enable") -> bool | None:
        elem = find_child(container, tag)
        if elem is None or not attr(elem, name):
            return None
        return attr(elem, name).lower() == "true"

    defaults = find_child(container, "Defaults")
    layout_ref = find_child(defaults, "LayoutReference") if defaults is not None else None
    minimum = find_child(container, "Minimum")
    login = find_child(container, "Login")
    account_ref = find_child(login, "AccountReference") if login is not None else None
    encryption = find_child(container, "Encryption")
    save_password = find_child(container, "SavePassword")

    triggers = []
    trig_list = find_child(container, "ScriptTriggers")
    for trig in find_all_children(trig_list, "ScriptTrigger") if trig_list is not None else []:
        script_ref = find_child(trig, "ScriptReference")
        if script_ref is None or not attr(script_ref, "name", "Name"):
            continue
        triggers.append({
            "event": attr(trig, "action", "Action"),
            "script": {
                "id": attr(script_ref, "id", "ID"),
                "uuid": attr(script_ref, "uuid", "UUID"),
                "name": attr(script_ref, "name", "Name"),
                "data_source": None,
            },
        })

    return {
        "default_layout": (
            {"id": attr(layout_ref, "id", "ID"), "name": attr(layout_ref, "name", "Name")}
            if layout_ref is not None and attr(layout_ref, "name", "Name") else None
        ),
        "minimum_version": attr(minimum, "version") or None if minimum is not None else None,
        # Only the account's name: a stored login password must never reach the output.
        "login_type": attr(login, "type") or None if login is not None else None,
        "login_account": attr(account_ref, "name", "Name") or None if account_ref is not None else None,
        "encrypted": (attr(encryption, "type") not in ("", "0")) if encryption is not None else None,
        "allow_save_password": (
            attr(save_password, "keychain").lower() == "true"
            if save_password is not None and attr(save_password, "keychain") else None
        ),
        "require_mobile_password": (
            attr(save_password, "requireMobile").lower() == "true"
            if save_password is not None and attr(save_password, "requireMobile") else None
        ),
        "show_sign_in_fields": enabled("ShowSignInFields"),
        "hide_from_client_sharing": enabled("HideClientSharing"),
        "hide_from_webdirect_sharing": enabled("HideWebDirectSharing"),
        "use_default_fields": enabled("UseDefaultFields"),
        "script_triggers": triggers,
    }
