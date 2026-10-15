"""Effective access: what each privilege set can do with each script, layout, value list and table.

FileMaker stores a privilege set's access per category, either as one setting for the
whole category (``<Scripts View="ReadOnly"/>``: all executable only) or as a custom list
with one row per object plus a row for objects created later (``type="New"``, kept with
``targetDocId`` None). Working out "who can run script X" means applying those rules,
which is easy to get wrong by hand, so it is done once here and every answer carries the
reason it was reached:

- ``fullAccess``: the built-in [Full Access] set
- ``blanket``: one setting for the whole category
- ``customRow``: the object's own row in a custom list
- ``newFallback``: no row of its own, so the "[Any new ...]" row applies
- ``notListed``: a custom list with neither (treated as no access)

Accounts are attached to their set. External accounts are groups in an identity
provider, not people, and disabled accounts can't sign in; both are flagged, not dropped.
"""

from __future__ import annotations

from typing import Any, Optional

from ..model.document_model import DocumentModel
from ..model.entities import PrivilegeCategory, PrivilegeItem, PrivilegeSetEntity

FULL_ACCESS = "[Full Access]"

# A custom row's access value -> level, per kind of object.
_SCRIPT_LEVELS = {"ReadWrite": "modifiable", "ReadOnly": "executable", "NoAccess": "none"}
_LAYOUT_LEVELS = {"ReadWrite": "modifiable", "ReadOnly": "view", "NoAccess": "none"}
_RECORD_ACTIONS = ("View", "Edit", "Create", "Delete")


def build_access(model: DocumentModel) -> dict[str, Any]:
    """Every privilege set's effective access to every script, layout, value list and table.

    ``objects[kind][docId]`` is a list of rows, one per privilege set:
    ``script``/``valueList``: ``[setDocId, level, reason]``;
    ``layout``: ``[setDocId, level, recordsLevel, reason]`` (recordsLevel ``None`` = the
    record privileges decide); ``table``: ``[setDocId, {view, edit, create, delete}, reason,
    {action: calc}]`` where each action is ``yes``, ``no`` or ``limited`` (by the calc).
    """
    em = model.entities
    sets = list(em.privilege_sets.values())
    accounts: dict[str, list[dict[str, Any]]] = {}
    for a in em.accounts.values():
        if a.privilege_set_doc_id:
            accounts.setdefault(a.privilege_set_doc_id, []).append({
                "docId": a.doc_id, "name": a.name, "enabled": a.enabled, "accountType": a.account_type,
                "external": a.account_type != "FileMaker",
            })
    ext_privs: dict[str, list[str]] = {}
    for x in em.extended_privileges.values():
        for ps in x.privilege_set_doc_ids:
            ext_privs.setdefault(ps, []).append(x.name)

    return {
        "sets": {
            ps.doc_id: {
                "name": ps.name,
                "builtIn": ps.built_in,
                "fullAccess": _is_full_access(ps),
                "accounts": accounts.get(ps.doc_id, []),
                "extendedPrivileges": sorted(ext_privs.get(ps.doc_id, [])),
                "summary": {key: cat.summary for key, cat in _categories(ps) if cat is not None},
                "other": ps.other,
            }
            for ps in sets
        },
        "objects": {
            "script": {d: [[ps.doc_id, *_leveled(ps, ps.scripts, d, _SCRIPT_LEVELS, "executable")]
                           for ps in sets] for d in em.scripts},
            "layout": {d: [[ps.doc_id, *_layout(ps, d)] for ps in sets] for d in em.layouts},
            "valueList": {d: [[ps.doc_id, *_leveled(ps, ps.value_lists, d, _LAYOUT_LEVELS, "view")]
                              for ps in sets] for d in em.value_lists},
            "table": {d: [[ps.doc_id, *_records(ps, d)] for ps in sets] for d in em.tables},
        },
    }


def _is_full_access(ps: PrivilegeSetEntity) -> bool:
    # FileMaker reserves the name, and some exports leave out the set's access details.
    return ps.name == FULL_ACCESS


def _categories(ps: PrivilegeSetEntity):
    return (("records", ps.records), ("layouts", ps.layouts), ("valueLists", ps.value_lists),
            ("scripts", ps.scripts))


def _row(category: PrivilegeCategory, doc_id: str) -> tuple[Optional[PrivilegeItem], str]:
    """The custom-list row that governs ``doc_id``, and why."""
    rows = category.custom or []
    own = next((r for r in rows if r.target_doc_id == doc_id), None)
    if own is not None:
        return own, "customRow"
    new = next((r for r in rows if r.target_doc_id is None), None)
    if new is not None:
        return new, "newFallback"
    return None, "notListed"


def _blanket_level(settings: dict[str, str], view_level: str) -> str:
    """``Create/Edit/Delete="True"``: modifiable; ``View="ReadOnly"``: view/executable only; else none."""
    if any(settings.get(k) == "True" for k in ("Create", "Edit", "Delete")):
        return "modifiable"
    if settings.get("View") in ("ReadOnly", "ReadWrite"):
        return view_level
    return "none"


def _row_value(row: PrivilegeItem, key: str = "access") -> Optional[str]:
    return row.attributes.get(key) or row.access.get(key) or row.access.get("View")


def _leveled(ps: PrivilegeSetEntity, category: Optional[PrivilegeCategory], doc_id: str,
             levels: dict[str, str], view_level: str) -> list[Any]:
    if _is_full_access(ps):
        return ["modifiable", "fullAccess"]
    if category is None:
        return ["none", "blanket"]
    if category.custom is None:
        return [_blanket_level(category.settings, view_level), "blanket"]
    row, reason = _row(category, doc_id)
    if row is None:
        return ["none", reason]
    return [levels.get(_row_value(row) or "", "none"), reason]


def _layout(ps: PrivilegeSetEntity, doc_id: str) -> list[Any]:
    if _is_full_access(ps):
        return ["modifiable", "modifiable", "fullAccess"]
    category = ps.layouts
    if category is None:
        return ["none", None, "blanket"]
    if category.custom is None:
        return [_blanket_level(category.settings, "view"), None, "blanket"]
    row, reason = _row(category, doc_id)
    if row is None:
        return ["none", "none", reason]
    records = row.attributes.get("records")
    return [_LAYOUT_LEVELS.get(_row_value(row) or "", "none"),
            _LAYOUT_LEVELS.get(records) if records else None, reason]


def _records(ps: PrivilegeSetEntity, doc_id: str) -> list[Any]:
    yes_all = {"view": "yes", "edit": "yes", "create": "yes", "delete": "yes"}
    if _is_full_access(ps):
        return [yes_all, "fullAccess", {}]
    category = ps.records
    if category is None:
        return [dict.fromkeys(yes_all, "no"), "blanket", {}]
    if category.custom is None:
        s = category.settings
        actions = {a.lower(): ("yes" if s.get(a) == "True" else "no") for a in ("Edit", "Create", "Delete")}
        viewable = s.get("View") in ("ReadOnly", "ReadWrite") or "yes" in actions.values()
        return [{"view": "yes" if viewable else "no", **actions}, "blanket", {}]
    row, reason = _row(category, doc_id)
    if row is None:
        return [dict.fromkeys(yes_all, "no"), reason, {}]
    calcs = {c.role.lower(): c.text for c in row.calculations}
    out = {}
    for action in _RECORD_ACTIONS:
        value = row.access.get(action)
        out[action.lower()] = ("limited" if value == "Calculation" else
                               "yes" if value in ("ReadWrite", "ReadOnly") else "no")
    return [out, reason, {k: v for k, v in calcs.items() if out.get(k) == "limited"}]
