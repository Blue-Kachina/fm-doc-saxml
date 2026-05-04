"""Shared helpers for XML extraction."""

from __future__ import annotations

from lxml import etree


def attr(elem: etree._Element, *names: str, default: str = "") -> str:
    """Get the first matching attribute from an element (case-insensitive fallback)."""
    attribs = elem.attrib
    for name in names:
        if name in attribs:
            return attribs[name]
    # case-insensitive fallback
    lower_attribs = {k.lower(): v for k, v in attribs.items()}
    for name in names:
        val = lower_attribs.get(name.lower())
        if val is not None:
            return val
    return default


def find_child(elem: etree._Element, *tags: str) -> etree._Element | None:
    """Find the first child matching any of the given local tag names (namespace-unaware)."""
    for child in elem:
        if not isinstance(child.tag, str):
            continue  # skip comments, PIs
        local = _local(child.tag)
        if local in tags:
            return child
    return None


def find_all_children(elem: etree._Element, *tags: str) -> list[etree._Element]:
    """Find all children matching any of the given local tag names."""
    results = []
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        if _local(child.tag) in tags:
            results.append(child)
    return results


def find_descendant(elem: etree._Element, *tags: str) -> etree._Element | None:
    """Find the first descendant matching any of the given local tag names."""
    for child in elem.iter():
        if not isinstance(child.tag, str):
            continue
        if _local(child.tag) in tags:
            return child
    return None


def find_all_descendants(elem: etree._Element, *tags: str) -> list[etree._Element]:
    """Find all descendants matching any of the given local tag names."""
    return [e for e in elem.iter() if isinstance(e.tag, str) and _local(e.tag) in tags]


def text_of(elem: etree._Element | None) -> str:
    """Get .text of an element, stripped, or empty string."""
    if elem is None:
        return ""
    return (elem.text or "").strip()


def calc_text_of(calc_elem: etree._Element | None) -> str:
    """Extract calculation text from a <Calculation> element.

    In v1 the text is the direct content; in v2 it lives in a <Text><![CDATA[...]]></Text> child.
    """
    if calc_elem is None:
        return ""
    text_child = find_child(calc_elem, "Text")
    if text_child is not None:
        val = (text_child.text or "").strip()
        if val:
            return val
    return (calc_elem.text or "").strip()


def xml_path(elem: etree._Element) -> str:
    """Build a simple XPath-like path string for debugging."""
    parts = []
    current = elem
    while current is not None:
        tag = current.tag
        if isinstance(tag, str):
            parts.append(_local(tag))
        current = current.getparent()
    return "/" + "/".join(reversed(parts))


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag
