"""Structural diff between two parsed FileMaker solution snapshots.

Every entity's ``docId`` is derived from stable, name-based keys (see
``normalize/ids.py``) rather than from FileMaker's internal numeric/UUID
identifiers, so the *same* table, field, script, etc. gets the *same*
``docId`` across two independent exports of the same solution as long as it
wasn't renamed. That's what makes a docId-keyed set diff meaningful here.

``script_steps`` is the one exception: its docId is positional
(``script + index``), so inserting or removing a step near the start of a
script would otherwise show as a wall of unrelated added/removed steps.
Script step changes are instead summarized per-script with a content-based
(position-tolerant) comparison — see ``_diff_script_steps``.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field as dc_field
from typing import Any, Optional

from ..model.document_model import DocumentModel

# (EntityMaps field name, entityType tag, human label). Order controls
# report/section order. script_steps is intentionally excluded — see module
# docstring. The entityType tags mirror each Entity class's `entity_type`
# default in model/entities.py.
_ENTITY_TYPES: list[tuple[str, str, str]] = [
    ("tables", "table", "Tables"),
    ("fields", "field", "Fields"),
    ("table_occurrences", "tableOccurrence", "Table Occurrences"),
    ("relationships", "relationship", "Relationships"),
    ("layouts", "layout", "Layouts"),
    ("layout_objects", "layoutObject", "Layout Objects"),
    ("scripts", "script", "Scripts"),
    ("custom_functions", "customFunction", "Custom Functions"),
    ("value_lists", "valueList", "Value Lists"),
    ("privilege_sets", "privilegeSet", "Privilege Sets"),
    ("accounts", "account", "Accounts"),
    ("extended_privileges", "extPriv", "Extended Privileges"),
    ("custom_menus", "customMenu", "Custom Menus"),
    ("custom_menu_sets", "customMenuSet", "Custom Menu Sets"),
    ("themes", "theme", "Themes"),
    ("file_references", "fileRef", "File References"),
]

# Fields excluded from change detection: volatile position/debug metadata
# that says nothing about the solution's actual content.
_IGNORED_FIELDS = {"source_xml", "doc_id"}


@dataclass
class FieldChange:
    field: str
    old: str
    new: str


@dataclass
class EntitySummary:
    doc_id: str
    entity_type: str
    name: str


@dataclass
class EntityChange:
    doc_id: str
    entity_type: str
    name: str
    changes: list[FieldChange]


@dataclass
class StepDiff:
    """Content-based (position-tolerant) diff of one script's step list."""
    script_doc_id: str
    script_name: str
    old_count: int
    new_count: int
    added: int
    removed: int


@dataclass
class TypeDiff:
    entity_type: str
    label: str
    added: list[EntitySummary] = dc_field(default_factory=list)
    removed: list[EntitySummary] = dc_field(default_factory=list)
    changed: list[EntityChange] = dc_field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


@dataclass
class DiffResult:
    old_source: str
    new_source: str
    types: list[TypeDiff]
    script_step_diffs: list[StepDiff]

    @property
    def total_added(self) -> int:
        return sum(len(t.added) for t in self.types)

    @property
    def total_removed(self) -> int:
        return sum(len(t.removed) for t in self.types)

    @property
    def total_changed(self) -> int:
        return sum(len(t.changed) for t in self.types)

    @property
    def has_changes(self) -> bool:
        return (
            self.total_added > 0
            or self.total_removed > 0
            or self.total_changed > 0
            or bool(self.script_step_diffs)
        )


def compute_diff(old: DocumentModel, new: DocumentModel) -> DiffResult:
    """Compare two normalized+resolved DocumentModels entity-by-entity."""
    types = [
        _diff_entity_map(
            entity_type, label,
            getattr(old.entities, field_name),
            getattr(new.entities, field_name),
        )
        for field_name, entity_type, label in _ENTITY_TYPES
    ]
    return DiffResult(
        old_source=old.source.file_name,
        new_source=new.source.file_name,
        types=types,
        script_step_diffs=_diff_script_steps(old, new),
    )


