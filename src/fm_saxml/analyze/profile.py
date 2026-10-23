"""Solution profile: the numbers behind Reports/profile.md.

A one-page overview of one file's structure for someone (or an agent) meeting the
solution for the first time: what the data model looks like, how big the scripts are and
which ones start a chain, what the layouts show, where the file talks to the outside, and
what looks unused. Every number comes from the normalized model and its backlinks; nothing
is guessed from names (no PK/FK or naming-style heuristics).

"Unused" uses the same rule as the UNUSED_FIELD_CANDIDATE warning: no backlink other than
structure (a table containing its field, a TO based on a table...). Backlinks include uses
from other files of a multi-file build. Calls by calculated name, server schedules and
fmp:// URLs are invisible, so these are candidates, not verdicts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..model.document_model import DocumentModel

# Backlinks that describe structure, not use
STRUCTURAL = {"contains", "basedOnTableOccurrence", "basedOnBaseTable", "joinsTo",
              "assignedPrivilegeSet", "grantedTo"}

# Script steps that reach outside the file
EXTERNAL_STEPS = (
    "Insert from URL", "Send Mail", "Open URL", "Execute SQL", "Execute FileMaker Data API",
    "Perform Script on Server", "Perform Script on Server with Callback", "Import Records",
    "Export Records", "Export Field Contents", "Save Records as PDF", "Save Records as Excel",
    "Send Event", "Perform AppleScript", "Perform JavaScript in Web Viewer",
)

# What runs a script that no script of this file performs, by backlink source
RUN_BY = {"layoutObject": "button or object trigger", "layout": "layout trigger",
          "fileOptions": "file trigger", "customMenu": "custom menu"}

HUB_DEGREE = 5      # a TO in at least this many relationships is a hub
LARGEST = 10        # scripts listed as largest


@dataclass
class Profile:
    tables: list[dict] = field(default_factory=list)          # name, fields, data_types, field_types
    relationships: dict = field(default_factory=dict)
    graph: dict = field(default_factory=dict)
    scripts: dict = field(default_factory=dict)
    layouts: dict = field(default_factory=dict)
    value_lists: dict = field(default_factory=dict)
    external_calls: list[dict] = field(default_factory=list)  # step, count, scripts
    unused: dict = field(default_factory=dict)                # kind -> sorted names


def _uses(model: DocumentModel, doc_id: str) -> list[dict]:
    return [b for b in model.backlinks.get(doc_id, []) if b.get("relationshipType") not in STRUCTURAL]


def _name(entity, doc_id: str = "") -> str:
    return getattr(entity, "name", None) or doc_id.split(":", 1)[-1]


def build_profile(model: DocumentModel) -> Profile:
    e = model.entities
    p = Profile()

    # -- data model -------------------------------------------------------------------
    by_table: dict[str, list] = defaultdict(list)
    for f in e.fields.values():
        by_table[f.base_table_doc_id].append(f)
    for doc_id, t in sorted(e.tables.items(), key=lambda kv: kv[1].name.casefold()):
        fields = by_table.get(doc_id, [])
        p.tables.append({
            "name": t.name,
            "fields": len(fields),
            "data_types": Counter(f.data_type for f in fields if f.data_type).most_common(),
            "field_types": Counter(f.field_type for f in fields if f.field_type).most_common(),
        })

    tos = e.table_occurrences
    rels = list(e.relationships.values())
    operators: Counter = Counter()
    self_joins = multi = 0
    cascade = {"create": {"left": 0, "right": 0}, "delete": {"left": 0, "right": 0}}
    sorted_rels = 0
    degree: Counter = Counter()
    for r in rels:
        ops = {pr.operator for pr in r.predicates}
        operators[" / ".join(sorted(ops)) if ops else "(none)"] += 1
        multi += len(r.predicates) > 1
        left, right = tos.get(r.left_table_occurrence_doc_id), tos.get(r.right_table_occurrence_doc_id)
        if left and right and left.base_table_doc_id and left.base_table_doc_id == right.base_table_doc_id:
            self_joins += 1
        for side in ("left", "right"):
            opts = getattr(r.options, side)
            if opts is not None:
                cascade["create"][side] += opts.allow_create
                cascade["delete"][side] += opts.delete
                sorted_rels += bool(opts.sort)
        degree[r.left_table_occurrence_doc_id] += 1
        degree[r.right_table_occurrence_doc_id] += 1
    p.relationships = {"total": len(rels), "operators": operators.most_common(), "multi_predicate": multi,
                       "self_joins": self_joins, "cascade": cascade, "sorted_sides": sorted_rels}

    degrees = [degree.get(d, 0) for d in tos]
    tables_with_tos = defaultdict(list)
    for d, to in tos.items():
        if to.base_table_doc_id:
            tables_with_tos[to.base_table_doc_id].append(d)
    p.graph = {
        "tos": len(tos),
        "avg_degree": round(sum(degrees) / len(degrees), 1) if degrees else 0,
        "max_degree": max(degrees, default=0),
        "hubs": sorted(((_name(tos[d], d), n) for d, n in degree.items() if n >= HUB_DEGREE and d in tos),
                       key=lambda x: (-x[1], x[0].casefold())),
        "isolated_tos": sorted(_name(to, d) for d, to in tos.items() if degree.get(d, 0) == 0),
        # tables none of whose TOs is in a relationship
        "disconnected_tables": sorted(t.name for d, t in e.tables.items()
                                      if not any(degree.get(to, 0) for to in tables_with_tos.get(d, []))),
        "hub_degree": HUB_DEGREE,
    }

    # -- scripts ----------------------------------------------------------------------
    steps_by_script = {d: len(s.steps) for d, s in e.scripts.items()}
    callers: dict[str, set] = defaultdict(set)      # callee docId -> caller script docIds (this file)
    for st in e.script_steps.values():
        for ref in st.references:
            if ref.get("kind") == "script" and ref.get("targetDocId") in e.scripts:
                callers[ref["targetDocId"]].add(st.script_doc_id)
    edges = sum(len(c) for c in callers.values())
    run_otherwise = {}
    for d in e.scripts:
        if callers.get(d):
            continue
        how = set()
        for b in _uses(model, d):
            if "/" in b.get("sourceDocId", ""):
                how.add("another file")
            elif b.get("sourceEntityType") != "scriptStep":
                how.add(RUN_BY.get(b.get("sourceEntityType"), b.get("sourceEntityType") or "?"))
        run_otherwise[d] = sorted(how)
    p.scripts = {
        "total": len(e.scripts),
        "steps": sum(steps_by_script.values()),
        "avg_steps": round(sum(steps_by_script.values()) / len(steps_by_script), 1) if steps_by_script else 0,
        "max_steps": max(steps_by_script.values(), default=0),
        "largest": [(_name(e.scripts[d], d), n) for d, n in
                    sorted(steps_by_script.items(), key=lambda kv: (-kv[1], _name(e.scripts[kv[0]]).casefold()))[:LARGEST]],
        "folders": sorted(Counter(s.folder_path or "(top level)" for s in e.scripts.values()).items(),
                          key=lambda kv: kv[0].casefold()),
        "call_edges": edges,
        # not called by another script of this file: what starts them, if anything we can see
        "entry_points": sorted(((_name(e.scripts[d], d), how) for d, how in run_otherwise.items() if how),
                               key=lambda x: x[0].casefold()),
    }

    # -- layouts ----------------------------------------------------------------------
    portals = []
    for o in e.layout_objects.values():
        if (o.object_type or "").lower() == "portal":
            lay = e.layouts.get(o.layout_doc_id)
            to = tos.get(o.table_occurrence_doc_id or "")
            portals.append((_name(lay, o.layout_doc_id), _name(to, o.table_occurrence_doc_id or "") or "(unknown)"))
    navigated = {d for d in e.layouts
                 if any(b.get("relationshipType") in ("usesLayout", "opensLayout", "navigatesTo", "opensWindowOn")
                        for b in model.backlinks.get(d, []))}
    if model.file_options is not None and model.file_options.default_layout:
        navigated.add(model.file_options.default_layout)
    p.layouts = {
        "total": len(e.layouts),
        "by_base_to": sorted(Counter(_name(tos.get(lay.base_table_occurrence_doc_id or ""), lay.base_table_occurrence_doc_id or "")
                                     or "(none)" for lay in e.layouts.values()).items(),
                             key=lambda kv: (-kv[1], kv[0].casefold())),
        "folders": sorted(Counter(lay.folder_path or "(top level)" for lay in e.layouts.values()).items(),
                          key=lambda kv: kv[0].casefold()),
        "portals": sorted(portals, key=lambda x: (x[0].casefold(), x[1].casefold())),
        "not_navigated": sorted(lay.name for d, lay in e.layouts.items() if d not in navigated),
    }

    p.value_lists = {"total": len(e.value_lists),
                     "by_type": Counter(v.list_type or "(unknown)" for v in e.value_lists.values()).most_common()}

    # -- integrations -----------------------------------------------------------------
    calls: dict[str, Counter] = defaultdict(Counter)
    for st in e.script_steps.values():
        if st.name in EXTERNAL_STEPS and st.enabled:
            calls[st.name][_name(e.scripts.get(st.script_doc_id), st.script_doc_id)] += 1
    p.external_calls = [{"step": s, "count": sum(calls[s].values()),
                         "scripts": sorted(calls[s], key=str.casefold)}
                        for s in EXTERNAL_STEPS if s in calls]

    # -- unused candidates ------------------------------------------------------------
    p.unused = {
        "fields": sorted(f.qualified_name for d, f in e.fields.items() if not _uses(model, d)),
        "scripts": sorted(s.name for d, s in e.scripts.items() if not _uses(model, d)),
        "layouts": sorted(lay.name for d, lay in e.layouts.items() if not _uses(model, d) and d not in navigated),
        "value_lists": sorted(v.name for d, v in e.value_lists.items() if not _uses(model, d)),
        "custom_functions": sorted(c.name for d, c in e.custom_functions.items() if not _uses(model, d)),
    }
    return p
