"""Markdown renderer — converts DocumentModel into a folder of Markdown files."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape, Undefined

from ...model.document_model import DocumentModel
from ...model.step_text import code_fence, render_script_block
from ...analyze.access import build_access
from ...analyze.coverage import build_coverage
from ...parser.coverage import CONTEXTS as COVERAGE_CONTEXTS
from ...normalize.paths import relative_md_link
from ...utils.file_writer import write_text
from .link_resolver import LinkResolver, _encode_href, _esc as _esc_link_label


_TEMPLATES_DIR = Path(__file__).parent / "templates"

# fm-saxml's own version line for page footers, looked up once by render_markdown
_updated_at: str | None = None
# Effective access per privilege set (analyze.access), built once by render_markdown
_access: dict[str, Any] | None = None


def render_markdown(
    model: DocumentModel, output_dir: Path, cross_file: dict[str, tuple[str, str]] | None = None,
) -> None:
    """Render the full documentation site from a DocumentModel.

    ``cross_file`` adds pages in sibling folders of a multi-file build (see ``LinkResolver``).
    """
    global _updated_at, _access
    from ...version import get_self_updated_at_display

    # Reads git metadata (two subprocesses): once per build, not once per page
    _updated_at = get_self_updated_at_display()
    _access = build_access(model) if model.entities.privilege_sets else None
    env = _make_jinja_env()
    links = LinkResolver(model, cross_file)

    _render_root_index(model, output_dir, env, links)
    _render_tables(model, output_dir, env, links)
    _render_fields(model, output_dir, env, links)
    _render_table_occurrences(model, output_dir, env, links)
    _render_relationships(model, output_dir, env, links)
    _render_layouts(model, output_dir, env, links)
    _render_layout_objects(model, output_dir, env, links)
    _render_scripts(model, output_dir, env, links)
    _render_variables(model, output_dir, env, links)
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
        loader=PackageLoader("fm_saxml", "render/markdown/templates"),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["cell"] = _md_cell
    return env


def _md_cell(value: object) -> str:
    """Make text safe for a single Markdown table cell (no raw newlines or bare pipes)."""
    text = "" if value is None else str(value)
    text = " ".join(text.split("\n")).replace("\r", "")
    return text.replace("|", "\\|")


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

    def has_page(doc_id: str) -> bool:
        return links.href(current_path, doc_id) is not None

    def privilege_access(kind: str, doc_id: str) -> list[dict[str, Any]]:
        return _privilege_access_rows(model, _access, kind, doc_id)

    xml_modified_at = (
        model.source.source_modified_at.strftime("%Y-%m-%d %H:%M UTC")
        if model.source.source_modified_at
        else None
    )

    from ...version import get_self_updated_at_display, REPO_URL, REPO_LABEL

    return {
        "entity": entity,
        "source_file": model.source.file_name,
        "fm_version": model.source.file_maker_version,
        "schema_version": model.schema_version,
        "solution_name": model.solution.name,
        "generated_at": model.source.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "xml_modified_at": xml_modified_at,
        "fm_saxml_updated_at": _updated_at or get_self_updated_at_display(),
        "fm_saxml_repo_url": REPO_URL,
        "fm_saxml_repo_label": REPO_LABEL,
        "link": link,
        "get_entity": get_entity,
        "backlinks": backlinks,
        "has_page": has_page,
        "privilege_access": privilege_access,
    }


# ---------------------------------------------------------------------------
# Root index
# ---------------------------------------------------------------------------

def _render_root_index(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    tmpl = env.get_template("index.md.j2")
    ctx = _make_ctx(model, "index.md", links)
    ctx["counts"] = _counts(model)
    ctx["file_options"] = model.file_options
    ctx["external_data_sources"] = model.external_data_sources
    ctx["graph_note_count"] = len(model.graph_notes)
    ctx["coverage"] = build_coverage(model)
    ctx["scrub_notice"] = _scrub_notice(model)
    content = tmpl.render(**ctx)
    write_text(output_dir / "index.md", content)


def _scrub_notice(model: DocumentModel) -> dict[str, Any] | None:
    """What a reader (or agent) needs to know about scrubbing before trusting code in these docs."""
    sc = model.scrubbing
    if sc is None:
        return None
    if not sc.applied:
        return {"applied": False}
    redacted = [f for f in sc.findings if f.action == "redacted"]
    steps = {f.location for f in redacted if f.location.startswith("Script ") and " › Step " in f.location}
    return {
        "applied": True, "level": sc.level,
        "values": sum(sc.counts.values()), "places": len(redacted), "steps": len(steps),
        "scripts": len({loc.split(" › ", 1)[0] for loc in steps}),
    }


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
        rel_path = links.path_for(entity.doc_id)
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
        by_table.setdefault(field.base_table_doc_id, []).append(field)

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
    for table_doc_id, fields in by_table.items():
        table = model.entities.tables.get(table_doc_id)
        table_name = table.name if table else table_doc_id.split(":", 1)[-1]
        field_dir = links.field_dir_for(table_doc_id)
        _render_section_index(
            fields,
            output_dir / field_dir / "index.md",
            section_title=f"Fields: {table_name}",
            entity_type_label="field",
            extra_header="Type",
            extra_col_fn=lambda e: f"{e.data_type} / {e.field_type}",
            index_path=f"{field_dir}/index.md",
            links=links,
        )

    for entity in model.entities.fields.values():
        rel_path = links.path_for(entity.doc_id)
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
    notes_by_to: dict[str, list] = {}
    for note in model.graph_notes:
        for to in note.table_occurrence_doc_ids + note.below_doc_ids:
            notes_by_to.setdefault(to, []).append(note)
    for entity in entities:
        rel_path = links.path_for(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        ctx["graph_notes"] = notes_by_to.get(entity.doc_id, [])
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)
    _render_graph_notes(model, output_dir, links)


GRAPH_NOTES_PATH = "TableOccurrences/_GraphNotes.md"


def _render_graph_notes(model: DocumentModel, output_dir: Path, links: LinkResolver) -> None:
    """The relationship graph's text notes, with where they sit and the TOs they lie over."""
    if not model.graph_notes:
        return
    lines = ["# Relationship Graph Notes", "",
             f"{len(model.graph_notes)} text note(s) on the relationship graph, top to bottom. "
             "\"Lies Over\" lists the table occurrences a note overlaps. Notes are often headings above a group: "
             "\"Below\" lists the ones under a note, within its width, down to the next note (by position only).", "",
             "| Note | Position (top, left) | Size | Lies Over | Below |", "|---|---|---|---|---|"]
    ordered = sorted(model.graph_notes, key=lambda n: (n.bounds.top, n.bounds.left) if n.bounds else (0, 0))
    for note in ordered:
        b = note.bounds
        pos = f"{b.top:g}, {b.left:g}" if b else ""
        size = f"{b.right - b.left:g} × {b.bottom - b.top:g}" if b else ""
        over = ", ".join(links.md_link(GRAPH_NOTES_PATH, d) for d in note.table_occurrence_doc_ids)
        below = ", ".join(links.md_link(GRAPH_NOTES_PATH, d) for d in note.below_doc_ids)
        lines.append(f"| {_md_cell(note.text) or '_(empty)_'} | {pos} | {size} | {over} | {below} |")
    write_text(output_dir / GRAPH_NOTES_PATH, "\n".join(lines) + "\n")


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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        steps = [model.entities.script_steps[d] for d in entity.steps if d in model.entities.script_steps]
        block = render_script_block(steps)
        ctx["steps_block"] = block
        ctx["steps_fence"] = code_fence(block)
        ctx["variables"] = _script_variables(model, entity)
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


