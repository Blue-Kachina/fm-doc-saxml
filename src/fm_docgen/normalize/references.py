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
    _link_tos_to_tables(model)
    _link_relationships(model)
    _link_layouts(model)
    _link_layout_objects(model)
    _link_scripts(model)
    _link_custom_functions(model)
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
                }
                rel_type = rel_type_map.get(kind, "usesField")
                entity_exists = model.get_entity(target) is not None
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


def _link_custom_functions(model: DocumentModel) -> None:
    """Parse calculation text of custom functions and add parsed references."""
    from ..analyze.calculations import extract_calc_references
    for cf in model.entities.custom_functions.values():
        if not cf.calculation:
            continue
        refs = extract_calc_references(cf.calculation, model)
        for ref in refs:
            model.references.append(ReferenceRecord(
                sourceDocId=cf.doc_id,
                sourceEntityType="customFunction",
                targetDocId=ref["targetDocId"],
                targetEntityType=ref["entityType"],
                relationshipType=ref["relationshipType"],
                confidence=ref["confidence"],
                rawText=ref.get("rawText"),
            ))
