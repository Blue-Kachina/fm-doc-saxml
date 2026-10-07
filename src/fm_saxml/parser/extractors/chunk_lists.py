"""Extract tokenized calculations (ChunkLists) from the DDR_INFO section of v2 SaveAsXML."""

from __future__ import annotations

from typing import Any, Callable
from lxml import etree

from ._helpers import attr, calc_text_of, find_all_children, find_child, text_of, _local

ChunkLists = dict[str, list[dict[str, Any]]]


def extract_chunk_lists(root: etree._Element) -> ChunkLists:
    """Map each ChunkList key to the entity references in that calculation.

    ``<DDR_INFO><Calculation><ObjectList>`` holds one element per calculation, named
    by the key a ``<DDRREF kind="ChunkList">`` beside the calc's ``<Text>`` points at
    (e.g. ``_B6E6906D-…_1``). Its ``<ChunkList>`` is the formula split into tokens,
    with FileMaker's own resolution of every field (to a table occurrence) and custom
    function it uses. Only those reference tokens are kept.

    A ChunkList with no chunks at all is left out: FileMaker writes one when it could
    not tokenize the calc (e.g. it contains ``<Field Missing>``), so it says nothing
    about what the calc uses and callers should fall back to the text.
    """
    ddr_info = find_child(root, "DDR_INFO")
    section = find_child(ddr_info, "Calculation") if ddr_info is not None else None
    obj_list = find_child(section, "ObjectList") if section is not None else None
    if obj_list is None:
        return {}

    result: ChunkLists = {}
    for entry in obj_list:
        if not isinstance(entry.tag, str):
            continue
        chunk_list = find_child(entry, "ChunkList")
        if chunk_list is not None and find_all_children(chunk_list, "Chunk"):
            result[_local(entry.tag)] = _chunk_refs(chunk_list)
    return result


def _chunk_refs(chunk_list: etree._Element) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for chunk in find_all_children(chunk_list, "Chunk"):
        kind = attr(chunk, "type")
        if kind == "FieldRef":
            fr = find_child(chunk, "FieldReference")
            if fr is None or not attr(fr, "name"):
                continue
            to_ref = find_child(fr, "TableOccurrenceReference")
            refs.append({
                "type": "field",
                "id": attr(fr, "id"),
                "uuid": attr(fr, "UUID", "uuid"),
                "name": attr(fr, "name"),
                "table": attr(to_ref, "name") if to_ref is not None else "",
                "table_id": attr(to_ref, "id") if to_ref is not None else "",
            })
        elif kind == "CustomFunctionRef" and text_of(chunk):
            refs.append({"type": "customFunction", "name": text_of(chunk)})
    return refs


def chunk_refs_for(holder: etree._Element, chunk_lists: ChunkLists | None) -> list[dict] | None:
    """References from the ChunkList a calc's ``<DDRREF kind="ChunkList">`` points at.

    None when there is no ChunkList for it (v1 export, untokenizable calc).
    """
    ddr = find_child(holder, "DDRREF")
    if chunk_lists is None or ddr is None or attr(ddr, "kind") != "ChunkList":
        return None
    return chunk_lists.get(text_of(ddr))


def calc_entry(holder: etree._Element, role: str, chunk_lists: ChunkLists | None) -> dict[str, Any] | None:
    """``{"role", "text", "references"}`` for the element holding a calc's ``<Text>``, or None if empty."""
    text = calc_text_of(holder)
    if not text:
        return None
    return {"role": role, "text": text, "references": chunk_refs_for(holder, chunk_lists)}


def collect_calcs(
    elem: etree._Element,
    chunk_lists: ChunkLists | None,
    role_for: Callable[[list[str]], str],
    stop_at: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Every calculation inside ``elem``, each with a role and its ChunkList references.

    A calc is held by an element with a ``<Text>`` child that is a ``<Calculation>`` or
    sits beside a ``<DDRREF kind="ChunkList">`` (e.g. a popover ``<Title>``).
    ``role_for`` gets the local tag names from ``elem`` (exclusive) down to the holder
    (inclusive). Elements named in ``stop_at`` are not descended into — they own their
    calcs themselves (nested layout objects).
    """
    found: list[dict[str, Any]] = []

    def walk(node: etree._Element, path: list[str]) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            tag = _local(child.tag)
            if tag in stop_at:
                continue
            child_path = [*path, tag]
            ddr = find_child(child, "DDRREF")
            is_holder = find_child(child, "Text") is not None and (
                tag == "Calculation" or (ddr is not None and attr(ddr, "kind") == "ChunkList")
            )
            if is_holder:
                entry = calc_entry(child, role_for(child_path), chunk_lists)
                if entry:
                    found.append(entry)
            else:
                walk(child, child_path)

    walk(elem, [])
    return found
