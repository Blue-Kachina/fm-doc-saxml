"""Pair the files of a multi-file build and resolve references between them.

Each file was analyzed on its own, so a reference into another file is an
``external`` ReferenceRecord whose target docId is provisional
(``ds:<data source uuid>/<docId>``). Here we work out which batch file each
external data source names, find the target in that file's model, and produce
what the renderer needs to link across output folders:

- per file, a ``cross_file`` map of provisional docId -> (path from this file's
  folder, title), passed to ``LinkResolver``;
- backlinks added to the target file's model, keyed ``xfile:<folder>/<docId>``,
  which are in the same map so "Referenced by" rows link back.

Pairing uses the data source's file path (``file:Clients`` -> ``Clients.fmp12``).
The data source's UUID is its own, defined in the referencing file, so it never
equals the target file's UUID (see ``multi_file_saxml.md`` section 1.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..model.document_model import DocumentModel
from ..model.references import ExternalTarget, ReferenceRecord
from ..render.markdown.link_resolver import LinkResolver


@dataclass
class BatchFile:
    """One analyzed file of the batch, with the output folder it renders into."""

    folder: str           # output subfolder name (safe_slug of the FileMaker file name)
    name: str             # FileMaker file name without extension
    model: DocumentModel


@dataclass
class DataSourcePairing:
    source: str                    # folder of the file that defines the data source
    data_source: str
    paths: list[str]
    target: Optional[str] = None   # folder of the paired file
    match: str = ""                # "path" or "name" (weak) when paired
    reason: str = ""               # why it isn't paired


@dataclass
class CrossReference:
    source: str                    # folder of the referencing file
    ref: ReferenceRecord
    target: Optional[str] = None   # folder of the target file, when the data source is paired
    target_doc_id: Optional[str] = None  # docId inside the target file, when found
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.target_doc_id is not None


@dataclass
class BatchLinks:
    pairings: list[DataSourcePairing] = field(default_factory=list)
    references: list[CrossReference] = field(default_factory=list)
    cross_file: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)

    @property
    def resolved(self) -> list[CrossReference]:
        return [r for r in self.references if r.resolved]

    @property
    def unresolved(self) -> list[CrossReference]:
        return [r for r in self.references if not r.resolved]

    @property
    def unpaired(self) -> list[DataSourcePairing]:
        return [p for p in self.pairings if p.target is None]

    def references_between(self) -> dict[str, set[str]]:
        """folder -> folders it has at least one resolved reference into."""
        out: dict[str, set[str]] = {}
        for r in self.resolved:
            if r.target != r.source:
                out.setdefault(r.source, set()).add(r.target)
        return out


def link_batch(files: list[BatchFile]) -> BatchLinks:
    """Pair data sources, resolve external references and add cross-file backlinks."""
    links = BatchLinks(cross_file={f.folder: {} for f in files})
    by_folder = {f.folder: f for f in files}
    resolvers = {f.folder: LinkResolver(f.model) for f in files}
    indexes = {f.folder: _TargetIndex(f.model) for f in files}

    pair_of: dict[tuple[str, str], DataSourcePairing] = {}
    for f in files:
        for ds in f.model.external_data_sources:
            p = _pair(f, ds.name, ds.type, ds.paths, files)
            links.pairings.append(p)
            pair_of[(f.folder, ds.name.casefold())] = p

    incoming: dict[str, dict[tuple, dict]] = {f.folder: {} for f in files}
    for f in files:
        for ref in f.model.references:
            t = ref.external_target
            if ref.confidence != "external" or t is None:
                continue
            pairing = pair_of.get((f.folder, t.data_source.casefold()))
            xref = CrossReference(source=f.folder, ref=ref)
            links.references.append(xref)
            if pairing is None or pairing.target is None:
                xref.reason = pairing.reason if pairing else f"no data source named {t.data_source!r}"
                continue
            other = by_folder[pairing.target]
            xref.target = other.folder
            xref.target_doc_id = find_target(other.model, t, indexes[other.folder])
            if xref.target_doc_id is None:
                xref.reason = f"no {t.target_type} {_label(t)!r} in {other.name}"
                continue

            path = resolvers[other.folder].path_for(xref.target_doc_id)
            title = resolvers[other.folder].title_for(xref.target_doc_id)
            if other is f:
                # A data source naming its own file: the target is a page of this file
                if path is not None:
                    links.cross_file[f.folder][ref.target_doc_id] = (path, title)
                incoming[f.folder].setdefault((xref.target_doc_id, ref.source_doc_id, ref.relationship_type, ref.role), {
                    "sourceDocId": ref.source_doc_id, "sourceEntityType": ref.source_entity_type,
                    "relationshipType": ref.relationship_type, "role": ref.role, "confidence": "external",
                })
                continue
            if path is not None:
                links.cross_file[f.folder][ref.target_doc_id] = (f"../{other.folder}/{path}", f"{title} ({other.name})")
            _add_backlink(incoming[other.folder], f, ref, xref.target_doc_id, resolvers[f.folder], links.cross_file[other.folder])

    for folder, backlinks in incoming.items():
        model = by_folder[folder].model
        used = set()
        for (target_doc_id, *_), entry in backlinks.items():
            model.backlinks.setdefault(target_doc_id, []).append(entry)
            used.add(target_doc_id)
        # Analyzed alone, a field used only through a data source looked unused
        model.warnings = [
            w for w in model.warnings if not (w.code == "UNUSED_FIELD_CANDIDATE" and w.entity_doc_id in used)
        ]
    return links


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

_SCHEME_RE = re.compile(r"^[A-Za-z]+:")


def path_file_names(paths: list[str]) -> list[str]:
    """File names (no extension, casefolded) that a data source's paths point at.

    A ``UniversalPathList`` may hold several paths, one per line, tried in order.
    Paths built from variables (``$path``) can't be paired and are left out.
    """
    names = []
    for entry in paths:
        for line in entry.splitlines():
            line = line.strip()
            if not line or "$" in line:
                continue
            seg = _SCHEME_RE.sub("", line).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            for ext in (".fmp12", ".fmp7"):
                if seg.lower().endswith(ext):
                    seg = seg[: -len(ext)]
            if seg:
                names.append(seg.casefold())
    return names


def _pair(f: BatchFile, ds_name: str, ds_type: str, paths: list[str], files: list[BatchFile]) -> DataSourcePairing:
    p = DataSourcePairing(source=f.folder, data_source=ds_name, paths=list(paths))
    if ds_type and ds_type.lower() != "filemaker":
        p.reason = f"{ds_type} data source"
        return p
    wanted = path_file_names(paths)
    hits = [o for o in files if o.name.casefold() in wanted]
    p.match = "path"
    if not hits and not paths:
        hits = [o for o in files if o.name.casefold() == ds_name.casefold()]
        p.match = "name"
    distinct = {o.folder for o in hits}
    if len(distinct) > 1:
        p.match, p.reason = "", "ambiguous: matches " + ", ".join(sorted(distinct))
    elif not hits:
        p.match = ""
        if paths and not wanted:
            p.reason = "path is built from a variable"
        else:
            p.reason = "file not in this build"
    else:
        p.target = hits[0].folder
        if p.target == f.folder:
            p.match = f"{p.match} (its own file)"
    return p


# ---------------------------------------------------------------------------
# Finding a target in its file: uuid, then fmpId, then name
# ---------------------------------------------------------------------------

def find_target(model: DocumentModel, t: ExternalTarget, index: Optional["_TargetIndex"] = None) -> Optional[str]:
    """The docId ``t`` names inside ``model``, or None. Pass ``index`` when looking up many targets."""
    ix = index or _TargetIndex(model)
    if t.target_type == "table":
        return ix.tables.find(t.uuid or t.base_table_uuid, t.fmp_id or t.base_table_id, t.name)
    if t.target_type == "script":
        return ix.scripts.find(t.uuid, t.fmp_id, t.name)
    if t.target_type == "layout":
        return ix.layouts.find(t.uuid, t.fmp_id, t.name)
    if t.target_type == "field":
        if t.uuid and t.uuid in ix.field_by_uuid:
            return ix.field_by_uuid[t.uuid]
        table = ix.tables.find(t.base_table_uuid, t.base_table_id, t.base_table)
        fields = ix.fields_by_table.get(table) if table else None
        return fields.find(None, t.fmp_id, t.name) if fields else None
    return None


class _Lookup:
    """Entities by uuid, fmpId and (casefolded) name; the first entity wins each key."""

    def __init__(self, entities) -> None:
        self.uuid: dict[str, str] = {}
        self.fmp_id: dict[str, str] = {}
        self.name: dict[str, str] = {}
        for e in entities:
            if e.uuid:
                self.uuid.setdefault(e.uuid, e.doc_id)
            if e.fmp_id:
                self.fmp_id.setdefault(str(e.fmp_id), e.doc_id)
            self.name.setdefault(e.name.casefold(), e.doc_id)

    def find(self, uuid: Optional[str], fmp_id: Optional[str], name: Optional[str]) -> Optional[str]:
        return ((uuid and self.uuid.get(uuid)) or (fmp_id and self.fmp_id.get(str(fmp_id)))
                or (name and self.name.get(name.casefold())) or None)


class _TargetIndex:
    def __init__(self, model: DocumentModel) -> None:
        em = model.entities
        self.tables = _Lookup(em.tables.values())
        self.scripts = _Lookup(em.scripts.values())
        self.layouts = _Lookup(em.layouts.values())
        self.field_by_uuid = {f.uuid: f.doc_id for f in em.fields.values() if f.uuid}
        by_table: dict[str, list] = {}
        for f in em.fields.values():
            by_table.setdefault(f.base_table_doc_id, []).append(f)
        self.fields_by_table = {table: _Lookup(fields) for table, fields in by_table.items()}


def _label(t: ExternalTarget) -> str:
    if t.target_type == "field" and (t.base_table or t.table_occurrence):
        return f"{t.base_table or t.table_occurrence}::{t.name}"
    return t.name


# ---------------------------------------------------------------------------
# Backlinks from other files
# ---------------------------------------------------------------------------

def _add_backlink(
    into: dict[tuple, dict], source: BatchFile, ref: ReferenceRecord, target_doc_id: str,
    source_links: LinkResolver, target_cross_file: dict[str, tuple[str, str]],
) -> None:
    """Record ``ref`` as a backlink on its target in the other file.

    Layout objects have no page of their own in "Used By" tables, so they are
    reported as their layout, like references made by the layout itself.
    """
    em = source.model.entities
    src_id, src_type = ref.source_doc_id, ref.source_entity_type
    if src_type == "layoutObject" and src_id in em.layout_objects:
        src_id, src_type = em.layout_objects[src_id].layout_doc_id, "layout"
    page_id = src_id
    if src_type == "scriptStep" and src_id in em.script_steps:
        page_id = em.script_steps[src_id].script_doc_id

    key = f"xfile:{source.folder}/{src_id}"
    path = source_links.path_for(page_id)
    if path is not None:
        target_cross_file[key] = (f"../{source.folder}/{path}", f"{source_links.title_for(src_id)} ({source.name})")
    into.setdefault((target_doc_id, key, ref.relationship_type, ref.role), {
        "sourceDocId": key,
        "sourceEntityType": src_type,
        "relationshipType": ref.relationship_type,
        "role": ref.role,
        "confidence": "external",
    })
