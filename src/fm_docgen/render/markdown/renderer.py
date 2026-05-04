"""Markdown renderer — converts DocumentModel into a folder of Markdown files."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape, Undefined

from ...model.document_model import DocumentModel
from ...normalize.paths import (
    table_path, field_path, table_occurrence_path, relationship_path,
    layout_path, layout_object_path, script_path, custom_function_path,
    value_list_path, privilege_set_path, account_path, extended_privilege_path,
    custom_menu_path, custom_menu_set_path, theme_path, file_reference_path,
    relative_md_link,
)
from ...utils.file_writer import write_text
from .link_resolver import LinkResolver


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_markdown(model: DocumentModel, output_dir: Path) -> None:
    """Render the full documentation site from a DocumentModel."""
    env = _make_jinja_env()
    links = LinkResolver(model)

    _render_root_index(model, output_dir, env, links)
    _render_tables(model, output_dir, env, links)
    _render_fields(model, output_dir, env, links)
    _render_table_occurrences(model, output_dir, env, links)
    _render_relationships(model, output_dir, env, links)
    _render_layouts(model, output_dir, env, links)
    _render_layout_objects(model, output_dir, env, links)
    _render_scripts(model, output_dir, env, links)
    _render_custom_functions(model, output_dir, env, links)
    _render_value_lists(model, output_dir, env, links)
    _render_privilege_sets(model, output_dir, env, links)
    _render_accounts(model, output_dir, env, links)
    _render_extended_privileges(model, output_dir, env, links)
    _render_custom_menus(model, output_dir, env, links)
    _render_custom_menu_sets(model, output_dir, env, links)
    _render_themes(model, output_dir, env, links)
    _render_file_references(model, output_dir, env, links)
    _render_reports(model, output_dir, env, links)


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------

def _make_jinja_env() -> Environment:
    env = Environment(
        loader=PackageLoader("fm_docgen", "render/markdown/templates"),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _make_ctx(
    model: DocumentModel,
    current_path: str,
    links: LinkResolver,
    entity: Any = None,
) -> dict[str, Any]:
    """Build the base Jinja context shared by all templates."""
    def link(doc_id: str, label: str | None = None) -> str:
        return links.md_link(current_path, doc_id, label)

    def get_entity(doc_id: str) -> Any:
        return model.get_entity(doc_id)

    def backlinks(doc_id: str) -> list[dict]:
        return model.backlinks.get(doc_id, [])

    xml_modified_at = (
        model.source.source_modified_at.strftime("%Y-%m-%d %H:%M UTC")
        if model.source.source_modified_at
        else None
    )

    return {
        "entity": entity,
        "source_file": model.source.file_name,
        "fm_version": model.source.file_maker_version,
        "schema_version": model.schema_version,
        "solution_name": model.solution.name,
        "generated_at": model.source.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "xml_modified_at": xml_modified_at,
        "link": link,
        "get_entity": get_entity,
        "backlinks": backlinks,
    }


# ---------------------------------------------------------------------------
# Root index
# ---------------------------------------------------------------------------

def _render_root_index(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    tmpl = env.get_template("index.md.j2")
    ctx = _make_ctx(model, "index.md", links)
    ctx["counts"] = _counts(model)
    content = tmpl.render(**ctx)
    write_text(output_dir / "index.md", content)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def _render_tables(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    tmpl = env.get_template("table.md.j2")
    entities = list(model.entities.tables.values())

    # Section index
    _render_section_index(
        entities, output_dir / "Tables" / "index.md",
        section_title="Tables",
        entity_type_label="table",
        extra_header="Field Count",
        extra_col_fn=lambda e: str(len(e.fields)),
        index_path="Tables/index.md",
        links=links,
    )

    for entity in entities:
        rel_path = table_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        ctx["global_fields"] = [
            f for f in model.entities.fields.values()
            if f.base_table_doc_id == entity.doc_id and f.storage.global_storage
        ]
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def _render_fields(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    tmpl = env.get_template("field.md.j2")

    # Group fields by table for index files
    by_table: dict[str, list] = {}
    for field in model.entities.fields.values():
        table_name = model.entities.tables.get(field.base_table_doc_id, None)
        t_name = table_name.name if table_name else field.base_table_doc_id.split(":", 1)[-1]
        by_table.setdefault(t_name, []).append(field)

    # Top-level fields index
    all_fields = list(model.entities.fields.values())
    _render_section_index(
        all_fields, output_dir / "Fields" / "index.md",
        section_title="Fields",
        entity_type_label="field",
        extra_header="Table",
        extra_col_fn=lambda e: e.base_table_doc_id.split(":", 1)[-1],
        index_path="Fields/index.md",
        links=links,
    )

    # Per-table field index pages
    for table_name, fields in by_table.items():
        from ...normalize.names import safe_slug
        _render_section_index(
            fields,
            output_dir / "Fields" / safe_slug(table_name) / "index.md",
            section_title=f"Fields: {table_name}",
            entity_type_label="field",
            extra_header="Type",
            extra_col_fn=lambda e: f"{e.data_type} / {e.field_type}",
            index_path=f"Fields/{safe_slug(table_name)}/index.md",
            links=links,
        )

    for entity in model.entities.fields.values():
        t_entity = model.entities.tables.get(entity.base_table_doc_id)
        t_name = t_entity.name if t_entity else entity.base_table_doc_id.split(":", 1)[-1]
        rel_path = field_path(t_name, entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Table Occurrences
# ---------------------------------------------------------------------------

def _render_table_occurrences(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.table_occurrences:
        return
    tmpl = env.get_template("table_occurrence.md.j2")
    entities = list(model.entities.table_occurrences.values())
    _render_section_index(
        entities, output_dir / "TableOccurrences" / "index.md",
        section_title="Table Occurrences",
        entity_type_label="table occurrence",
        extra_header="Base Table",
        extra_col_fn=lambda e: links.md_link("TableOccurrences/index.md", e.base_table_doc_id),
        index_path="TableOccurrences/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = table_occurrence_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def _render_relationships(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.relationships:
        return
    tmpl = env.get_template("relationship.md.j2")
    entities = list(model.entities.relationships.values())
    _render_section_index(
        entities, output_dir / "Relationships" / "index.md",
        section_title="Relationships",
        entity_type_label="relationship",
        extra_header="Left TO",
        extra_col_fn=lambda e: links.title_for(e.left_table_occurrence_doc_id),
        index_path="Relationships/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = relationship_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------

def _render_layouts(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.layouts:
        return
    tmpl = env.get_template("layout.md.j2")
    entities = list(model.entities.layouts.values())
    _render_section_index(
        entities, output_dir / "Layouts" / "index.md",
        section_title="Layouts",
        entity_type_label="layout",
        extra_header="Table Occurrence",
        extra_col_fn=lambda e: links.title_for(e.base_table_occurrence_doc_id or "") if e.base_table_occurrence_doc_id else "",
        index_path="Layouts/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = layout_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Layout Objects
# ---------------------------------------------------------------------------

def _render_layout_objects(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.layout_objects:
        return
    tmpl = env.get_template("layout_object.md.j2")
    entities = list(model.entities.layout_objects.values())

    # Top-level index for layout objects, grouped & sortable by layout name.
    def layout_name_for(e):
        layout = model.entities.layouts.get(e.layout_doc_id)
        return layout.name if layout else e.layout_doc_id.split(":", 1)[-1]

    _render_section_index(
        entities, output_dir / "LayoutObjects" / "index.md",
        section_title="Layout Objects",
        entity_type_label="layout object",
        extra_header="Layout · Type · Field",
        extra_col_fn=lambda e: (
            f"{layout_name_for(e)} · {e.object_type or '?'}"
            + (f" · {links.title_for(e.field_doc_id)}" if e.field_doc_id else "")
        ),
        index_path="LayoutObjects/index.md",
        links=links,
        sort_key=lambda e: (layout_name_for(e).lower(), e.object_id or ""),
        name_fn=lambda e: e.name or e.raw_text or e.object_id or "(object)",
    )

    for entity in entities:
        rel_path = links.path_for(entity.doc_id)
        if not rel_path:
            continue
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def _render_scripts(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.scripts:
        return
    tmpl = env.get_template("script.md.j2")
    entities = list(model.entities.scripts.values())
    _render_section_index(
        entities, output_dir / "Scripts" / "index.md",
        section_title="Scripts",
        entity_type_label="script",
        extra_header="Folder",
        extra_col_fn=lambda e: e.folder_path or "",
        index_path="Scripts/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = script_path(entity.name, entity.folder_path)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Custom Functions
# ---------------------------------------------------------------------------

def _render_custom_functions(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.custom_functions:
        return
    tmpl = env.get_template("custom_function.md.j2")
    entities = list(model.entities.custom_functions.values())
    _render_section_index(
        entities, output_dir / "CustomFunctions" / "index.md",
        section_title="Custom Functions",
        entity_type_label="custom function",
        extra_header="Parameters",
        extra_col_fn=lambda e: ", ".join(e.parameters),
        index_path="CustomFunctions/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = custom_function_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Value Lists
# ---------------------------------------------------------------------------

def _render_value_lists(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.value_lists:
        return
    tmpl = env.get_template("value_list.md.j2")
    entities = list(model.entities.value_lists.values())
    _render_section_index(
        entities, output_dir / "ValueLists" / "index.md",
        section_title="Value Lists",
        entity_type_label="value list",
        extra_header="Type",
        extra_col_fn=lambda e: e.list_type,
        index_path="ValueLists/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = value_list_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Privilege Sets
# ---------------------------------------------------------------------------

def _render_privilege_sets(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.privilege_sets:
        return
    for entity in model.entities.privilege_sets.values():
        rel_path = privilege_set_path(entity.name)
        content = f"---\ndocId: {entity.doc_id}\nentityType: privilegeSet\nname: {entity.name}\n---\n\n# Privilege Set: {entity.name}\n\n| Name | Value |\n|---|---|\n| FMP ID | {entity.fmp_id} |\n"
        if entity.description:
            content += f"| Description | {entity.description} |\n"
        write_text(output_dir / rel_path, content)

    entities = list(model.entities.privilege_sets.values())
    _render_section_index(
        entities, output_dir / "Privileges" / "index.md",
        section_title="Privilege Sets",
        entity_type_label="privilege set",
        extra_header="Description",
        extra_col_fn=lambda e: e.description or "",
        index_path="Privileges/index.md",
        links=links,
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _render_accounts(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.accounts:
        return
    tmpl = env.get_template("account.md.j2")
    entities = list(model.entities.accounts.values())
    _render_section_index(
        entities, output_dir / "Accounts" / "index.md",
        section_title="Accounts",
        entity_type_label="account",
        extra_header="Type",
        extra_col_fn=lambda e: e.account_type,
        index_path="Accounts/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = account_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Extended Privileges
# ---------------------------------------------------------------------------

def _render_extended_privileges(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.extended_privileges:
        return
    tmpl = env.get_template("extended_privilege.md.j2")
    entities = list(model.entities.extended_privileges.values())
    _render_section_index(
        entities, output_dir / "ExtendedPrivileges" / "index.md",
        section_title="Extended Privileges",
        entity_type_label="extended privilege",
        extra_header="Description",
        extra_col_fn=lambda e: e.description or "",
        index_path="ExtendedPrivileges/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = extended_privilege_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Custom Menus
# ---------------------------------------------------------------------------

def _render_custom_menus(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.custom_menus:
        return
    tmpl = env.get_template("custom_menu.md.j2")
    entities = list(model.entities.custom_menus.values())
    _render_section_index(
        entities, output_dir / "CustomMenus" / "index.md",
        section_title="Custom Menus",
        entity_type_label="custom menu",
        extra_header="Base Menu",
        extra_col_fn=lambda e: e.base_menu_name or "",
        index_path="CustomMenus/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = custom_menu_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Custom Menu Sets
# ---------------------------------------------------------------------------

def _render_custom_menu_sets(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.custom_menu_sets:
        return
    tmpl = env.get_template("custom_menu_set.md.j2")
    entities = list(model.entities.custom_menu_sets.values())
    _render_section_index(
        entities, output_dir / "CustomMenuSets" / "index.md",
        section_title="Custom Menu Sets",
        entity_type_label="custom menu set",
        extra_header="Menu Count",
        extra_col_fn=lambda e: str(len(e.menu_doc_ids)),
        index_path="CustomMenuSets/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = custom_menu_set_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

def _render_themes(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.themes:
        return
    tmpl = env.get_template("theme.md.j2")
    entities = list(model.entities.themes.values())
    _render_section_index(
        entities, output_dir / "Themes" / "index.md",
        section_title="Themes",
        entity_type_label="theme",
        extra_header="Display Name",
        extra_col_fn=lambda e: e.display_name or e.name,
        index_path="Themes/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = theme_path(entity.name)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# File References
# ---------------------------------------------------------------------------

def _render_file_references(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.file_references:
        return
    tmpl = env.get_template("file_access.md.j2")
    entities = list(model.entities.file_references.values())
    _render_section_index(
        entities, output_dir / "FileAccess" / "index.md",
        section_title="File References",
        entity_type_label="file reference",
        extra_header="Type",
        extra_col_fn=lambda e: e.ref_type,
        index_path="FileAccess/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = file_reference_path(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _render_reports(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    reports_dir = output_dir / "Reports"

    warning_counts: Counter = Counter(w.code for w in model.warnings)
    unresolved = [r for r in model.references if r.confidence == "unresolved"]
    counts = _counts(model)

    # Summary
    tmpl = env.get_template("reports/summary.md.j2")
    xml_modified_at = (
        model.source.source_modified_at.strftime("%Y-%m-%d %H:%M UTC")
        if model.source.source_modified_at
        else None
    )
    content = tmpl.render(
        generated_at=model.source.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        xml_modified_at=xml_modified_at,
        counts=counts,
        total_references=len(model.references),
        exact_references=sum(1 for r in model.references if r.confidence == "exact"),
        parsed_references=sum(1 for r in model.references if r.confidence == "parsed"),
        unresolved_references=len(unresolved),
        warning_counts=dict(warning_counts),
    )
    write_text(reports_dir / "summary.md", content)

    # Warnings
    tmpl = env.get_template("reports/warnings.md.j2")
    content = tmpl.render(warnings=[w.model_dump() for w in model.warnings])
    write_text(reports_dir / "warnings.md", content)

    # Unresolved references
    tmpl = env.get_template("reports/unresolved_references.md.j2")
    content = tmpl.render(refs=unresolved)
    write_text(reports_dir / "unresolved-references.md", content)


# ---------------------------------------------------------------------------
# Section index helper
# ---------------------------------------------------------------------------

def _render_section_index(
    entities: list,
    out_path: Path,
    *,
    section_title: str,
    entity_type_label: str,
    extra_header: str,
    extra_col_fn,
    index_path: str,
    links: LinkResolver,
    sort_key=None,
    name_fn=None,
) -> None:
    from ...normalize.names import safe_slug

    if sort_key is None:
        sort_key = lambda x: (getattr(x, "name", "") or "").lower()
    if name_fn is None:
        name_fn = lambda x: getattr(x, "name", "") or ""

    lines = [f"# {section_title}", "", f"_{len(entities)} {entity_type_label}(s)_", ""]
    lines.append(f"| Name | {extra_header} |")
    lines.append("|---|---|")
    for e in sorted(entities, key=sort_key):
        display_name = name_fn(e)
        doc_path = links.path_for(e.doc_id)
        if doc_path:
            href = _relative_from_index(index_path, doc_path)
            name_cell = f"[{display_name}]({href})"
        else:
            name_cell = display_name
        extra_cell = str(extra_col_fn(e))
        lines.append(f"| {name_cell} | {extra_cell} |")

    write_text(out_path, "\n".join(lines) + "\n")


def _relative_from_index(index_path: str, target_path: str) -> str:
    from pathlib import PurePosixPath
    from_dir = PurePosixPath(index_path).parent
    to = PurePosixPath(target_path)
    try:
        return str(to.relative_to(from_dir))
    except ValueError:
        pass
    parts_from = list(from_dir.parts)
    parts_to = list(to.parts)
    common = 0
    for a, b in zip(parts_from, parts_to):
        if a == b:
            common += 1
        else:
            break
    ups = len(parts_from) - common
    remainder = parts_to[common:]
    return "/".join([".."] * ups + remainder)


# ---------------------------------------------------------------------------
# Counts helper
# ---------------------------------------------------------------------------

class _Counts:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _counts(model: DocumentModel) -> _Counts:
    return _Counts(
        tables=len(model.entities.tables),
        fields=len(model.entities.fields),
        table_occurrences=len(model.entities.table_occurrences),
        relationships=len(model.entities.relationships),
        layouts=len(model.entities.layouts),
        layout_objects=len(model.entities.layout_objects),
        scripts=len(model.entities.scripts),
        script_steps=len(model.entities.script_steps),
        custom_functions=len(model.entities.custom_functions),
        value_lists=len(model.entities.value_lists),
        privilege_sets=len(model.entities.privilege_sets),
        accounts=len(model.entities.accounts),
        extended_privileges=len(model.entities.extended_privileges),
        custom_menus=len(model.entities.custom_menus),
        custom_menu_sets=len(model.entities.custom_menu_sets),
        themes=len(model.entities.themes),
        file_references=len(model.entities.file_references),
    )
