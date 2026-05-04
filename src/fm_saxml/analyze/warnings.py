"""Post-analysis warnings — identifies potentially problematic patterns."""

from __future__ import annotations

from ..model.document_model import DocumentModel


def generate_warnings(model: DocumentModel) -> DocumentModel:
    """Add analysis-phase warnings to the model."""
    _warn_unresolved_references(model)
    _warn_empty_scripts(model)
    _warn_fields_no_backlinks(model)
    return model


def _warn_unresolved_references(model: DocumentModel) -> None:
    unresolved = [r for r in model.references if r.confidence == "unresolved"]
    for ref in unresolved:
        model.add_warning(
            code="UNRESOLVED_REFERENCE",
            message=f"Unresolved reference from '{ref.source_doc_id}' to '{ref.target_doc_id}'",
            entity_doc_id=ref.source_doc_id,
            detail=ref.raw_text,
        )


def _warn_empty_scripts(model: DocumentModel) -> None:
    for script in model.entities.scripts.values():
        if not script.steps:
            model.add_warning(
                code="EMPTY_SCRIPT",
                message=f"Script '{script.name}' has no steps",
                entity_doc_id=script.doc_id,
            )


def _warn_fields_no_backlinks(model: DocumentModel) -> None:
    """Note fields that appear to have no inbound references."""
    for field in model.entities.fields.values():
        if field.doc_id not in model.backlinks:
            model.add_warning(
                code="UNUSED_FIELD_CANDIDATE",
                message=f"Field '{field.qualified_name}' has no detected references — may be unused",
                entity_doc_id=field.doc_id,
            )
