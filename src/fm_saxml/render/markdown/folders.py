"""Folder trees for the layout and script indexes, and the breadcrumbs on their pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .link_resolver import _encode_href, _esc, _relative

SEP = " › "


def entity_folder_parts(entity: Any) -> list[str]:
    """The folders an entity sits in, outermost first. Models built before ``folderPathParts`` split the joined path."""
    parts = [p for p in (getattr(entity, "folder_path_parts", None) or []) if p]
    if not parts and getattr(entity, "folder_path", None):
        parts = [p for p in entity.folder_path.split("/") if p]
    return parts


def folder_anchor(parts: list[str]) -> str:
    """The anchor of a folder's heading: its full path as the heading text, slugged the way GitHub and the HTML viewer do.

    The full path (not the last name) as heading text keeps two folders called "Old" apart.
    """
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", SEP.join(parts).strip().lower()))


@dataclass
class FolderNode:
    name: str = ""
    parts: list[str] = field(default_factory=list)
    items: list[Any] = field(default_factory=list)
    children: dict[str, "FolderNode"] = field(default_factory=dict)

    def total(self) -> int:
        return len(self.items) + sum(c.total() for c in self.children.values())

    def sorted_children(self) -> list["FolderNode"]:
        return sorted(self.children.values(), key=lambda n: (n.name.casefold(), n.name))


def build_folder_tree(entities: Iterable[Any]) -> FolderNode:
    root = FolderNode()
    for e in entities:
        node = root
        parts: list[str] = []
        for p in entity_folder_parts(e):
            parts = [*parts, p]
            node = node.children.setdefault(p, FolderNode(name=p, parts=parts))
        node.items.append(e)
    return root


def contents_lines(root: FolderNode) -> list[str]:
    """A nested bullet list linking to every folder section."""
    lines: list[str] = []

    def walk(node: FolderNode, depth: int) -> None:
        for child in node.sorted_children():
            lines.append(f"{'  ' * depth}- [{_esc(child.name)}](#{folder_anchor(child.parts)}) ({child.total()})")
            walk(child, depth + 1)

    walk(root, 0)
    return lines


def section_lines(
    root: FolderNode,
    table: Callable[[list[Any]], list[str]],
    sort_key: Callable[[Any], Any],
) -> list[str]:
    """The index body: unfiled items first, then a heading per folder (deeper folders get deeper headings)."""
    lines: list[str] = []
    if root.items:
        lines += table(sorted(root.items, key=sort_key)) + [""]

    def walk(node: FolderNode) -> None:
        for child in node.sorted_children():
            level = min(len(child.parts) + 1, 6)
            lines.extend([f"{'#' * level} {_esc(SEP.join(child.parts))}", ""])
            if child.items:
                lines.extend(table(sorted(child.items, key=sort_key)) + [""])
            walk(child)

    walk(root)
    return lines


def breadcrumb(section_title: str, index_path: str, page_path: str, parts: list[str], name: str) -> str:
    """``Scripts › Utils › Sub › Name`` with the section and each folder linked to the index; "" for an unfiled item."""
    if not parts:
        return ""
    base = _relative(page_path, index_path)
    crumbs = [f"[{_esc(section_title)}]({_encode_href(base)})"]
    for i in range(len(parts)):
        crumbs.append(f"[{_esc(parts[i])}]({_encode_href(base)}#{folder_anchor(parts[: i + 1])})")
    crumbs.append(_esc(name))
    return SEP.join(crumbs)
