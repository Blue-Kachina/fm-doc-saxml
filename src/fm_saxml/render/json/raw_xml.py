"""Scrubbed raw XML of scripts, layouts, themes and custom menus (roadmap B3).

``build`` writes ``raw/<kind>.json`` next to entities.json: the contract envelope plus
``xml: {docId: "<element…>"}``. They serve the tools that put something back into
FileMaker (snippets from scripts, theme CSS, menu edits, layout examples), which need
the original element rather than the model's digest. Steps and layout objects aren't
stored on their own: the reader cuts them out of their script's or layout's XML.

The XML is scrubbed with the build's own scrubber, after every file of a batch has
been scrubbed, so its placeholders are the ones on the pages. ``scrub/xml_writer.py``
does the work (the same rewrite as ``fm-saxml scrub``), on the kept elements only.
``DDR_INFO`` is left out: its step text and ChunkLists are copies of what is kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import orjson
from lxml import etree

from ...contract import RAW_DIR, RAW_FILES, envelope
from ...normalize.ids import custom_menu_doc_id, custom_menu_set_doc_id, theme_doc_id
from ...normalize.names import normalize_name
from ...utils.file_writer import write_bytes


@dataclass
class RawSource:
    """Where a model's export is, and what the model pass of the scrubber changed in it."""

    path: Path
    fragments: list[Path] = field(default_factory=list)
    changes: list[tuple[str, str, str]] = field(default_factory=list)  # Scrubber.last_changes after scrub_raw


def write_raw_xml(model, out_dir: Path, scrubber=None) -> Optional[int]:
    """Write ``out_dir/raw/*.json`` for ``model``. Returns the number of elements, or None
    when the model has no export to read (a model.json render).

    Values only this pass finds are added to ``model.scrubbing``, so call it before the
    redaction report is rendered.
    """
    source: Optional[RawSource] = getattr(model, "_raw_source", None)
    if source is None:
        return None
    root = _load_root(source)
    picked = _pick(model, root)
    del root  # only the picked elements are kept (they were moved out of the tree)

    if scrubber is not None:
        _scrub(picked, source, scrubber, model)

    by_file: dict[str, dict[str, str]] = {name: {} for name in RAW_FILES.values()}
    count = 0
    for kind, items in picked.items():
        for doc_id, el in items:
            by_file[RAW_FILES[kind]][doc_id] = etree.tostring(el, encoding="unicode", with_tail=False)
            count += 1
    head = envelope(model)
    for name, xml in by_file.items():
        write_bytes(out_dir / RAW_DIR / name, orjson.dumps({**head, "xml": xml}, option=orjson.OPT_INDENT_2))
    return count


# ---------------------------------------------------------------------------


def _load_root(source: RawSource) -> etree._Element:
    from ...parser.saxml_reader import merge_split_catalogs

    parser = etree.XMLParser(strip_cdata=False, huge_tree=True, resolve_entities=False, no_network=True)
    if source.fragments or source.path.is_dir():
        paths = source.fragments or sorted(p for p in source.path.iterdir() if p.suffix.lower() == ".xml")
        return merge_split_catalogs([etree.parse(str(p), parser).getroot() for p in paths])
    return etree.parse(str(source.path), parser).getroot()


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _children(el: Optional[etree._Element], *names: str) -> list[etree._Element]:
    return [c for c in el if _local(c) in names] if el is not None else []


def _descendants(el: Optional[etree._Element], name: str) -> list[etree._Element]:
    return [d for d in el.iter() if _local(d) == name] if el is not None else []


def _catalog(root: etree._Element, name: str) -> Optional[etree._Element]:
    """``Structure/AddAction/<name>`` (the catalogs of a whole or merged export)."""
    for structure in _children(root, "Structure"):
        for action in _children(structure, "AddAction"):
            hit = _children(action, name)
            if hit:
                return hit[0]
    return None


def _pick(model, root: etree._Element) -> dict[str, list[tuple[str, etree._Element]]]:
    """The elements to keep, by kind, with their docIds; only those the model has an entity for."""
    e = model.entities
    picked: dict[str, list[tuple[str, etree._Element]]] = {k: [] for k in RAW_FILES}

    def keep(kind: str, doc_id: str, el: etree._Element, entities: dict) -> None:
        if doc_id in entities and doc_id not in {d for d, _ in picked[kind]}:
            picked[kind].append((doc_id, el))

    for script in _children(_catalog(root, "StepsForScripts"), "Script"):
        ref = next(iter(_children(script, "ScriptReference")), None)
        if ref is not None and ref.get("name"):
            keep("scripts", model.local_script_doc_id(ref.get("name"), ref.get("id")), script, e.scripts)
    for layout in _descendants(_catalog(root, "LayoutCatalog"), "Layout"):
        if layout.get("name") and _children(layout, "PartsList"):  # not a folder, marker or divider
            keep("layouts", model.local_layout_doc_id(layout.get("name"), layout.get("id")), layout, e.layouts)
    for theme in _descendants(_catalog(root, "ThemeCatalog"), "Theme"):
        keep("themes", theme_doc_id(normalize_name(theme.get("name", ""))), theme, e.themes)
    for menu in _descendants(_catalog(root, "CustomMenuCatalog"), "CustomMenu"):
        keep("menus", custom_menu_doc_id(normalize_name(menu.get("name", ""))), menu, e.custom_menus)
    menu_sets = _catalog(root, "CustomMenuSetCatalog")
    if menu_sets is None:  # the plural is kept for older hand-made fixtures
        menu_sets = _catalog(root, "CustomMenuSetsCatalog")
    for menu_set in _descendants(menu_sets, "CustomMenuSet"):
        keep("menus", custom_menu_set_doc_id(normalize_name(menu_set.get("name", ""))), menu_set, e.custom_menu_sets)
    return picked


def _scrub(picked, source: RawSource, scrubber, model) -> None:
    """Apply the model pass's redactions to the kept elements, as ``fm-saxml scrub`` does."""
    from ...scrub.xml_writer import _drop_hashes, _Edits, _Rewriter

    container = etree.Element("fm_saxml_raw")
    for items in picked.values():
        for _doc_id, el in items:
            container.append(el)  # moves it: one tree, so late-found values reach earlier elements
    known = {f.placeholder for f in (model.scrubbing.findings if model.scrubbing else [])}
    rewriter = _Rewriter(scrubber, _Edits(source.changes))
    rewriter.rewrite(container)
    _drop_hashes(container, {e.el for e in rewriter.edits})
    # Redactions only this pass made (text the parser doesn't extract). Its review flags
    # would repeat the model pass's under XML locations, so they're dropped.
    extra = [f for f in scrubber._finalize() if f.action == "redacted" and f.placeholder not in known]
    if extra and model.scrubbing is not None and model.scrubbing.applied:
        findings = model.scrubbing.findings + extra
        model.scrubbing = scrubber.summary(findings)
