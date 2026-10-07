"""Resolve references between entities — builds the references list and enriches entities."""

from __future__ import annotations

from typing import Any

from ..model.document_model import DocumentModel
from ..model.references import ReferenceRecord
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
    _link_summary_fields(model)
    _link_tos_to_tables(model)
    _link_relationships(model)
    _link_layouts(model)
    _link_layout_objects(model)
    _link_scripts(model)
    _link_script_triggers(model)
    _link_value_lists(model)
    _link_custom_menus(model)
    _link_field_validation_value_lists(model)
    _link_calculations(model)
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


def _link_summary_fields(model: DocumentModel) -> None:
    """A summary field (e.g. "Total Of") → the field it aggregates."""
    for field in model.entities.fields.values():
        if field.summary_field_doc_id and field.summary_field_doc_id in model.entities.fields:
            model.references.append(ReferenceRecord(
                sourceDocId=field.doc_id,
                sourceEntityType="field",
                targetDocId=field.summary_field_doc_id,
                targetEntityType="field",
                relationshipType="summarizes",
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
        # Single-step button targets, portal sort fields
        _link_entity_refs(model, obj.doc_id, "layoutObject", obj.references)
        if obj.button_script_doc_id:
            if obj.button_script_external is not None:
                confidence = "external"
            else:
                confidence = "exact" if obj.button_script_doc_id in model.entities.scripts else "unresolved"
            model.references.append(ReferenceRecord(
                sourceDocId=obj.doc_id,
                sourceEntityType="layoutObject",
                targetDocId=obj.button_script_doc_id,
                targetEntityType="script",
                relationshipType="triggersScript",
                role="button",
                confidence=confidence,
                externalTarget=obj.button_script_external,
            ))


# ---------------------------------------------------------------------------
# Script → Layout / Field / Script
# ---------------------------------------------------------------------------

_REL_TYPE_FOR_KIND = {
    "field": "usesField",
    "layout": "usesLayout",
    "script": "usesScript",
    "customFunction": "usesCustomFunction",
    "valueList": "usesValueList",
}


def _link_entity_refs(model: DocumentModel, source_doc_id: str, source_type: str, refs: list[dict]) -> None:
    """ReferenceRecords for an entity's ``references`` list (``{"kind", "targetDocId", "role", ...}``)."""
    for ref in refs:
        kind = ref.get("kind")
        target = ref.get("targetDocId", "")
        if not target:
            continue
        external_target = ref.get("external")
        if external_target:
            # Target lives in another file of a multi-file solution
            confidence = "external"
        else:
            confidence = "exact" if model.get_entity(target) is not None else "unresolved"
        model.references.append(ReferenceRecord(
            sourceDocId=source_doc_id,
            sourceEntityType=source_type,
            targetDocId=target,
            targetEntityType=kind or "unknown",
            relationshipType=_REL_TYPE_FOR_KIND.get(kind, "usesField"),
            role=ref.get("role"),
            confidence=confidence,
            rawText=ref.get("rawText"),
            externalTarget=external_target or None,
        ))


def _link_scripts(model: DocumentModel) -> None:
    for script in model.entities.scripts.values():
        for step_doc_id in script.steps:
            step = model.entities.script_steps.get(step_doc_id)
            if step is not None:
                _link_entity_refs(model, step_doc_id, "scriptStep", step.references)


def _link_script_triggers(model: DocumentModel) -> None:
    """Layout / layout object -> the script each of its script triggers runs (role: the event)."""
    sources = [("layout", model.entities.layouts), ("layoutObject", model.entities.layout_objects)]
    for source_type, entities in sources:
        for entity in entities.values():
            for trig in entity.script_triggers:
                if trig.script_external is not None:
                    confidence = "external"
                else:
                    confidence = "exact" if trig.script_doc_id in model.entities.scripts else "unresolved"
                model.references.append(ReferenceRecord(
                    sourceDocId=entity.doc_id,
                    sourceEntityType=source_type,
                    targetDocId=trig.script_doc_id,
                    targetEntityType="script",
                    relationshipType="triggersScript",
                    role=trig.event or None,
                    confidence=confidence,
                    externalTarget=trig.script_external,
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


def _link_field_validation_value_lists(model: DocumentModel) -> None:
    """A field -> the value list used by its "member of value list" validation."""
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


def _link_calculations(model: DocumentModel) -> None:
    """Entities -> the fields, custom functions and value lists their calculations use.

    Covers field formulas / auto-enter / validation, custom function bodies, layout
    script-trigger parameters, every calc on a layout object (hide condition, conditional
    formatting, tooltip, button parameter, ...) and custom menu install conditions. The
    role is what the calc is for. A layout object's uses are also rolled up to its
    layout, so "which layouts use this field" includes hide conditions and the like.
    """
    from .calc_refs import CalcRefResolver, RELATIONSHIP_FOR_KIND

    resolver = CalcRefResolver(model)
    sources = [
        ("field", model.entities.fields),
        ("customFunction", model.entities.custom_functions),
        ("layout", model.entities.layouts),
        ("layoutObject", model.entities.layout_objects),
        ("customMenu", model.entities.custom_menus),
    ]
    rolled_up: set[tuple[str, str, str]] = set()
    for source_type, entities in sources:
        for entity in entities.values():
            seen: set[tuple[str, str]] = set()
            for calc in entity.calculations:
                for use in resolver.uses(calc.text, calc.chunk_refs):
                    if source_type == "field" and use.target_doc_id == entity.doc_id:
                        continue  # a field naming itself (e.g. in its own auto-enter calc)
                    if (use.target_doc_id, calc.role) in seen:
                        continue
                    seen.add((use.target_doc_id, calc.role))
                    record = dict(
                        targetDocId=use.target_doc_id,
                        targetEntityType=use.kind,
                        relationshipType=RELATIONSHIP_FOR_KIND[use.kind],
                        role=calc.role,
                        confidence=use.confidence,
                        rawText=use.raw_text,
                        externalTarget=use.external,
                    )
                    model.references.append(ReferenceRecord(
                        sourceDocId=entity.doc_id, sourceEntityType=source_type, **record))
                    layout_did = getattr(entity, "layout_doc_id", None) if source_type == "layoutObject" else None
                    key = (layout_did, use.target_doc_id, calc.role)
                    if layout_did in model.entities.layouts and key not in rolled_up:
                        rolled_up.add(key)
                        model.references.append(ReferenceRecord(
                            sourceDocId=layout_did, sourceEntityType="layout", **record))
