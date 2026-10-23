"""Read converted docs from Python, without parsing JSON by hand.

    import fm_saxml

    docs = fm_saxml.load("exports/Invoices_docs")      # one file's docs -> SolutionDocs
    docs.entities.scripts["script:Post Invoice"]       # typed entities, the converter's own classes
    docs.find("script", "post invoice")                # case-insensitive, every match
    docs.refs_to("field:Invoices::Total")              # what uses it

    batch = fm_saxml.load("exports/Accounting")        # a multi-file build -> BatchDocs
    batch["Invoices"].entities.layouts
    batch.resolve("ds:EEC9827D-…/field:Clients::Name") # a reference into another file

    fm_saxml.find_docs("Invoices")                     # by solution name, under $FM_SAXML_DOCS_ROOT

Files are read when first used, upgraded in memory if an older fm-saxml wrote them
(``contract_migrations``), and validated against the contract models. A file written
by a newer major version raises ``ContractVersionError``. See docs/contract.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Optional, Union

import orjson
from pydantic import BaseModel

from .contract import CONTRACT_VERSION, RAW_DIR, ROOT_CATALOG, raw_file_for
from .contract_migrations import ContractVersionError, file_version, read_contract_file
from .contract_models import (
    Backlink, ContractSource, DocsCatalog, EntitiesDoc, ExternalReferencesDoc, RawXmlDoc,
)
from .model.references import ReferenceRecord

DOCS_ROOT_ENV = "FM_SAXML_DOCS_ROOT"


class DocsNotFoundError(FileNotFoundError):
    """No fm-saxml docs where they were looked for."""


class RawXmlNotFoundError(LookupError):
    """These docs have no raw XML for the docId (or none at all)."""


# docId prefix -> entities.json collection
PREFIXES: dict[str, str] = {
    "table": "tables",
    "field": "fields",
    "to": "tableOccurrences",
    "relationship": "relationships",
    "layout": "layouts",
    "layoutObject": "layoutObjects",
    "script": "scripts",
    "scriptStep": "scriptSteps",
    "customFunction": "customFunctions",
    "valueList": "valueLists",
    "privilegeSet": "privilegeSets",
    "account": "accounts",
    "extPriv": "extendedPrivileges",
    "customMenu": "customMenus",
    "customMenuSet": "customMenuSets",
    "theme": "themes",
    "fileRef": "fileReferences",
    "variable": "variables",
    "dataSource": "externalDataSources",
}
# Other words find() accepts for a kind
_KIND_ALIASES = {
    "tableoccurrence": "tableOccurrences", "object": "layoutObjects", "step": "scriptSteps",
    "cf": "customFunctions", "extendedprivilege": "extendedPrivileges", "filereference": "fileReferences",
    "externaldatasource": "externalDataSources", "datasource": "externalDataSources",
}


def _collection_for(kind: str) -> str:
    """A kind as a docId prefix, a collection name or a plain word -> the collection's key."""
    by_key = {c.casefold(): c for c in PREFIXES.values()}
    by_key.update({p.casefold(): c for p, c in PREFIXES.items()})
    by_key.update(_KIND_ALIASES)
    k = kind.strip().replace(" ", "").replace("_", "").casefold()
    found = by_key.get(k) or by_key.get(k.rstrip("s"))
    if found is None:
        raise ValueError(f"unknown kind {kind!r}; use one of: {', '.join(PREFIXES)}")
    return found


def _attr_for(collection: str) -> str:
    """Collection key (alias) -> EntitiesDoc attribute name."""
    for name, info in EntitiesDoc.model_fields.items():
        if (info.alias or name) == collection:
            return name
    raise KeyError(collection)


def _names_of(entity: BaseModel) -> list[str]:
    """The names an entity answers to in find(): its name, plus a field's Table::Field and a theme's display name."""
    out = []
    for attr in ("name", "qualified_name", "display_name"):
        value = getattr(entity, attr, None)
        if isinstance(value, str) and value:
            out.append(value.casefold())
    return out


