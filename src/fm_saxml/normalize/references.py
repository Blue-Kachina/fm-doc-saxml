"""Resolve references between entities — builds the references list and enriches entities."""

from __future__ import annotations

from typing import Any

from ..model.document_model import DocumentModel
from ..model.references import ReferenceRecord
from .external import ExternalTargets
from .ids import (
    field_doc_id,
    layout_doc_id,
    script_doc_id,
    to_doc_id,
    custom_function_doc_id,
    value_list_doc_id,
)


def resolve_references(model: DocumentModel) -> DocumentModel:
    """Populate model.references by resolving entity cross-references."""
    _link_fields_to_tables(model)
    _link_tos_to_tables(model)
    _link_relationships(model)
    _link_layouts(model)
    _link_layout_objects(model)
    _link_scripts(model)
    _link_custom_functions(model)
    _link_value_lists(model)
    _link_custom_menus(model)
    _link_field_calculations(model)
    _link_accounts_to_privilege_sets(model)
    _link_extended_privileges_to_privilege_sets(model)
    return model


# ---------------------------------------------------------------------------
# Field → Table
# ---------------------------------------------------------------------------

def _link_fields_to_tables(model: DocumentModel) -> None:
    for field in model.entities.fields.values():
        if field.base_table_doc_id in model.entities.tables:
            model.references.append(ReferenceRecord(
                sourceDocId=field.base_table_doc_id,
                sourceEntityType="table",
                targetDocId=field.doc_id,
                targetEntityType="field",
                relationshipType="contains",
                confidence="exact",
            ))


# ---------------------------------------------------------------------------
# Table Occurrence → Base Table
# ---------------------------------------------------------------------------

def _link_tos_to_tables(model: DocumentModel) -> None:
    for to in model.entities.table_occurrences.values():
        if to.base_table_doc_id in model.entities.tables:
            model.references.append(ReferenceRecord(
                sourceDocId=to.doc_id,
                sourceEntityType="tableOccurrence",
                targetDocId=to.base_table_doc_id,
                targetEntityType="table",
                relationshipType="basedOnBaseTable",
                confidence="exact",
            ))


# ---------------------------------------------------------------------------
# Relationship predicates
# ---------------------------------------------------------------------------

def _link_relationships(model: DocumentModel) -> None:
    for rel in model.entities.relationships.values():
        for to_doc_id_val in [rel.left_table_occurrence_doc_id, rel.right_table_occurrence_doc_id]:
            if to_doc_id_val in model.entities.table_occurrences:
                model.references.append(ReferenceRecord(
                    sourceDocId=rel.doc_id,
                    sourceEntityType="relationship",
                    targetDocId=to_doc_id_val,
                    targetEntityType="tableOccurrence",
                    relationshipType="joinsTo",
                    confidence="exact",
                ))
        for pred in rel.predicates:
            for tgt, fd, role in [(pred.left_external, pred.left_field_doc_id, "left"),
                                  (pred.right_external, pred.right_field_doc_id, "right")]:
                if tgt is not None:
                    model.references.append(ReferenceRecord(
                        sourceDocId=rel.doc_id,
                        sourceEntityType="relationship",
                        targetDocId=fd,
                        targetEntityType="field",
                        relationshipType="usesField",
                        role=role,
                        confidence="external",
                        externalTarget=tgt,
                    ))
            for fd, role in [(pred.left_field_doc_id, "left"), (pred.right_field_doc_id, "right")]:
                if fd in model.entities.fields:
                    model.references.append(ReferenceRecord(
                        sourceDocId=rel.doc_id,
                        sourceEntityType="relationship",
                        targetDocId=fd,
                        targetEntityType="field",
                        relationshipType="usesField",
                        role=role,
                        confidence="exact",
                    ))


# ---------------------------------------------------------------------------
# Layout → Table Occurrence and Fields
# ---------------------------------------------------------------------------

def _link_layouts(model: DocumentModel) -> None:
    for layout in model.entities.layouts.values():
        if layout.base_table_occurrence_doc_id and layout.base_table_occurrence_doc_id in model.entities.table_occurrences:
            model.references.append(ReferenceRecord(
                sourceDocId=layout.doc_id,
                sourceEntityType="layout",
                targetDocId=layout.base_table_occurrence_doc_id,
                targetEntityType="tableOccurrence",
                relationshipType="basedOnTableOccurrence",
                confidence="exact",
            ))
        for fd in layout.referenced_fields:
            if fd in model.entities.fields:
                model.references.append(ReferenceRecord(
                    sourceDocId=layout.doc_id,
                    sourceEntityType="layout",
                    targetDocId=fd,
                    targetEntityType="field",
                    relationshipType="usesField",
                    role="display",
                    confidence="exact",
                ))


# ---------------------------------------------------------------------------
# Layout Object → Layout / Field / Table Occurrence
# ---------------------------------------------------------------------------

