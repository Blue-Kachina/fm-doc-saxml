"""Work out what a calculation uses: fields, custom functions and value lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, TYPE_CHECKING

from ..model.references import ExternalTarget
from .external import ExternalTargets
from .field_resolver import build_field_resolver
from .ids import custom_function_doc_id, field_doc_id
from .names import normalize_name

if TYPE_CHECKING:
    from ..model.document_model import DocumentModel

RELATIONSHIP_FOR_KIND = {
    "field": "usesField",
    "customFunction": "usesCustomFunction",
    "valueList": "usesValueList",
}


@dataclass
class CalcUse:
    kind: str                   # field | customFunction | valueList
    target_doc_id: str
    raw_text: Optional[str]
    external: Optional[ExternalTarget]
    from_chunks: bool           # FileMaker resolved it (ChunkList) rather than us parsing the text
    confidence: str             # exact | parsed | external | unresolved (meaningful once all entities exist)


class CalcRefResolver:
    """Resolves the references of calculations against one model.

    Fields and custom functions come from the calc's ChunkList, where FileMaker has
    already resolved each one (fields to their table occurrence). The text is parsed
    only for value lists named in ``ValueListItems()`` (a string literal, so never a
    reference token) and, when there is no ChunkList (v1 exports, calcs FileMaker could
    not tokenize), for everything.
    """

    def __init__(self, model: "DocumentModel", resolve_field=None, ext: Optional[ExternalTargets] = None):
        self.model = model
        self.resolve_field = resolve_field or build_field_resolver(model)
        self.ext = ext or ExternalTargets(model)

    def uses(self, text: str, chunk_refs: Optional[Iterable[Any]]) -> list[CalcUse]:
        from ..analyze.calculations import extract_calc_references

        found: list[CalcUse] = []
        seen: set[tuple[str, str]] = set()

        def add(use: CalcUse) -> None:
            if (use.kind, use.target_doc_id) not in seen:
                seen.add((use.kind, use.target_doc_id))
                found.append(use)

        for ch in chunk_refs or []:
            ch = _as_dict(ch)
            if ch["type"] == "field":
                tn, fn = ch.get("table") or "", ch["name"]
                f_ext = self.ext.field(tn, fn, ch.get("fmpId"), ch.get("uuid"))
                fd = f_ext.scoped_doc_id if f_ext else (self.resolve_field(tn, fn) or field_doc_id(tn, fn))
                add(CalcUse("field", fd, f"{tn}::{fn}", f_ext, True, self._confidence(fd, f_ext)))
            elif ch["type"] == "customFunction":
                cd = custom_function_doc_id(normalize_name(ch["name"]))
                add(CalcUse("customFunction", cd, ch["name"], None, True, self._confidence(cd, None)))

        parsed_kinds = ("valueList",) if chunk_refs is not None else ("field", "customFunction", "valueList")
        for cref in extract_calc_references(text, self.model, self.resolve_field):
            if cref["entityType"] not in parsed_kinds or cref["confidence"] == "unresolved":
                continue
            c_ext = (self.ext.field(cref.get("table"), cref.get("field", ""))
                     if cref["confidence"] == "external" else None)
            target = c_ext.scoped_doc_id if c_ext else cref["targetDocId"]
            add(CalcUse(cref["entityType"], target, cref.get("rawText"), c_ext, False,
                        "external" if c_ext else cref["confidence"]))
        return found

    def _confidence(self, target_doc_id: str, external: Optional[ExternalTarget]) -> str:
        if external is not None:
            return "external"
        return "exact" if self.model.get_entity(target_doc_id) is not None else "unresolved"


def _as_dict(chunk_ref: Any) -> dict[str, Any]:
    """Raw parser dict (``id``) or a ``CalcChunkRef`` model (``fmp_id``) -> one shape."""
    if isinstance(chunk_ref, dict):
        return {**chunk_ref, "fmpId": chunk_ref.get("fmpId", chunk_ref.get("id"))}
    return {"type": chunk_ref.type, "name": chunk_ref.name, "table": chunk_ref.table,
            "fmpId": chunk_ref.fmp_id, "uuid": chunk_ref.uuid}


def chunk_ref_models(raw_refs: Optional[list[dict]]):
    """Raw parser ChunkList refs -> ``CalcChunkRef`` models (None stays None: no ChunkList)."""
    from ..model.entities import CalcChunkRef
    if raw_refs is None:
        return None
    return [CalcChunkRef(type=r["type"], name=r["name"], table=r.get("table") or None,
                         fmpId=r.get("id") or None, uuid=r.get("uuid") or None) for r in raw_refs]