class SolutionDocs:
    """One FileMaker file's docs: the four contract files in ``path``."""

    def __init__(self, path: Union[str, Path], catalog: Optional[DocsCatalog] = None) -> None:
        self.path = Path(path)
        self.catalog = catalog  # docs.json, when this folder is an output root
        self._raw: dict[str, dict[str, str]] = {}  # raw/*.json, by file name, read on first use

    def __repr__(self) -> str:
        return f"SolutionDocs({str(self.path)!r})"

    def _read(self, file_name: str):
        path = self.path / file_name
        if not path.is_file():
            raise DocsNotFoundError(f"{path} not found: {self.path} is not a complete fm-saxml docs folder "
                                    "(build it again without --no-include-json)")
        return read_contract_file(path)

    @cached_property
    def entities(self) -> EntitiesDoc:
        return self._read("entities.json")

    @cached_property
    def external(self) -> ExternalReferencesDoc:
        return self._read("external-references.json")

    @cached_property
    def references(self) -> list[ReferenceRecord]:
        return self._read("references.json").references

    @cached_property
    def backlinks(self) -> dict[str, list[Backlink]]:
        return self._read("backlinks.json").backlinks

    @property
    def schema_version(self) -> str:
        return self.entities.schema_version

    @property
    def source(self) -> ContractSource:
        """Which FileMaker file this is. Docs upgraded from before the contract take it from external-references."""
        src = self.entities.source
        if src.fmp_file_name is None and src.file_uuid is None and (self.path / "external-references.json").is_file():
            return self.external.source
        return src

    @property
    def name(self) -> str:
        """The FileMaker file name without extension, else the folder name."""
        fmp = self.source.fmp_file_name or ""
        for ext in (".fmp12", ".fmp7"):
            if fmp.lower().endswith(ext):
                return fmp[: -len(ext)]
        return fmp or self.path.name

    # -- lookups ------------------------------------------------------------------

    def collection(self, kind: str) -> dict[str, Any]:
        """``{docId: entity}`` of one kind: ``"script"``, ``"scripts"``, ``"tableOccurrence"``, ..."""
        return getattr(self.entities, _attr_for(_collection_for(kind)))

    def get(self, doc_id: str) -> Optional[BaseModel]:
        """The entity with this (unscoped) docId, or None."""
        prefix = doc_id.split(":", 1)[0]
        if prefix in PREFIXES:
            return getattr(self.entities, _attr_for(PREFIXES[prefix])).get(doc_id)
        if "#ind" in doc_id:
            return self.entities.indirection_sites.get(doc_id)
        return None

    def raw_xml(self, doc_id: str) -> str:
        """The scrubbed XML of a script, step, layout, layout object, theme, custom menu or menu set.

        It's the export's own element (re-serialized, scrubbed like the pages), for tools that
        build something to paste back into FileMaker. A step's XML is cut from its script's, and
        a layout object's from its layout's. ``raw/*.json`` is read only when first needed.
        """
        file_name = raw_file_for(doc_id)
        if file_name is None:
            raise RawXmlNotFoundError(f"{doc_id}: only scripts, steps, layouts, layout objects, themes, "
                                      "custom menus and menu sets have raw XML")
        prefix = doc_id.split(":", 1)[0]
        xml = self._raw_file(file_name)
        if prefix not in ("scriptStep", "layoutObject"):
            if doc_id not in xml:
                raise RawXmlNotFoundError(f"{doc_id} isn't in {self.path / RAW_DIR / file_name}")
            return xml[doc_id]

        from lxml import etree

        entity = self.get(doc_id)
        if entity is None:
            raise RawXmlNotFoundError(f"{doc_id} isn't in these docs")
        if prefix == "scriptStep":
            parent_id, match = entity.script_doc_id, ("Step", "index", str(entity.index))
        else:
            parent_id, match = entity.layout_doc_id, ("LayoutObject", "id", entity.object_id)
        parent = etree.fromstring(self.raw_xml(parent_id))
        tag, attr, value = match
        for el in parent.iter(tag):
            if el.get(attr) == value:
                return etree.tostring(el, encoding="unicode", with_tail=False)
        raise RawXmlNotFoundError(f"{doc_id}: no <{tag} {attr}=\"{value}\"> in {parent_id}'s raw XML")

    def _raw_file(self, file_name: str) -> dict[str, str]:
        if file_name not in self._raw:
            path = self.path / RAW_DIR / file_name
            if not path.is_file():
                raise RawXmlNotFoundError(
                    f"{path} not found: these docs have no raw XML. Build them from the export without "
                    "--no-raw-xml (a render from model.json has no export to read).")
            data = orjson.loads(path.read_bytes())
            major = file_version(data)[0]
            if major > CONTRACT_VERSION[0]:
                raise ContractVersionError(f"{path}: docs written by schema {major}.x; "
                                           f"this fm-saxml reads up to {CONTRACT_VERSION[0]}.x — upgrade fm-saxml")
            self._raw[file_name] = RawXmlDoc.model_validate(data).xml
        return self._raw[file_name]

    def find(self, kind: str, name: str) -> list[BaseModel]:
        """Every entity of ``kind`` named ``name``, ignoring case. Fields also match ``Table::Field``."""
        wanted = name.strip().casefold()
        return [e for e in self.collection(kind).values() if wanted in _names_of(e)]

    @cached_property
    def _refs_by_source(self) -> dict[str, list[ReferenceRecord]]:
        out: dict[str, list[ReferenceRecord]] = {}
        for r in self.references:
            out.setdefault(r.source_doc_id, []).append(r)
        return out

    @cached_property
    def _refs_by_target(self) -> dict[str, list[ReferenceRecord]]:
        out: dict[str, list[ReferenceRecord]] = {}
        for r in self.references:
            out.setdefault(r.target_doc_id, []).append(r)
        return out

    def refs_from(self, doc_id: str) -> list[ReferenceRecord]:
        """References this entity makes."""
        return list(self._refs_by_source.get(doc_id, []))

    def refs_to(self, doc_id: str) -> list[ReferenceRecord]:
        """References to this entity from this file. ``backlinks`` also has those from other files of a batch."""
        return list(self._refs_by_target.get(doc_id, []))

    def to_document_model(self):
        """The converter's ``DocumentModel``, rebuilt from the docs (no warnings, scrub summary or coverage)."""
        from .model.document_model import DocumentModel, EntityMaps, SolutionInfo, SourceInfo

        e, src = self.entities, self.source
        return DocumentModel(
            source=SourceInfo(fileName=src.fmp_file_name or self.path.name,
                              fileMakerVersion=src.file_maker_version or "unknown",
                              saxmlVersion=src.saxml_version, hasDdrInfo=src.has_ddr_info,
                              fmpFileName=src.fmp_file_name,
                              fileUuid=src.file_uuid, scope=src.scope),
            solution=SolutionInfo(name=self.name),
            entities=EntityMaps(**{n: getattr(e, n) for n in EntityMaps.model_fields}),
            external_data_sources=list(e.external_data_sources.values()),
            file_options=e.file_options,
            graph_notes=e.graph_notes,
            references=self.references,
            indirectionSites=list(e.indirection_sites.values()),
            backlinks={k: [b.model_dump(by_alias=True, exclude_unset=True) for b in v]
                       for k, v in self.backlinks.items()},
        )


