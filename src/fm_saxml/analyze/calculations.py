"""Parse FileMaker calculation text for entity references."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..model.document_model import DocumentModel

# Matches TableOccurrence::FieldName patterns (supports spaces in names)
_TABLE_FIELD_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_ ]*)::([A-Za-z_][A-Za-z0-9_ ]*)')

# Matches potential custom function calls: FunctionName( ...
_VALUE_LIST_ITEMS_RE = re.compile(
    r'\bValueListItems\s*\(\s*[^;()]*(?:\([^()]*\))?[^;()]*;\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE
)
_CF_CALL_RE =re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')


def extract_calc_references(
    calculation: str,
    model: "DocumentModel",
    resolver=None,
) -> list[dict[str, Any]]:
    """Parse a calculation string and return a list of reference dicts."""
    if not calculation:
        return []

    from ..normalize.field_resolver import build_external_to_lookup, build_field_resolver
    resolve_field = resolver or build_field_resolver(model)
    is_external = build_external_to_lookup(model)

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
        if not resolved and is_external(table_name):
            confidence = "external"  # TO belongs to another file
        if candidate_doc_id in seen:
            continue
        seen.add(candidate_doc_id)

        refs.append({
            "targetDocId": candidate_doc_id,
            "entityType": "field",
            "relationshipType": "usesField",
            "confidence": confidence,
            "rawText": raw_text,
            "table": table_name,
            "field": field_name,
        })

    # ValueListItems ( file ; "Value List Name" ) — value list referenced by name
    known_vls = {vl.name.casefold(): vl.doc_id for vl in model.entities.value_lists.values()}
    for match in _VALUE_LIST_ITEMS_RE.finditer(calculation):
        vl_name = match.group(1).replace('\\"', '"')
        vl_doc = known_vls.get(vl_name.strip().casefold())
        if vl_doc and vl_doc not in seen:
            seen.add(vl_doc)
            refs.append({
                "targetDocId": vl_doc,
                "entityType": "valueList",
                "relationshipType": "usesValueList",
                "confidence": "parsed",
                "rawText": match.group(0),
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
