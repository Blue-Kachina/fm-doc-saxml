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
    """Note fields that appear to have no inbound *usage* references.

    Every field also has a structural ``contains`` backlink from its own
    table (added by ``_link_fields_to_tables``) purely because it's defined
    there — that exists regardless of whether the field is ever actually
    used, so it must not count as evidence of use here.
    """
    for field in model.entities.fields.values():
        usage_backlinks = [
            b for b in model.backlinks.get(field.doc_id, [])
            if b.get("relationshipType") != "contains"
        ]
        if not usage_backlinks:
            model.add_warning(
                code="UNUSED_FIELD_CANDIDATE",
                message=f"Field '{field.qualified_name}' has no detected usage references — may be unused",
                entity_doc_id=field.doc_id,
            )