def _link_layout_objects(model: DocumentModel) -> None:
    layout_vl_seen: set[tuple[str, str]] = set()
    for obj in model.entities.layout_objects.values():
        if obj.layout_doc_id in model.entities.layouts:
            model.references.append(ReferenceRecord(
                sourceDocId=obj.layout_doc_id,
                sourceEntityType="layout",
                targetDocId=obj.doc_id,
                targetEntityType="layoutObject",
                relationshipType="contains",
                confidence="exact",
            ))
        if obj.value_list_doc_id and obj.value_list_doc_id in model.entities.value_lists:
            model.references.append(ReferenceRecord(
                sourceDocId=obj.doc_id,
                sourceEntityType="layoutObject",
                targetDocId=obj.value_list_doc_id,
                targetEntityType="valueList",
                relationshipType="usesValueList",
                role="control",
                confidence="exact",
            ))
            # Roll up to the owning layout (once per layout / value list)
            key = (obj.layout_doc_id, obj.value_list_doc_id)
            if obj.layout_doc_id in model.entities.layouts and key not in layout_vl_seen:
                layout_vl_seen.add(key)
                model.references.append(ReferenceRecord(
                    sourceDocId=obj.layout_doc_id,
                    sourceEntityType="layout",
                    targetDocId=obj.value_list_doc_id,
                    targetEntityType="valueList",
                    relationshipType="usesValueList",
                    role="control",
                    confidence="exact",
                ))
        if obj.external_target is not None and obj.field_doc_id:
            model.references.append(ReferenceRecord(
                sourceDocId=obj.doc_id,
                sourceEntityType="layoutObject",
                targetDocId=obj.field_doc_id,
                targetEntityType="field",
                relationshipType="usesField",
                role="display",
                confidence="external",
                externalTarget=obj.external_target,
            ))
        if obj.field_doc_id and obj.field_doc_id in model.entities.fields:
            model.references.append(ReferenceRecord(
                sourceDocId=obj.doc_id,
                sourceEntityType="layoutObject",
                targetDocId=obj.field_doc_id,
                targetEntityType="field",
                relationshipType="usesField",
                role="display",
                confidence="exact",
            ))
        if (
            obj.table_occurrence_doc_id
            and obj.table_occurrence_doc_id in model.entities.table_occurrences
        ):
            model.references.append(ReferenceRecord(
                sourceDocId=obj.doc_id,
                sourceEntityType="layoutObject",
                targetDocId=obj.table_occurrence_doc_id,
                targetEntityType="tableOccurrence",
                relationshipType="basedOnTableOccurrence",
                confidence="exact",
            ))


# ---------------------------------------------------------------------------
# Script → Layout / Field / Script
# ---------------------------------------------------------------------------

def _link_scripts(model: DocumentModel) -> None:
    for script in model.entities.scripts.values():
        for step_doc_id in script.steps:
            step = model.entities.script_steps.get(step_doc_id)
            if step is None:
                continue
            for ref in step.references:
                kind = ref.get("kind")
                target = ref.get("targetDocId", "")
                if not target:
                    continue
                rel_type_map = {
                    "field": "usesField",
                    "layout": "usesLayout",
                    "script": "usesScript",
                    "customFunction": "usesCustomFunction",
                    "valueList": "usesValueList",
                }
                rel_type = rel_type_map.get(kind, "usesField")
                entity_exists = model.get_entity(target) is not None
                external_target = ref.get("external")
                if external_target:
                    # Target lives in another file of a multi-file solution
                    confidence = "external"
                else:
                    confidence = "exact" if entity_exists else "unresolved"
                model.references.append(ReferenceRecord(
                    sourceDocId=step_doc_id,
                    sourceEntityType="scriptStep",
                    targetDocId=target,
                    targetEntityType=kind or "unknown",
                    relationshipType=rel_type,
                    role=ref.get("role"),
                    confidence=confidence,
                    rawText=ref.get("rawText"),
                    externalTarget=external_target or None,
                ))


def _link_accounts_to_privilege_sets(model: DocumentModel) -> None:
    for acct in model.entities.accounts.values():
        if acct.privilege_set_doc_id and acct.privilege_set_doc_id in model.entities.privilege_sets:
            model.references.append(ReferenceRecord(
                sourceDocId=acct.doc_id,
                sourceEntityType="account",
                targetDocId=acct.privilege_set_doc_id,
                targetEntityType="privilegeSet",
                relationshipType="assignedPrivilegeSet",
                confidence="exact",
            ))


def _link_extended_privileges_to_privilege_sets(model: DocumentModel) -> None:
    for ep in model.entities.extended_privileges.values():
        for ps_doc_id in ep.privilege_set_doc_ids:
            if ps_doc_id in model.entities.privilege_sets:
                model.references.append(ReferenceRecord(
                    sourceDocId=ep.doc_id,
                    sourceEntityType="extPriv",
                    targetDocId=ps_doc_id,
                    targetEntityType="privilegeSet",
                    relationshipType="grantedTo",
                    confidence="exact",
                ))


