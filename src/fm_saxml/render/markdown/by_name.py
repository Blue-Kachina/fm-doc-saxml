"""Indirection (by-name references) shaped for the Markdown pages and Reports/indirection.md."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...model.document_model import DocumentModel
from ...model.indirection import CLASS_LABELS, IndirectionSite

CLASS_ORDER = ["B", "C", "E", "D", "A", "A'"]

CLASS_MEANINGS = {
    "A": "The name comes from a real reference (GetFieldName, Get ( ScriptName ), an SQL helper function). "
         "It follows a rename.",
    "A'": "Resolved by internal ID (FileMaker_Fields, ScriptIDs). Survives a rename, not a delete and recreate.",
    "B": "The name is written as text right here. **Breaks on rename.**",
    "C": "The name reaches this place through variables, script parameters or a pattern. Breaks on rename when "
         "it started as text.",
    "D": "The name comes from data (field contents, records, an API response). It can't be checked from the "
         "file alone.",
    "E": "Names something that doesn't exist in this file: already broken, or names another file.",
}

KIND_LABELS = {
    "field": "field", "script": "script", "layout": "layout", "tableOccurrence": "table occurrence",
    "valueList": "value list", "layoutObject": "layout object", "sql": "SQL", "expression": "formula",
    "layoutOrTableOccurrence": "layout / table occurrence",
}


def trace_text(evidence: list[str]) -> str:
    return " ← ".join(evidence)


class ByNameIndex:
    def __init__(self, model: DocumentModel) -> None:
        self.model = model
        self.sites: list[IndirectionSite] = list(model.indirection)
        self.by_target: dict[str, list[tuple[IndirectionSite, Any]]] = {}
        self.by_source: dict[str, list[IndirectionSite]] = {}
        self.by_script: dict[str, list[IndirectionSite]] = {}
        for site in self.sites:
            self.by_source.setdefault(site.source_doc_id, []).append(site)
            if site.script_doc_id:
                self.by_script.setdefault(site.script_doc_id, []).append(site)
            for cand in site.candidates:
                self.by_target.setdefault(cand.target_doc_id, []).append((site, cand))

    # -- entity pages ----------------------------------------------------------------
    def for_target(self, doc_id: str) -> dict[str, list[dict[str, Any]]]:
        breaks, safe = [], []
        for site, cand in self.by_target.get(doc_id, []):
            row = {
                "where": site.source_doc_id, "how": site.sink, "name": cand.name, "klass": site.klass,
                "confidence": cand.confidence, "origin": cand.origin, "trace": trace_text(cand.evidence),
                "note": site.note or "",
            }
            (breaks if cand.breaks_on_rename else safe).append(row)
        key = lambda r: (r["klass"] != "B", r["confidence"] != "parsed", r["how"])  # noqa: E731
        return {"breaks": sorted(breaks, key=key), "safe": safe}

    def sites_for(self, doc_id: str, script: bool = False) -> list[dict[str, Any]]:
        sites = self.by_script.get(doc_id, []) if script else self.by_source.get(doc_id, [])
        return [self.site_row(s) for s in sorted(sites, key=lambda s: (s.step or 0, s.doc_id))]

    @staticmethod
    def site_row(site: IndirectionSite) -> dict[str, Any]:
        return {
            "site": site, "where": site.source_doc_id, "step": site.step, "how": site.sink,
            "expression": site.expression, "klass": site.klass, "label": CLASS_LABELS[site.klass],
            "kind": KIND_LABELS.get(site.name_kind, site.name_kind),
            "targets": [c.target_doc_id for c in site.candidates],
            "names": site.names, "note": site.note or "",
            "trace": trace_text(site.candidates[0].evidence) if site.candidates else "",
        }

    # -- the report ------------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        counts = Counter(s.klass for s in self.sites)
        classes = [{"klass": k, "label": CLASS_LABELS[k], "count": counts.get(k, 0), "meaning": CLASS_MEANINGS[k]}
                   for k in CLASS_ORDER]
        sinks: dict[str, Counter] = {}
        for s in self.sites:
            sinks.setdefault(s.sink, Counter())[s.klass] += 1
        sink_rows = [{"sink": name, "total": sum(c.values()), **{k: c.get(k, 0) for k in CLASS_ORDER}}
                     for name, c in sorted(sinks.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))]

        risk: dict[str, dict[str, Any]] = {}
        for s in self.sites:
            for c in s.candidates:
                if not c.breaks_on_rename:
                    continue
                row = risk.setdefault(c.target_doc_id, {
                    "target": c.target_doc_id, "kind": c.target_entity_type,
                    "kind_label": KIND_LABELS.get(c.target_entity_type, c.target_entity_type),
                    "B": 0, "C": 0, "pattern": 0, "sites": set()})
                if c.origin == "pattern":
                    row["pattern"] += 1
                elif s.klass == "B":
                    row["B"] += 1
                else:
                    row["C"] += 1
                row["sites"].add(s.doc_id)
        risk_rows = sorted(risk.values(), key=lambda r: (-(r["B"] + r["C"] + r["pattern"]), r["target"]))
        for r in risk_rows:
            r["sites"] = len(r["sites"])

        def rows(klass: str) -> list[dict[str, Any]]:
            return [self.site_row(s) for s in self.sites if s.klass == klass]

        return {
            "total": len(self.sites), "classes": classes, "sinks": sink_rows, "class_order": CLASS_ORDER,
            "risk": risk_rows, "broken": rows("E"), "hardcoded": rows("B"), "traced": rows("C"),
            "opaque": rows("D"),
            "functions": [cf for cf in self.model.entities.custom_functions.values() if cf.name_role],
        }
