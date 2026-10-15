"""Generate backlinks from the flat references list."""

from __future__ import annotations

from ..model.document_model import DocumentModel


def generate_backlinks(model: DocumentModel) -> DocumentModel:
    """Populate model.backlinks by inverting model.references."""
    backlinks: dict[str, list[dict]] = {}

    for ref in model.references:
        target = ref.target_doc_id
        if not target:
            continue
        if target not in backlinks:
            backlinks[target] = []
        entry = {
            "sourceDocId": ref.source_doc_id,
            "sourceEntityType": ref.source_entity_type,
            "relationshipType": ref.relationship_type,
            "role": ref.role,
            "confidence": ref.confidence,
        }
        if ref.via:  # named in a string: see analyze/indirection.py
            entry["via"] = ref.via
            entry["siteDocId"] = ref.site_doc_id
        backlinks[target].append(entry)

    model.backlinks = backlinks
    return model