@dataclass
class ResolvedRef:
    """Where a scoped docId points: the file's docs, the docId inside it, and the entity (None if absent)."""

    file: SolutionDocs
    doc_id: str
    entity: Optional[BaseModel]


def _unescape_scope(text: str) -> str:
    return text.replace("%2F", "/").replace("%2f", "/").replace("%25", "%")


class BatchDocs(Mapping):
    """A multi-file build: each file's ``SolutionDocs``, by FileMaker file name (case-insensitive)."""

    def __init__(self, path: Union[str, Path], catalog: Optional[DocsCatalog] = None) -> None:
        self.path = Path(path)
        self.catalog = catalog
        if catalog is not None:
            self._files = {f.name: SolutionDocs(self.path / f.folder) for f in catalog.files}
            self._folders = {f.folder: f.name for f in catalog.files}
        else:  # built before docs.json existed: every subfolder with docs
            subs = sorted(d for d in self.path.iterdir() if (d / "entities.json").is_file())
            self._files = {d.name: SolutionDocs(d) for d in subs}
            self._folders = {d.name: d.name for d in subs}

    def __repr__(self) -> str:
        return f"BatchDocs({str(self.path)!r}, files={list(self._files)})"

    def __getitem__(self, name: str) -> SolutionDocs:
        if name in self._files:
            return self._files[name]
        key = name.casefold()
        for ext in (".fmp12", ".fmp7"):
            if key.endswith(ext):
                key = key[: -len(ext)]
        for n, docs in self._files.items():
            if n.casefold() == key:
                return docs
        if name in self._folders:
            return self._files[self._folders[name]]
        raise KeyError(f"{name!r} is not in {self.path} (files: {', '.join(self._files)})")

    def __iter__(self) -> Iterator[str]:
        return iter(self._files)

    def __len__(self) -> int:
        return len(self._files)

    @property
    def solution(self) -> str:
        return self.catalog.solution if self.catalog else self.path.name

    def _by_uuid(self, uuid: str) -> Optional[SolutionDocs]:
        for f in (self.catalog.files if self.catalog else []):
            if f.file_uuid and f.file_uuid.casefold() == uuid.casefold():
                return self._files[f.name]
        for docs in self._files.values():
            if docs.source.file_uuid and docs.source.file_uuid.casefold() == uuid.casefold():
                return docs
        return None

    def _by_data_source(self, key: str) -> Optional[SolutionDocs]:
        """The file a data source (by UUID, else by name) of any file in the batch is paired with."""
        k = key.casefold()
        if self.catalog is not None:
            for p in self.catalog.pairings:
                if p.target_folder and k in ((p.data_source_uuid or "").casefold(), p.data_source.casefold()):
                    return self[p.target_folder]
            return None
        from .batch.links import path_file_names  # older batch: pair by path, as the build does

        for docs in self._files.values():
            for ds in docs.external.data_sources:
                if k in ((ds.uuid or "").casefold(), ds.name.casefold()):
                    for wanted in path_file_names(ds.paths) or [ds.name.casefold()]:
                        hit = next((d for n, d in self._files.items() if n.casefold() == wanted), None)
                        if hit is not None:
                            return hit
        return None

    def resolve(self, scoped_doc_id: str) -> Optional[ResolvedRef]:
        """Follow ``<file uuid>/…``, ``file:<name>/…``, ``ds:<data source>/…`` or ``xfile:<folder>/…`` to its file.

        None when the file isn't in this batch. ValueError for an unscoped docId.
        """
        if scoped_doc_id.startswith("xfile:"):
            folder, _, doc_id = scoped_doc_id[len("xfile:"):].partition("/")
            docs = self._files.get(self._folders.get(folder, ""))
        else:
            from .normalize.ids import split_scoped_doc_id  # importing normalize at the top loads the parser

            scope, doc_id = split_scoped_doc_id(scoped_doc_id)
            if scope is None:
                raise ValueError(f"{scoped_doc_id!r} has no file scope; look it up in one file with .get()")
            if scope.startswith("file:"):
                try:
                    docs = self[_unescape_scope(scope[len("file:"):])]
                except KeyError:
                    docs = None
            elif scope.startswith("ds:"):
                docs = self._by_data_source(_unescape_scope(scope[len("ds:"):]))
            else:
                docs = self._by_uuid(scope)
        if docs is None:
            return None
        return ResolvedRef(file=docs, doc_id=doc_id, entity=docs.get(doc_id))


