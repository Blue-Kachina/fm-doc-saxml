"""Central link resolver — maps docIds to file paths and builds relative links."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote

from ...model.document_model import DocumentModel
from ...normalize.names import safe_slug
from ...normalize.paths import (
    dedupe_paths,
    table_path,
    field_path_in,
    table_occurrence_path,
    relationship_path,
    layout_path,
    layout_object_path_in,
    script_path,
    custom_function_path,
    value_list_path,
    privilege_set_path,
    account_path,
    extended_privilege_path,
    custom_menu_path,
    custom_menu_set_path,
    theme_path,
    file_reference_path,
)


class LinkResolver:
    """Resolves docIds to Markdown file paths and builds relative Markdown links."""

    def __init__(self, model: DocumentModel) -> None:
        self._model = model
        self._path_by_doc_id: dict[str, str] = {}
        self._title_by_doc_id: dict[str, str] = {}
        self._field_dir_by_table: dict[str, str] = {}
        self._build_index()

    @property
    def page_count(self) -> int:
        """Number of entity pages (excludes section indexes and reports)."""
        return len(self._path_by_doc_id)

    def _stem_of(self, doc_id: str, fallback_name: str) -> str:
        """File-name stem of a parent's resolved page (its children's folder name)."""
        path = self._path_by_doc_id.get(doc_id)
        return PurePosixPath(path).stem if path else safe_slug(fallback_name)

    def _build_index(self) -> None:
        em = self._model.entities

        for e in em.tables.values():
            p = table_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.table_occurrences.values():
            p = table_occurrence_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.relationships.values():
            p = relationship_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.layouts.values():
            p = layout_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.scripts.values():
            p = script_path(e.name, e.folder_path)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.custom_functions.values():
            p = custom_function_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.value_lists.values():
            p = value_list_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.privilege_sets.values():
            p = privilege_set_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.accounts.values():
            p = account_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.extended_privileges.values():
            p = extended_privilege_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.custom_menus.values():
            p = custom_menu_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.custom_menu_sets.values():
            p = custom_menu_set_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.themes.values():
            p = theme_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.display_name or e.name

        for e in em.file_references.values():
            p = file_reference_path(e.doc_id)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        # Make top-level pages unique even on case-insensitive file systems.
        self._path_by_doc_id = dedupe_paths(self._path_by_doc_id)

        # Fields and layout objects live in a folder named after their parent's
        # final page name, so de-duplicated parents get distinct folders too.
        children: dict[str, str] = {}
        for e in em.fields.values():
            parent = em.tables.get(e.base_table_doc_id)
            parent_name = parent.name if parent else e.base_table_doc_id.split(":", 1)[-1]
            table_dir = self._stem_of(e.base_table_doc_id, parent_name)
            self._field_dir_by_table[e.base_table_doc_id] = f"Fields/{table_dir}"
            children[e.doc_id] = field_path_in(table_dir, e.name)
            self._title_by_doc_id[e.doc_id] = e.qualified_name

        for e in em.layout_objects.values():
            layout = em.layouts.get(e.layout_doc_id)
            layout_name = layout.name if layout else e.layout_doc_id.split(":", 1)[-1]
            obj_label = e.object_id or e.doc_id.split("::", 1)[-1]
            layout_dir = self._stem_of(e.layout_doc_id, layout_name)
            children[e.doc_id] = layout_object_path_in(layout_dir, obj_label)
            display = e.name or e.raw_text or e.object_type or obj_label
            self._title_by_doc_id[e.doc_id] = f"{layout_name} · {display}"

        self._path_by_doc_id.update(dedupe_paths(children))

        # Targets in other files have no page here; show them readably, not as a raw scoped id
        for ref in self._model.references:
            t = ref.external_target
            if t is not None and ref.target_doc_id not in self._title_by_doc_id:
                label = t.name
                if t.target_type == "field" and (t.base_table or t.table_occurrence):
                    label = f"{t.base_table or t.table_occurrence}::{t.name}"
                self._title_by_doc_id[ref.target_doc_id] = f"{label} ({t.data_source})"

    def field_dir_for(self, table_doc_id: str) -> str | None:
        """Folder (e.g. ``Fields/Customers``) holding a table's field pages."""
        return self._field_dir_by_table.get(table_doc_id)

    def path_for(self, doc_id: str) -> str | None:
        return self._path_by_doc_id.get(doc_id)

    def title_for(self, doc_id: str) -> str:
        return self._title_by_doc_id.get(doc_id, doc_id)

    def href(self, from_path: str, target_doc_id: str) -> str | None:
        to_path = self._path_by_doc_id.get(target_doc_id)
        if to_path is None:
            return None
        return _relative(from_path, to_path)

    def md_link(self, from_path: str, target_doc_id: str, label: str | None = None) -> str:
        """Return a Markdown link from `from_path` to `target_doc_id`."""
        href = self.href(from_path, target_doc_id)
        title = label or self.title_for(target_doc_id)
        if href is None:
            return title
        return f"[{_esc(title)}]({_encode_href(href)})"


def _relative(from_path: str, to_path: str) -> str:
    from_dir = PurePosixPath(from_path).parent
    to = PurePosixPath(to_path)
    try:
        return str(to.relative_to(from_dir))
    except ValueError:
        pass
    from_parts = from_dir.parts
    to_parts = to.parts
    common_len = 0
    for a, b in zip(from_parts, to_parts):
        if a == b:
            common_len += 1
        else:
            break
    ups = len(from_parts) - common_len
    remainder = to_parts[common_len:]
    parts = [".."] * ups + list(remainder)
    return "/".join(parts) if parts else "."


def _esc(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _encode_href(href: str) -> str:
    """Percent-encode a relative path for use as a bare Markdown link destination.

    CommonMark only allows a space-free, unescaped sequence inside `(...)` —
    a literal space (or most other non-alphanumeric characters) ends the
    destination early, silently truncating the link. FileMaker names
    routinely contain spaces and parentheses (e.g. "Loadi18n ( idLanguage )"),
    so every generated href needs this, not just the rare edge case.
    """
    return quote(href, safe="/")
