"""Central link resolver — maps docIds to file paths and builds relative links."""

from __future__ import annotations

from pathlib import PurePosixPath

from ...model.document_model import DocumentModel
from ...normalize.paths import (
    table_path,
    field_path,
    table_occurrence_path,
    relationship_path,
    layout_path,
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
        self._build_index()

    def _build_index(self) -> None:
        em = self._model.entities

        for e in em.tables.values():
            p = table_path(e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.name

        for e in em.fields.values():
            table_name = em.tables[e.base_table_doc_id].name if e.base_table_doc_id in em.tables else e.base_table_doc_id.split(":", 1)[-1]
            p = field_path(table_name, e.name)
            self._path_by_doc_id[e.doc_id] = p
            self._title_by_doc_id[e.doc_id] = e.qualified_name

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
        return f"[{_esc(title)}]({href})"


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
