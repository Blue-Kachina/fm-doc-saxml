"""Data for the HTML viewer's WebMCP tools (``--webmcp``).

The tools (``templates/webmcp.js``) answer questions from the model, not from the
rendered Markdown, so the model is written next to the pages as classic scripts the
viewer loads on demand (file:// pages can't fetch()):

``_viewer/data/<file>/catalog.js``
    counts, plus one row per named entity for the search box: ``[docId, type, name, path]``
``_viewer/data/<file>/<entityType>.js``
    every entity of one type as a flat, queryable record (no ``sourceXml``)
``_viewer/data/<file>/refs.js``
    the reference graph, one row per edge, with the parent of each end
``_viewer/data/<file>/access.js``
    effective access per privilege set (analyze/access.py)

Records are the model's own JSON with a few derived fields an agent would otherwise
have to compute: the page ``path``, the parent's name, a layout object's hide condition
and the panel or popover it sits in. In a multi-file build every file gets its own
folder, keyed by its output folder name; paths are relative to the viewer's root.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ...analyze.access import build_access
from ...model.document_model import DocumentModel
from ...utils.file_writer import write_text
from ..markdown.link_resolver import LinkResolver
from .viewer import VIEWER_DIR, _js_literal

DATA_DIR = "data"

# Bulky or internal parts of an entity no question needs: the XML location and
# FileMaker's tokenized calcs.
_DROP = {"sourceXml", "chunkRefs"}
# Per type: child id lists the child type's shard already answers (fields by
# baseTableDocId, ...), and a step's raw parameter dicts (its text and calcs are kept).
_DROP_BY_TYPE = {
    "table": {"fields"},
    "layout": {"layoutObjects"},
    "script": {"steps"},
    "scriptStep": {"params", "parameters"},
}

# Containers whose contents only show when opened: tab and slide panels, popovers.
_PANEL_TYPES = {"Panel": "panel", "PopoverPanel": "popover"}


def write_webmcp_data(model: DocumentModel, output_dir: str | Any, *, file_key: str = "", prefix: str = "",
                      label: str = "", cross_file: Optional[dict[str, tuple[str, str]]] = None) -> dict[str, Any]:
    """Write one file's data under ``output_dir/_viewer/data/<file_key or '_'>/``.

    ``output_dir`` is the viewer's root (the batch root in a multi-file build) and
    ``prefix`` the file's folder inside it (``"Invoices/"``, or ``""``). Returns the
    manifest entry for the file.
    """
    from pathlib import Path

    root = Path(output_dir)
    key = file_key or "_"
    data_dir = root / VIEWER_DIR / DATA_DIR / key
    links = LinkResolver(model, cross_file)
    builder = _Builder(model, links, prefix, cross_file or {})

    counts: dict[str, int] = {}
    catalog: list[list[Any]] = []
    for entity_type, records in builder.records_by_type().items():
        counts[entity_type] = len(records)
        _write(data_dir / f"{entity_type}.js", f"FMDocs.shard({_js_literal(key)},{_js_literal(entity_type)},"
                                              f"{_js_literal(records, compact=True)});\n")
        for r in records:
            if entity_type != "scriptStep" and (r.get("name") or entity_type == "layoutObject" and r.get("label")):
                catalog.append([r["docId"], entity_type, r.get("label") or r["name"], r.get("path")])

    refs = builder.references()
    _write(data_dir / "refs.js", f"FMDocs.refs({_js_literal(key)},{_js_literal(refs, compact=True)});\n")
    _write(data_dir / "access.js", f"FMDocs.access({_js_literal(key)},{_js_literal(build_access(model), compact=True)});\n")

    info = {
        "key": key,
        "label": label or model.solution.name or model.source.file_name,
        "dir": prefix.rstrip("/"),
        "counts": counts,
        "references": len(refs["rows"]),
        "scrubbed": bool(model.scrubbing and model.scrubbing.applied),
    }
    _write(data_dir / "catalog.js", f"FMDocs.catalog({_js_literal(key)},{_js_literal({**info, 'index': catalog}, compact=True)});\n")
    return info


def _write(path, text: str) -> None:
    write_text(path, text)


class _Builder:
    def __init__(self, model: DocumentModel, links: LinkResolver, prefix: str,
                 cross_file: dict[str, tuple[str, str]]) -> None:
        self.model = model
        self.links = links
        self.prefix = prefix
        self.cross_file = cross_file
        em = model.entities
        self.parent_of: dict[str, str] = {}
        for f in em.fields.values():
            self.parent_of[f.doc_id] = f.base_table_doc_id
        for o in em.layout_objects.values():
            self.parent_of[o.doc_id] = o.layout_doc_id
        for s in em.script_steps.values():
            self.parent_of[s.doc_id] = s.script_doc_id

    def path(self, doc_id: Optional[str]) -> Optional[str]:
        """Page for ``doc_id`` relative to the viewer root (a step's is its script's page)."""
        if not doc_id:
            return None
        own = self.links.path_for(doc_id)
        if own is None and doc_id in self.parent_of:
            own = self.links.path_for(self.parent_of[doc_id])
        if own is not None:
            return self.prefix + own
        if doc_id in self.cross_file:
            return _join(self.prefix, self.cross_file[doc_id][0])
        return None

    def name(self, doc_id: Optional[str]) -> Optional[str]:
        return self.links.title_for(doc_id) if doc_id else None

    def records_by_type(self) -> dict[str, list[dict[str, Any]]]:
        em = self.model.entities
        out: dict[str, list[dict[str, Any]]] = {}
        for entity_map in (em.tables, em.fields, em.table_occurrences, em.relationships, em.layouts,
                           em.layout_objects, em.scripts, em.script_steps, em.custom_functions, em.value_lists,
                           em.privilege_sets, em.accounts, em.extended_privileges, em.custom_menus,
                           em.custom_menu_sets, em.themes, em.file_references, em.variables):
            for entity in entity_map.values():
                record = _clean(entity.model_dump(by_alias=True, exclude_none=True, mode="json"))
                for drop in _DROP_BY_TYPE.get(entity.entity_type, ()):
                    record.pop(drop, None)
                record["path"] = self.path(entity.doc_id)
                _DERIVE.get(entity.entity_type, _no_derive)(self, entity, record)
                out.setdefault(entity.entity_type, []).append(record)
        return out

    def references(self) -> dict[str, Any]:
        cols = ["source", "sourceType", "sourceParent", "target", "targetType", "targetParent",
                "relationshipType", "role", "confidence", "externalFile"]
        rows = []
        for r in self.model.references:
            ext = r.external_target
            target = r.target_doc_id
            rows.append([
                r.source_doc_id, r.source_entity_type, self.parent_of.get(r.source_doc_id),
                target, r.target_entity_type, self.parent_of.get(target) or _field_table(target),
                r.relationship_type, r.role, r.confidence, ext.data_source if ext is not None else None,
            ])
        # Names and pages of the ends that aren't entities of this file (other files' targets).
        names = {}
        for r in self.model.references:
            for d in (r.target_doc_id, r.source_doc_id):
                if d not in names and d in self.cross_file:
                    names[d] = [self.cross_file[d][1], _join(self.prefix, self.cross_file[d][0])]
                elif d not in names and r.external_target is not None and d == r.target_doc_id:
                    names[d] = [self.name(d), None]
        return {"cols": cols, "rows": rows, "external": names}


def _join(prefix: str, rel: str) -> str:
    """``prefix`` + a path relative to it that may climb out (``../Other/x.md``)."""
    parts = [p for p in prefix.split("/") if p]
    for seg in rel.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return "/".join(parts)


def _field_table(doc_id: str) -> Optional[str]:
    """``field:Invoices::Total`` -> ``table:Invoices`` (fields are keyed by their base table)."""
    if doc_id.startswith("field:") and "::" in doc_id:
        return "table:" + doc_id[len("field:"):].split("::", 1)[0]
    return None


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _DROP and v not in ([], {})}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Derived fields, per entity type
# ---------------------------------------------------------------------------

def _no_derive(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    return None


def _derive_field(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    r["table"] = b.name(e.base_table_doc_id)
    s = e.storage
    r["global"] = s.global_storage
    r["indexed"] = s.indexed
    if s.stored is not None:
        r["stored"] = s.stored
    r["autoEnterType"] = e.auto_enter.type if e.auto_enter else "none"
    r["hasValidation"] = e.validation is not None


def _derive_layout(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    r["baseTableOccurrence"] = b.name(e.base_table_occurrence_doc_id)
    r["objectCount"] = len(e.layout_objects)
    r["triggerEvents"] = [t.event for t in e.script_triggers]


def _derive_layout_object(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    em = b.model.entities
    r["layoutName"] = b.name(e.layout_doc_id)
    r["label"] = e.name or e.raw_text or None
    roles: dict[str, str] = {}
    for c in e.calculations:
        roles.setdefault(c.role, c.text)
    r["hasHideCondition"] = "hideCondition" in roles
    if "hideCondition" in roles:
        r["hideCondition"] = roles["hideCondition"]
    if "tooltip" in roles:
        r["tooltip"] = roles["tooltip"]
    r["hasConditionalFormatting"] = "conditionalFormatting" in roles
    r["isField"] = bool(e.field_doc_id or (e.external_target and e.external_target.target_type == "field"))
    if e.field_doc_id:
        r["fieldName"] = b.name(e.field_doc_id)
    r["triggerEvents"] = [t.event for t in e.script_triggers]
    # The tab/slide panel or popover the object only shows in, nearest first.
    containers = []
    parent = em.layout_objects.get(e.parent_object_doc_id) if e.parent_object_doc_id else None
    seen = set()
    while parent is not None and parent.doc_id not in seen:
        seen.add(parent.doc_id)
        kind = _PANEL_TYPES.get(parent.object_type)
        if kind == "panel":
            control = em.layout_objects.get(parent.parent_object_doc_id or "")
            kind = "slidePanel" if control is not None and control.object_type == "Slide Control" else "tabPanel"
        if kind:
            containers.append({"docId": parent.doc_id, "kind": kind, "name": parent.name or None})
        parent = em.layout_objects.get(parent.parent_object_doc_id) if parent.parent_object_doc_id else None
    if containers:
        r["shownIn"] = containers
    r["inPanel"] = bool(containers)


def _derive_script(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    r["stepCount"] = len(e.steps)


def _derive_step(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    script = b.model.entities.scripts.get(e.script_doc_id)
    r["scriptName"] = script.name if script else b.name(e.script_doc_id)
    if script is not None and script.folder_path:
        r["scriptFolder"] = script.folder_path
    r["stepNumber"] = e.index + 1
    r["text"] = e.fm_text or e.raw_text or e.name
    r.pop("rawText", None)
    targets = [ref.get("targetDocId") for ref in e.references if ref.get("targetDocId")]
    if targets:
        r["targets"] = targets


def _derive_table_occurrence(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    r["baseTable"] = b.name(e.base_table_doc_id)


def _derive_account(b: _Builder, e: Any, r: dict[str, Any]) -> None:
    r["external"] = e.account_type != "FileMaker"


_DERIVE: dict[str, Callable[[_Builder, Any, dict[str, Any]], None]] = {
    "field": _derive_field,
    "layout": _derive_layout,
    "layoutObject": _derive_layout_object,
    "script": _derive_script,
    "scriptStep": _derive_step,
    "tableOccurrence": _derive_table_occurrence,
    "account": _derive_account,
}
