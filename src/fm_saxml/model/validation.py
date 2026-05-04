"""Model validation utilities."""

from __future__ import annotations

from .document_model import DocumentModel


def validate_model(model: DocumentModel) -> DocumentModel:
    """Run consistency checks and add warnings for any issues found."""
    _check_field_table_refs(model)
    _check_to_base_table_refs(model)
    _check_relationship_to_refs(model)
    _check_layout_to_refs(model)
    return model


def _check_field_table_refs(model: DocumentModel) -> None:
    for field in model.entities.fields.values():
        if field.base_table_doc_id not in model.entities.tables:
            model.add_warning(
                code="UNRESOLVED_FIELD_TABLE",
                message=f"Field '{field.qualified_name}' references unknown table '{field.base_table_doc_id}'",
                entity_doc_id=field.doc_id,
            )


def _check_to_base_table_refs(model: DocumentModel) -> None:
    for to in model.entities.table_occurrences.values():
        if to.base_table_doc_id not in model.entities.tables:
            model.add_warning(
                code="UNRESOLVED_TO_TABLE",
                message=f"Table occurrence '{to.name}' references unknown base table '{to.base_table_doc_id}'",
                entity_doc_id=to.doc_id,
            )


def _check_relationship_to_refs(model: DocumentModel) -> None:
    for rel in model.entities.relationships.values():
        for attr, label in [
            (rel.left_table_occurrence_doc_id, "left"),
            (rel.right_table_occurrence_doc_id, "right"),
        ]:
            if attr not in model.entities.table_occurrences:
                model.add_warning(
                    code="UNRESOLVED_RELATIONSHIP_TO",
                    message=f"Relationship '{rel.name}' references unknown {label} table occurrence '{attr}'",
                    entity_doc_id=rel.doc_id,
                )


def _check_layout_to_refs(model: DocumentModel) -> None:
    for layout in model.entities.layouts.values():
        if layout.base_table_occurrence_doc_id and layout.base_table_occurrence_doc_id not in model.entities.table_occurrences:
            model.add_warning(
                code="UNRESOLVED_LAYOUT_TO",
                message=f"Layout '{layout.name}' references unknown table occurrence '{layout.base_table_occurrence_doc_id}'",
                entity_doc_id=layout.doc_id,
            )