def _read_catalog(path: Path) -> DocsCatalog:
    data = orjson.loads(path.read_bytes())
    major = file_version(data)[0]
    if major > CONTRACT_VERSION[0]:
        raise ContractVersionError(f"{path}: docs written by schema {major}.x; this fm-saxml reads up to "
                                   f"{CONTRACT_VERSION[0]}.x — upgrade fm-saxml")
    return DocsCatalog.model_validate(data)


def load(path: Union[str, Path]) -> Union[SolutionDocs, BatchDocs]:
    """The docs in ``path``: ``SolutionDocs`` for one file's folder, ``BatchDocs`` for a multi-file build."""
    path = Path(path)
    if not path.is_dir():
        raise DocsNotFoundError(f"{path} is not a folder")
    catalog_path = path / ROOT_CATALOG
    if catalog_path.is_file():
        catalog = _read_catalog(catalog_path)
        return BatchDocs(path, catalog) if catalog.kind == "batch" else SolutionDocs(path, catalog)
    if (path / "entities.json").is_file():
        return SolutionDocs(path)
    if any((d / "entities.json").is_file() for d in path.iterdir() if d.is_dir()):
        return BatchDocs(path)
    raise DocsNotFoundError(f"{path} holds no fm-saxml docs (no {ROOT_CATALOG} or entities.json)")


