"""What to check before renaming an entity (``fm-saxml rename-check``).

FileMaker updates *direct* references on rename. It does not update a name written in
text (analyze/indirection.py), so for each entity this lists:

* **breaks**: places that name it in text (hardcoded, or traced through variables and
  script parameters, or matched by a pattern). These need editing.
* **safe**: places that get its name from a real reference (GetFieldName, Get (
  ScriptName ), an SQL helper function). They follow the rename.
* **opaque**: places that take a name of the same kind from data. We can't tell whether
  they name this entity: check them by hand.
* **direct**: references FileMaker updates by itself (for scale, nothing to do).

For a rename *plan* (old -> new), the new name is also checked: an existing entity of the
same kind with that name is a clash, and a place that already names it in text (today
broken, or naming another entity) would silently start pointing at the renamed entity.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..model.document_model import DocumentModel
from ..model.indirection import IndirectCandidate, IndirectionSite

# Kinds of name a site can hold that might name an entity of each type
NAME_KINDS = {
    "field": {"field", "sql", "expression"},
    "script": {"script"},
    "layout": {"layout", "layoutOrTableOccurrence"},
    "tableOccurrence": {"tableOccurrence", "sql", "layoutOrTableOccurrence"},
    "valueList": {"valueList"},
    "layoutObject": {"layoutObject"},
}

KIND_ALIASES = {
    "field": "field", "fields": "field", "script": "script", "scripts": "script", "layout": "layout",
    "layouts": "layout", "to": "tableOccurrence", "tableoccurrence": "tableOccurrence", "table-occurrence": "tableOccurrence",
    "valuelist": "valueList", "value-list": "valueList", "vl": "valueList", "object": "layoutObject",
    "layoutobject": "layoutObject", "layout-object": "layoutObject",
}


@dataclass
class Impact:
    doc_id: str
    entity_type: str
    name: str
    breaks: list[tuple[IndirectionSite, IndirectCandidate]] = field(default_factory=list)
    safe: list[tuple[IndirectionSite, IndirectCandidate]] = field(default_factory=list)
    opaque: list[IndirectionSite] = field(default_factory=list)
    direct: int = 0
    new_name: Optional[str] = None
    clashes: list[str] = field(default_factory=list)          # docIds already called new_name
    captured_by_new_name: list[IndirectionSite] = field(default_factory=list)  # sites that already say new_name


def entity_name(model: DocumentModel, doc_id: str) -> str:
    ent = model.get_entity(doc_id)
    if getattr(ent, "entity_type", "") == "layoutObject":
        layout = model.entities.layouts.get(ent.layout_doc_id)
        return f"{layout.name if layout else ent.layout_doc_id} · {ent.name or ent.object_type or ent.object_id}"
    return getattr(ent, "qualified_name", None) or getattr(ent, "name", None) or doc_id


def find_entities(model: DocumentModel, name: str, kind: Optional[str] = None) -> list[str]:
    """docIds called ``name`` (case-insensitive). ``Table::Field`` may use a table occurrence."""
    from ..normalize.field_resolver import build_field_resolver

    name = name.strip()
    if model.get_entity(name) is not None:  # already a docId
        return [name]
    ents = model.entities
    want = name.casefold()
    hits: list[str] = []
    if "::" in name and kind in (None, "field"):
        table, fld = name.split("::", 1)
        target = build_field_resolver(model)(table, fld)
        if target:
            hits.append(target)
    maps = {"script": ents.scripts, "layout": ents.layouts, "tableOccurrence": ents.table_occurrences,
            "valueList": ents.value_lists, "layoutObject": ents.layout_objects}
    for k, entity_map in maps.items():
        if kind not in (None, k):
            continue
        hits.extend(e.doc_id for e in entity_map.values() if getattr(e, "name", "") and e.name.casefold() == want)
    if kind in (None, "field") and "::" not in name:
        hits.extend(f.doc_id for f in ents.fields.values() if f.name.casefold() == want)
    return list(dict.fromkeys(hits))


def rename_impact(model: DocumentModel, doc_id: str, new_name: Optional[str] = None) -> Impact:
    ent = model.get_entity(doc_id)
    etype = getattr(ent, "entity_type", "") if ent is not None else ""
    impact = Impact(doc_id=doc_id, entity_type=etype, name=entity_name(model, doc_id), new_name=new_name)
    kinds = NAME_KINDS.get(etype, set())
    for site in model.indirection:
        cand = next((c for c in site.candidates if c.target_doc_id == doc_id), None)
        if cand is not None:
            (impact.breaks if cand.breaks_on_rename else impact.safe).append((site, cand))
        elif site.klass == "D" and site.name_kind in kinds:
            impact.opaque.append(site)
    impact.direct = sum(1 for b in model.backlinks.get(doc_id, [])
                        if not b.get("via") and b.get("relationshipType") != "contains")
    if new_name:
        _check_new_name(model, impact, etype, new_name)
    return impact


def _check_new_name(model: DocumentModel, impact: Impact, etype: str, new_name: str) -> None:
    new_key = new_name.strip().casefold()
    if etype == "field":
        ent = model.get_entity(impact.doc_id)
        table = ent.base_table_doc_id if ent is not None else None
        bare = new_key.split("::")[-1]
        impact.clashes = [f.doc_id for f in model.entities.fields.values()
                          if f.base_table_doc_id == table and f.name.casefold() == bare and f.doc_id != impact.doc_id]
    else:
        impact.clashes = [d for d in find_entities(model, new_name, etype) if d != impact.doc_id]
    kinds = NAME_KINDS.get(etype, set())
    for site in model.indirection:
        if site.name_kind not in kinds:
            continue
        for name in site.names:
            n = name.casefold()
            if n == new_key or (etype == "field" and "::" in n and n.split("::", 1)[1] == new_key.split("::")[-1]):
                impact.captured_by_new_name.append(site)
                break


def read_plan(path: Path) -> list[tuple[str, str, Optional[str]]]:
    """``old,new[,kind]`` rows; a first row whose first cell is "old" is a header."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.reader(fh)):
            cells = [c.strip() for c in row]
            if not cells or not cells[0] or cells[0].startswith("#"):
                continue
            if i == 0 and cells[0].casefold() in ("old", "from", "old name"):
                continue
            if len(cells) < 2 or not cells[1]:
                raise ValueError(f"{path.name} line {i + 1}: expected old,new[,kind]")
            kind = normalize_kind(cells[2]) if len(cells) > 2 and cells[2] else None
            rows.append((cells[0], cells[1], kind))
    return rows