def _script_variables(model: DocumentModel, script) -> list[dict[str, Any]]:
    """Rows for a script page's Variables table: each variable with this script's set / read steps."""
    rows = []
    for doc_id in script.variables:
        var = model.entities.variables.get(doc_id)
        if var is None:
            continue
        here = [u for u in var.uses if u.script_doc_id == script.doc_id]
        sets = sorted({u.step for u in here if u.access == "set" and u.step})
        reads = sorted({u.step for u in here if u.access == "read" and u.step})
        note = ""
        if var.scope == "local" and reads and not sets:
            note = "Never set in this script: always empty (a typo?)"
        elif var.scope == "global" and not var.sets:
            note = "Never set in this file"
        rows.append({"doc_id": doc_id, "name": var.name, "scope": var.scope,
                     "sets": sets, "reads": reads, "note": note})
    rows.sort(key=lambda r: (r["scope"] != "global", r["name"].lower()))
    return rows


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def _render_variables(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    """A page per ``$$global``, and an index of globals plus each script's ``$locals``."""
    variables = list(model.entities.variables.values())
    if not variables:
        return
    tmpl = env.get_template("variable.md.j2")
    globals_ = [v for v in variables if v.scope == "global"]
    for entity in globals_:
        rel_path = links.path_for(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        write_text(output_dir / rel_path, tmpl.render(**ctx))

    index = "Variables/index.md"
    lines = ["# Variables", "",
             f"_{len(globals_)} global variable(s), {len(variables) - len(globals_)} local variable(s)_", ""]
    if globals_:
        lines += ["## Global Variables", "", "| Variable | Set In | Read In | Note |", "|---|---:|---:|---|"]
        for v in sorted(globals_, key=lambda v: v.name.lower()):
            note = "Never set in this file" if not v.sets else ("Never read in this file" if not v.reads else "")
            lines.append(f"| {links.md_link(index, v.doc_id)} | {len(v.sets)} | {len(v.reads)} | {note} |")
        lines.append("")
    locals_by_script: dict[str, list] = {}
    for v in variables:
        if v.scope == "local" and v.script_doc_id:
            locals_by_script.setdefault(v.script_doc_id, []).append(v)
    if locals_by_script:
        lines += ["## Local Variables", "",
                  ("Each script's `$variables`. _Never set_ lists those read without ever being set in "
                   "that script: they are always empty, which usually means a typo."), "",
                  "| Script | Variables | Never Set |", "|---|---|---|"]
        for script_doc_id, vs in sorted(locals_by_script.items(), key=lambda kv: links.title_for(kv[0]).lower()):
            names = ", ".join(f"`{v.name}`" for v in sorted(vs, key=lambda v: v.name.lower()))
            unset = ", ".join(f"`{v.name}`" for v in vs if v.reads and not v.sets)
            lines.append(f"| {links.md_link(index, script_doc_id)} | {_md_cell(names)} | {_md_cell(unset)} |")
    write_text(output_dir / index, "\n".join(lines) + "\n")


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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        ctx["values_block"] = "\n".join(entity.values)  # exactly as typed, blank separator lines included
        ctx["values_fence"] = code_fence(ctx["values_block"])
        content = tmpl.render(**ctx)
        write_text(output_dir / rel_path, content)


# ---------------------------------------------------------------------------
# Privilege Sets
# ---------------------------------------------------------------------------

_PRIVILEGE_OTHER_LABELS = {
    "Print": "Allow printing",
    "Export": "Allow exporting",
    "manageDatabase": "Manage database",
    "manageCustomMenus": "Manage custom menus",
    "manageAccounts": "Manage accounts (except Full Access)",
    "manageExtPrivs": "Manage extended privileges",
    "allowOverride": "Allow user to override data validation warnings",
    "allowOpenQuickly": "Allow Open Quickly",
    "disconnectIdle": "Disconnect user from server when idle",
    "passwordChangeProhibited": "Allow user to modify their own password",
    "commands": "Available menu commands",
}


def _privilege_access_label(value: str) -> str:
    return {"ReadWrite": "Yes", "ReadOnly": "View only", "NoAccess": "No", "Limited": "Limited…",
            "Calculation": "Limited"}.get(value, value)


# The wording of FileMaker's Edit Privilege Set dialog, per kind of object
_LEVEL_LABELS = {"ReadWrite": "Modifiable", "ReadOnly": "View only", "NoAccess": "No access"}
_SCRIPT_LEVEL_LABELS = {**_LEVEL_LABELS, "ReadOnly": "Executable only"}
_FIELDS_LABELS = {"ReadWrite": "All modifiable", "ReadOnly": "All view only", "NoAccess": "All no access",
                  "Custom": "Custom (below)"}
_RECORD_COLUMNS = ("View", "Edit", "Create", "Delete", "Fields")
# category key -> (heading, first column, "Allow creation of new ...", [(column, attribute, labels)])
_PRIVILEGE_CATEGORIES = (
    ("records", "Records", "Table", None, []),
    ("layouts", "Layouts", "Layout", "layouts",
     [("Layout", "access", _LEVEL_LABELS), ("Records", "records", _LEVEL_LABELS)]),
    ("value_lists", "Value Lists", "Value List", "value lists", [("Access", "access", _LEVEL_LABELS)]),
    ("scripts", "Scripts", "Script", "scripts", [("Access", "access", _SCRIPT_LEVEL_LABELS)]),
)


def _privilege_tables(entity: Any) -> list[dict[str, Any]]:
    """Each custom category of a privilege set, as table rows in FileMaker's own wording.

    Tables have one column per record action (View, Edit, Create, Delete, Fields), read from
    child elements; layouts, value lists and scripts keep their level as attributes of the
    row itself (``<Layout access="ReadOnly" records="ReadWrite">``). Any column not known
    here is still shown, under its XML name, so nothing is silently dropped.
    """
    out = []
    for key, heading, item_label, create_words, attr_columns in _PRIVILEGE_CATEGORIES:
        cat = getattr(entity, key)
        if cat is None or cat.custom is None:
            continue
        child_cols: list[str] = [c for c in _RECORD_COLUMNS if any(c in it.access for it in cat.custom)]
        for it in cat.custom:
            child_cols += [c for c in it.access if c not in child_cols]
        known_attrs = {a for _, a, _ in attr_columns}
        extra_attrs: list[str] = []
        for it in cat.custom:
            extra_attrs += [a for a in it.attributes if a not in known_attrs and a not in extra_attrs]
        columns = ([c for c, a, _ in attr_columns if any(a in it.attributes for it in cat.custom)]
                   + ["Field access" if c == "Fields" else c for c in child_cols] + extra_attrs)
        rows = []
        for it in cat.custom:
            cells = [labels.get(it.attributes.get(a, ""), it.attributes.get(a, ""))
                     for c, a, labels in attr_columns if c in columns]
            cells += [_FIELDS_LABELS.get(it.access.get(c, ""), it.access.get(c, "")) if c == "Fields"
                      else _privilege_access_label(it.access.get(c, "")) for c in child_cols]
            cells += [it.attributes.get(a, "") for a in extra_attrs]
            rows.append({"item": it, "cells": cells,
                         "limited": [{"role": c.role, "text": c.text} for c in it.calculations]})
        allow_create = None
        if create_words and cat.allow_create is not None:
            allow_create = f"Allow creation of new {create_words}: {'Yes' if cat.allow_create else 'No'}"
        out.append({
            "heading": heading, "item_label": item_label, "columns": columns, "rows": rows,
            "has_limited": any(r["limited"] for r in rows), "allow_create": allow_create,
            "field_tables": [{"item": it, "fields": [{"field": f, "label": _LEVEL_LABELS.get(f.access, f.access)}
                                                     for f in it.field_access]}
                             for it in cat.custom if it.field_access],
        })
    return out


# ---------------------------------------------------------------------------
# "Access by privilege set" on script, layout, value list and field pages
# ---------------------------------------------------------------------------

_ACCESS_LEVEL_WORDS = {"modifiable": "Modifiable", "executable": "Executable only", "view": "View only",
                       "none": "No access"}
_ACCESS_REASONS = {
    "fullAccess": "Full Access", "blanket": "Same for all", "customRow": "Own row",
    "newFallback": '"Any new" row', "notListed": "Not listed", "fieldRow": "Own entry",
    "newFieldFallback": '"Any new field" entry', "fieldNotListed": "Not listed",
}
# Which privilege-set category decides each kind of object
_ACCESS_CATEGORY = {"script": "scripts", "layout": "layouts", "valueList": "value_lists", "field": "records"}


def _privilege_access_rows(model: DocumentModel, access: dict[str, Any] | None, kind: str,
                           doc_id: str) -> list[dict[str, Any]]:
    """One row per privilege set for one object, or [] when no set has a custom list for it.

    Files that only use blanket settings ("all executable only", ...) would get the same
    table on every page, which tells a reader nothing the privilege set pages don't.
    """
    if not access:
        return []
    rows = access["objects"].get(kind, {}).get(doc_id)
    if not rows:
        return []
    category = _ACCESS_CATEGORY[kind]
    sets = model.entities.privilege_sets

    def custom(ps_doc_id: str) -> bool:
        cat = getattr(sets[ps_doc_id], category, None) if ps_doc_id in sets else None
        if cat is None or cat.custom is None:
            return False
        return kind != "field" or any(it.field_access or it.access.get("Fields") for it in cat.custom)

    if not any(custom(r[0]) for r in rows):
        return []
    out = []
    for row in rows:
        level, reason = row[1], row[-1]
        text = _ACCESS_LEVEL_WORDS.get(level, level)
        if kind == "layout" and row[2]:
            text += f" (records: {_ACCESS_LEVEL_WORDS.get(row[2], row[2]).lower()})"
        out.append({"set_doc_id": row[0], "access": text, "reason": _ACCESS_REASONS.get(reason, reason)})
    return out


def _privilege_other_value(key: str, value: str) -> str:
    if value.lower() in ("true", "false"):
        yes = value.lower() == "true"
        if key == "passwordChangeProhibited":
            yes = not yes  # FileMaker's checkbox is the opposite: "Allow user to modify their own password"
        return "Yes" if yes else "No"
    return value


def _render_privilege_sets(model: DocumentModel, output_dir: Path, env: Environment, links: LinkResolver) -> None:
    if not model.entities.privilege_sets:
        return
    tmpl = env.get_template("privilege_set.md.j2")
    for entity in model.entities.privilege_sets.values():
        rel_path = links.path_for(entity.doc_id)
        ctx = _make_ctx(model, rel_path, links, entity)
        ctx["access_label"] = _privilege_access_label
        ctx["privilege_tables"] = _privilege_tables(entity)
        ctx["other_label"] = lambda key: _PRIVILEGE_OTHER_LABELS.get(key, key)
        ctx["other_value"] = _privilege_other_value
        write_text(output_dir / rel_path, tmpl.render(**ctx))

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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
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
        rel_path = links.path_for(entity.doc_id)
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
        section_title="File Access",
        entity_type_label="file access authorization",
        extra_header="Type",
        extra_col_fn=lambda e: e.ref_type,
        index_path="FileAccess/index.md",
        links=links,
    )
    for entity in entities:
        rel_path = links.path_for(entity.doc_id)
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

    coverage = build_coverage(model)
    areas: dict[str, list] = {}
    for row in coverage.rows:
        areas.setdefault(row.area, []).append(row)  # in MEASURES order, not alphabetical

    # Summary
    tmpl = env.get_template("reports/summary.md.j2")
    xml_modified_at = (
        model.source.source_modified_at.strftime("%Y-%m-%d %H:%M UTC")
        if model.source.source_modified_at
        else None
    )
    from ...version import get_self_updated_at_display, REPO_URL, REPO_LABEL
    content = tmpl.render(
        generated_at=model.source.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        source_file=model.source.file_name,
        xml_modified_at=xml_modified_at,
        fm_saxml_updated_at=get_self_updated_at_display(),
        fm_saxml_repo_url=REPO_URL,
        fm_saxml_repo_label=REPO_LABEL,
        counts=counts,
        total_references=len(model.references),
        exact_references=sum(1 for r in model.references if r.confidence == "exact"),
        parsed_references=sum(1 for r in model.references if r.confidence == "parsed"),
        unresolved_references=len(unresolved),
        external_references=sum(1 for r in model.references if r.confidence == "external"),
        warning_counts=dict(warning_counts),
        scrubbing=model.scrubbing,
        coverage=coverage,
    )
    write_text(reports_dir / "summary.md", content)

    # Coverage: only when the build asked for it (--coverage)
    if coverage.available:
        tmpl = env.get_template("reports/coverage.md.j2")
        write_text(reports_dir / "coverage.md", tmpl.render(report=coverage, areas=areas, context_count=len(COVERAGE_CONTEXTS)))

    # Redactions
    if model.scrubbing is not None:
        tmpl = env.get_template("reports/redactions.md.j2")
        write_text(reports_dir / "redactions.md", tmpl.render(scrubbing=model.scrubbing))

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
    if sort_key is None:
        sort_key = lambda x: (getattr(x, "name", "") or "").lower()
    if name_fn is None:
        name_fn = lambda x: getattr(x, "name", "") or ""

    lines = [f"# {section_title}", "", f"_{len(entities)} {entity_type_label}(s)_", ""]
    lines.append(f"| Name | {extra_header} |")
    lines.append("|---|---|")
    for e in sorted(entities, key=sort_key):
        # Names can hold newlines and pipes (e.g. a multi-line layout text object),
        # which would end the table row early.
        display_name = _md_cell(name_fn(e))
        doc_path = links.path_for(e.doc_id)
        if doc_path:
            href = _relative_from_index(index_path, doc_path)
            name_cell = f"[{_esc_link_label(display_name)}]({_encode_href(href)})"
        else:
            name_cell = display_name
        extra_cell = _md_cell(extra_col_fn(e))
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
        variables=len(model.entities.variables),
    )