def _docs_root(root: Union[str, Path, None]) -> Path:
    if root is None:
        env = os.environ.get(DOCS_ROOT_ENV)
        if not env:
            raise DocsNotFoundError(f"No docs root: pass root=, or set {DOCS_ROOT_ENV}")
        root = env
    root = Path(os.path.expandvars(str(root))).expanduser()
    if not root.is_dir():
        raise DocsNotFoundError(f"Docs root {root} is not a folder")
    return root


def find_docs(solution: str, root: Union[str, Path, None] = None) -> Path:
    """Folder of a converted solution under ``root`` (default ``$FM_SAXML_DOCS_ROOT``).

    Matches, ignoring case, in this order: a folder name or its slug; the ``solution`` in a
    folder's docs.json; a FileMaker file listed in a docs.json (for a batch, that file's own
    folder). Several matches at one step are an error, as is none at all.
    """
    from .normalize.names import safe_slug

    root = _docs_root(root)
    keys = {solution.strip().casefold(), safe_slug(solution.strip()).casefold()}
    for ext in (".fmp12", ".fmp7"):
        keys |= {k[: -len(ext)] for k in keys if k.endswith(ext)}

    folders, catalogs = [], {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if (d / ROOT_CATALOG).is_file():
            try:
                catalogs[d] = _read_catalog(d / ROOT_CATALOG)
            except (ValueError, OSError):
                continue
            folders.append(d)
        elif (d / "entities.json").is_file():
            folders.append(d)

    def only(hits: list[Path]) -> Optional[Path]:
        if len(hits) > 1:
            raise DocsNotFoundError(f"{solution!r} matches several docs folders: {', '.join(map(str, hits))}")
        return hits[0] if hits else None

    for match in (
        lambda d: d.name.casefold() in keys,
        lambda d: d in catalogs and catalogs[d].solution.casefold() in keys,
    ):
        hit = only([d for d in folders if match(d)])
        if hit:
            return hit
    hit = only([d / f.folder for d, c in catalogs.items() for f in c.files
                if keys & {f.name.casefold(), (f.fmp_file_name or "").casefold(), f.folder.casefold()}])
    if hit:
        return hit

    found = []
    for d in folders:
        c = catalogs.get(d)
        found.append(f"{d.name} ({', '.join(f.name for f in c.files)})" if c and c.kind == "batch" else d.name)
    raise DocsNotFoundError(f"No docs for {solution!r} in {root}. Found: {', '.join(found) or 'nothing'}")