def normalize_kind(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    key = re.sub(r"\s+", "", kind).casefold()
    if key not in KIND_ALIASES:
        raise ValueError(f"unknown kind '{kind}' (use field, script, layout, to, valuelist or object)")
    return KIND_ALIASES[key]


def where_label(model: DocumentModel, doc_id: str) -> str:
    step = model.entities.script_steps.get(doc_id)
    if step is not None:
        script = model.entities.scripts.get(step.script_doc_id)
        return f"{script.name if script else step.script_doc_id} · step {step.index + 1}"
    return entity_name(model, doc_id)


def impact_markdown(model: DocumentModel, impacts: list[Impact], unknown: list[str]) -> str:
    """A Markdown report of rename impacts, for ``rename-check --out``."""
    out = ["# Rename Check", "", f"Source: {model.source.file_name}", ""]
    total = sum(len(i.breaks) for i in impacts)
    out.append(f"{len(impacts)} entit{'y' if len(impacts) == 1 else 'ies'} checked; **{total} place(s) name them in "
               "text and need editing.** FileMaker updates direct references by itself.")
    out.append("")
    if unknown:
        out += ["Not found in this file: " + ", ".join(f"`{u}`" for u in unknown), ""]
    for imp in impacts:
        title = f"{imp.name} ({imp.entity_type})" + (f" → {imp.new_name}" if imp.new_name else "")
        out += [f"## {title}", ""]
        out.append(f"- Breaks on rename: **{len(imp.breaks)}**")
        out.append(f"- Name comes from data (check by hand): {len(imp.opaque)}")
        out.append(f"- Captured safely: {len(imp.safe)}")
        out.append(f"- Direct references (updated by FileMaker): {imp.direct}")
        if imp.clashes:
            out.append("- **Clash:** already used by " + ", ".join(entity_name(model, d) for d in imp.clashes))
        if imp.captured_by_new_name:
            out.append(f"- **{len(imp.captured_by_new_name)} place(s) already use the new name in text**; after the "
                       "rename they will point at this entity: " + ", ".join(
                           where_label(model, s.source_doc_id) for s in imp.captured_by_new_name[:10]))
        out.append("")
        if imp.breaks:
            out += ["| Where | How | Name used | Confidence | How the name gets there |", "|---|---|---|---|---|"]
            for site, cand in imp.breaks:
                trace = " ← ".join(cand.evidence) or "written here"
                out.append(f"| {_cell(where_label(model, site.source_doc_id))} | {_cell(site.sink)} | "
                           f"`{_cell(cand.name)}` | {cand.confidence} | {_cell(trace)} |")
            out.append("")
        if imp.opaque:
            out += ["Name from data:", ""]
            out += [f"- {where_label(model, s.source_doc_id)}: {s.sink} `{_cell(s.expression[:80])}`"
                    f"{' (' + s.note + ')' if s.note else ''}" for s in imp.opaque[:50]]
            if len(imp.opaque) > 50:
                out.append(f"- … and {len(imp.opaque) - 50} more")
            out.append("")
    return "\n".join(out) + "\n"


def _cell(text: str) -> str:
    return " ".join(str(text).split("\n")).replace("|", "\\|")
