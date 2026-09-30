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
    resolver=None,
) -> list[dict[str, Any]]:
    """Parse a calculation string and return a list of reference dicts."""
    if not calculation:
        return []

    from ..normalize.field_resolver import build_field_resolver
    resolve_field = resolver or build_field_resolver(model)

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Extract Table::Field references
    for match in _TABLE_FIELD_RE.finditer(calculation):
        table_name = match.group(1).strip()
        field_name = match.group(2).strip()
        raw_text = match.group(0)

        # Table part is normally a table occurrence name — resolve to the real field
        from ..normalize.ids import field_doc_id
        resolved = resolve_field(table_name, field_name)
        candidate_doc_id = resolved or field_doc_id(table_name, field_name)
        confidence = "parsed" if resolved else "unresolved"
        if candidate_doc_id in seen:
            continue
        seen.add(candidate_doc_id)

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
