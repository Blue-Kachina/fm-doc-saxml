"""Parse FileMaker calculation text for entity references."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..model.document_model import DocumentModel

# Matches TableOccurrence::FieldName patterns (supports spaces in names)
_TABLE_FIELD_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_ ]*)::([A-Za-z_][A-Za-z0-9_ ]*)')

# Matches potential custom function calls: FunctionName( ...
_CF_CALL_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')


def extract_calc_references(
    calculation: str,
    model: "DocumentModel",
) -> list[dict[str, Any]]:
    """Parse a calculation string and return a list of reference dicts."""
    if not calculation:
        return []

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Extract Table::Field references
    for match in _TABLE_FIELD_RE.finditer(calculation):
        table_name = match.group(1).strip()
        field_name = match.group(2).strip()
        raw_text = match.group(0)

        # Try to find matching field in model
        from ..normalize.ids import field_doc_id, to_doc_id
        candidate_doc_id = field_doc_id(table_name, field_name)
        if candidate_doc_id in seen:
            continue
        seen.add(candidate_doc_id)

        if candidate_doc_id in model.entities.fields:
            confidence = "parsed"
        else:
            # Maybe table_name is a TO name; try resolving via base table
            to_entity = model.entities.table_occurrences.get(to_doc_id(table_name))
            if to_entity:
                base_name = to_entity.base_table_doc_id.split(":", 1)[1] if ":" in to_entity.base_table_doc_id else ""
                alt_id = field_doc_id(base_name, field_name) if base_name else ""
                if alt_id in model.entities.fields:
                    candidate_doc_id = alt_id
                    confidence = "parsed"
                else:
                    confidence = "unresolved"
            else:
                confidence = "unresolved"

        refs.append({
            "targetDocId": candidate_doc_id,
            "entityType": "field",
            "relationshipType": "usesField",
            "confidence": confidence,
            "rawText": raw_text,
        })

    # Extract custom function calls
    known_cf_names = {cf.name: cf.doc_id for cf in model.entities.custom_functions.values()}
    for match in _CF_CALL_RE.finditer(calculation):
        fn_name = match.group(1)
        if fn_name in known_cf_names:
            cf_doc_id = known_cf_names[fn_name]
            if cf_doc_id not in seen:
                seen.add(cf_doc_id)
                refs.append({
                    "targetDocId": cf_doc_id,
                    "entityType": "customFunction",
                    "relationshipType": "usesCustomFunction",
                    "confidence": "parsed",
                    "rawText": fn_name,
                })

    return refs