def _diff_entity_map(entity_type: str, label: str, old_map: dict[str, Any], new_map: dict[str, Any]) -> TypeDiff:
    old_keys, new_keys = set(old_map), set(new_map)

    added = sorted(
        (_summary(new_map[k]) for k in new_keys - old_keys),
        key=lambda s: s.name,
    )
    removed = sorted(
        (_summary(old_map[k]) for k in old_keys - new_keys),
        key=lambda s: s.name,
    )

    changed: list[EntityChange] = []
    for k in old_keys & new_keys:
        field_changes = _diff_fields(old_map[k], new_map[k])
        if field_changes:
            changed.append(EntityChange(
                doc_id=k,
                entity_type=entity_type,
                name=_name_of(new_map[k]),
                changes=field_changes,
            ))
    changed.sort(key=lambda c: c.name)

    return TypeDiff(entity_type=entity_type, label=label, added=added, removed=removed, changed=changed)


def _diff_fields(old_entity: Any, new_entity: Any) -> list[FieldChange]:
    old_dump = old_entity.model_dump(exclude=_IGNORED_FIELDS)
    new_dump = new_entity.model_dump(exclude=_IGNORED_FIELDS)
    changes: list[FieldChange] = []
    for key in sorted(set(old_dump) | set(new_dump)):
        ov, nv = old_dump.get(key), new_dump.get(key)
        if isinstance(ov, list) and isinstance(nv, list):
            old_set, new_set = {str(x) for x in ov}, {str(x) for x in nv}
            if old_set == new_set:
                continue
            added_n, removed_n = len(new_set - old_set), len(old_set - new_set)
            changes.append(FieldChange(
                field=key,
                old=f"{len(ov)} item(s)",
                new=f"{len(nv)} item(s) (+{added_n}/-{removed_n})",
            ))
            continue
        if ov == nv:
            continue
        changes.append(FieldChange(field=key, old=_fmt(ov), new=_fmt(nv)))
    return changes


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return f"{len(v)} item(s)"
    if isinstance(v, dict):
        parts = ", ".join(f"{k}={_fmt(val)}" for k, val in sorted(v.items()))
        s = "{" + parts + "}"
        return s if len(s) <= 100 else s[:97] + "..."
    s = str(v)
    return s if len(s) <= 100 else s[:97] + "..."


def _name_of(entity: Any) -> str:
    qn = getattr(entity, "qualified_name", None)
    if qn:
        return qn
    return getattr(entity, "name", None) or getattr(entity, "doc_id", "")


def _summary(entity: Any) -> EntitySummary:
    return EntitySummary(doc_id=entity.doc_id, entity_type=entity.entity_type, name=_name_of(entity))


def _diff_script_steps(old: DocumentModel, new: DocumentModel) -> list[StepDiff]:
    diffs: list[StepDiff] = []
    old_scripts, new_scripts = old.entities.scripts, new.entities.scripts
    for doc_id in sorted(set(old_scripts) & set(new_scripts)):
        old_script, new_script = old_scripts[doc_id], new_scripts[doc_id]
        old_sigs = [_step_signature(old.entities.script_steps.get(sid)) for sid in old_script.steps]
        new_sigs = [_step_signature(new.entities.script_steps.get(sid)) for sid in new_script.steps]
        if old_sigs == new_sigs:
            continue

        sm = difflib.SequenceMatcher(a=old_sigs, b=new_sigs, autojunk=False)
        added = removed = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "insert":
                added += j2 - j1
            elif tag == "delete":
                removed += i2 - i1
            elif tag == "replace":
                removed += i2 - i1
                added += j2 - j1

        diffs.append(StepDiff(
            script_doc_id=doc_id,
            script_name=new_script.name,
            old_count=len(old_sigs),
            new_count=len(new_sigs),
            added=added,
            removed=removed,
        ))
    diffs.sort(key=lambda d: d.script_name)
    return diffs


def _step_signature(step: Optional[Any]) -> str:
    if step is None:
        return ""
    return f"{step.name}|{step.enabled}|{step.raw_text or ''}"