def _link_custom_menus(model: DocumentModel) -> None:
    """Custom menu → scripts its items perform, and submenus they open."""
    for menu in model.entities.custom_menus.values():
        for item in menu.items:
            if item.script_doc_id:
                if item.script_external is not None:
                    confidence = "external"
                else:
                    confidence = "exact" if item.script_doc_id in model.entities.scripts else "unresolved"
                model.references.append(ReferenceRecord(
                    sourceDocId=menu.doc_id,
                    sourceEntityType="customMenu",
                    targetDocId=item.script_doc_id,
                    targetEntityType="script",
                    relationshipType="usesScript",
                    role="menuItem",
                    confidence=confidence,
                    rawText=item.name,
                    externalTarget=item.script_external,
                ))
            if item.submenu_doc_id:
                model.references.append(ReferenceRecord(
                    sourceDocId=menu.doc_id,
                    sourceEntityType="customMenu",
                    targetDocId=item.submenu_doc_id,
                    targetEntityType="customMenu",
                    relationshipType="usesCustomMenu",
                    role="submenu",
                    confidence="exact" if item.submenu_doc_id in model.entities.custom_menus else "unresolved",
                    rawText=item.name,
                ))


def _link_value_lists(model: DocumentModel) -> None:
    """Value list → source / second field (usage evidence for those fields)."""
    for vl in model.entities.value_lists.values():
        for tgt, fd, role in [(vl.source_field_external, vl.source_field_doc_id, "source"),
                              (vl.second_field_external, vl.second_field_doc_id, "second")]:
            if tgt is not None and fd:
                model.references.append(ReferenceRecord(
                    sourceDocId=vl.doc_id,
                    sourceEntityType="valueList",
                    targetDocId=fd,
                    targetEntityType="field",
                    relationshipType="usesField",
                    role=role,
                    confidence="external",
                    externalTarget=tgt,
                ))
        for fd, role in [(vl.source_field_doc_id, "source"), (vl.second_field_doc_id, "second")]:
            if fd and fd in model.entities.fields:
                model.references.append(ReferenceRecord(
                    sourceDocId=vl.doc_id,
                    sourceEntityType="valueList",
                    targetDocId=fd,
                    targetEntityType="field",
                    relationshipType="usesField",
                    role=role,
                    confidence="exact",
                ))


def _link_field_calculations(model: DocumentModel) -> None:
    """Calculation / auto-enter calculation fields → fields, value lists and custom functions they use.

    Also links a field to the value list used by its "member of value list" validation.
    """
    from ..analyze.calculations import extract_calc_references
    ext = ExternalTargets(model)
    for field in model.entities.fields.values():
        vl = field.validation.value_list_doc_id if field.validation else None
        if vl and vl in model.entities.value_lists:
            model.references.append(ReferenceRecord(
                sourceDocId=field.doc_id,
                sourceEntityType="field",
                targetDocId=vl,
                targetEntityType="valueList",
                relationshipType="usesValueList",
                role="validation",
                confidence="exact",
            ))
        calcs = [field.calculation]
        if field.auto_enter is not None:
            calcs.append(field.auto_enter.calculation)
        for calc in calcs:
            if not calc:
                continue
            for ref in extract_calc_references(calc, model):
                if ref["confidence"] == "unresolved" or ref["targetDocId"] == field.doc_id:
                    continue
                et = _calc_external_target(ext, ref)
                model.references.append(ReferenceRecord(
                    sourceDocId=field.doc_id,
                    sourceEntityType="field",
                    targetDocId=_calc_target_doc_id(ref, et),
                    targetEntityType=ref["entityType"],
                    relationshipType=ref["relationshipType"],
                    confidence=ref["confidence"],
                    rawText=ref.get("rawText"),
                    externalTarget=et,
                ))


def _calc_external_target(ext: ExternalTargets, ref: dict):
    """ExternalTarget for a calculation-derived reference that points into another file."""
    if ref.get("confidence") != "external":
        return None
    return ext.field(ref.get("table"), ref.get("field", ""))


def _calc_target_doc_id(ref: dict, external_target) -> str:
    """DocId a calculation reference points at: the scoped id when it lives in another file."""
    return external_target.scoped_doc_id if external_target else ref["targetDocId"]


def _link_custom_functions(model: DocumentModel) -> None:
    """Parse calculation text of custom functions and add parsed references."""
    from ..analyze.calculations import extract_calc_references
    ext = ExternalTargets(model)
    for cf in model.entities.custom_functions.values():
        if not cf.calculation:
            continue
        refs = extract_calc_references(cf.calculation, model)
        for ref in refs:
            et = _calc_external_target(ext, ref)
            model.references.append(ReferenceRecord(
                sourceDocId=cf.doc_id,
                sourceEntityType="customFunction",
                targetDocId=_calc_target_doc_id(ref, et),
                targetEntityType=ref["entityType"],
                relationshipType=ref["relationshipType"],
                confidence=ref["confidence"],
                rawText=ref.get("rawText"),
                externalTarget=et,
            ))
