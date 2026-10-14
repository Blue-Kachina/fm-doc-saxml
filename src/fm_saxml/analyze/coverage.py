"""Coverage: what the XML contains, set against what made it into the documentation.

The XML side is counted by ``parser/coverage.py`` straight from the export, independently of
the extractors. The documentation side is counted here from the finished (scrubbed, linked)
model. A check passes when the two agree. Some checks go further than "was it captured": a
Set Variable name or a step calculation only counts as shown if it appears in the step's
rendered text.

A shortfall means something in the export did not reach the docs. A surplus means the two
sides count differently; both are worth a look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..model.document_model import DocumentModel
from ..model.step_text import COMMENT_STEP, comparable, step_text


@dataclass
class Measure:
    key: str
    area: str
    label: str
    count: Callable[[DocumentModel], int]
    note: str = ""


@dataclass
class CoverageRow:
    area: str
    key: str
    label: str
    in_xml: int
    in_docs: int
    note: str = ""

    @property
    def status(self) -> str:
        if self.in_docs == self.in_xml:
            return "complete"
        return "missing" if self.in_docs < self.in_xml else "surplus"


@dataclass
class CoverageReport:
    available: bool
    rows: list[CoverageRow] = field(default_factory=list)
    unrecognised: dict[str, dict[str, int]] = field(default_factory=dict)
    skipped: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def problems(self) -> list[CoverageRow]:
        return [r for r in self.rows if r.status != "complete"]

    @property
    def unrecognised_count(self) -> int:
        return sum(len(names) for names in self.unrecognised.values())

    @property
    def ok(self) -> bool:
        return self.available and not self.problems and not self.unrecognised


# ---------------------------------------------------------------------------
# Counting the documentation side
# ---------------------------------------------------------------------------

def _steps(m: DocumentModel):
    return m.entities.script_steps.values()


def _objects(m: DocumentModel):
    return m.entities.layout_objects.values()


def _fields(m: DocumentModel):
    return m.entities.fields.values()


def _ae(m: DocumentModel):
    return [f.auto_enter for f in _fields(m) if f.auto_enter is not None]


def _val(m: DocumentModel):
    return [f.validation for f in _fields(m) if f.validation is not None]


def _sides(m: DocumentModel):
    for rel in m.entities.relationships.values():
        for side in (rel.options.left, rel.options.right):
            if side is not None:
                yield side


def _comment_shown(step) -> bool:
    """A comment step whose text has something after its leading "#" (a "####" banner counts)."""
    if step.name != COMMENT_STEP:
        return False
    return any(line.strip()[1:].strip() if line.strip().startswith("#") else line.strip()
               for line in step_text(step).splitlines())


def _variable_name(step) -> Optional[str]:
    for p in step.params or []:
        if p.get("kind") == "variable" and p.get("name"):
            return p["name"]
    return (step.parameters or {}).get("variable")


def _variable_shown(step) -> bool:
    name = _variable_name(step)
    return step.name == "Set Variable" and bool(name) and name in step_text(step)


def _calcs_shown(m: DocumentModel) -> int:
    """Step calculations whose whole text appears in the step as rendered."""
    shown = 0
    for step in _steps(m):
        text = comparable(step_text(step))
        for calc in step.calculations:
            calc_text = comparable(calc.text)
            if not calc_text or (calc.slot == "repetition" and calc_text == "1"):
                continue
            if calc_text in text:
                shown += 1
    return shown


def _privilege_rows(m: DocumentModel, category: str) -> int:
    return sum(len(getattr(ps, category).custom or []) for ps in m.entities.privilege_sets.values()
               if getattr(ps, category) is not None)


def _list_type(m: DocumentModel, kind: str) -> int:
    return sum(1 for vl in m.entities.value_lists.values() if vl.list_type == kind)


MEASURES: list[Measure] = [
    # Catalogs
    Measure("tables", "Catalogs", "Tables", lambda m: len(m.entities.tables)),
    Measure("fields", "Catalogs", "Fields", lambda m: len(m.entities.fields)),
    Measure("table_occurrences", "Catalogs", "Table occurrences", lambda m: len(m.entities.table_occurrences)),
    Measure("relationships", "Catalogs", "Relationships", lambda m: len(m.entities.relationships)),
    Measure("layouts", "Catalogs", "Layouts", lambda m: len(m.entities.layouts)),
    Measure("layout_objects", "Catalogs", "Layout objects", lambda m: len(m.entities.layout_objects)),
    Measure("scripts", "Catalogs", "Scripts", lambda m: len(m.entities.scripts)),
    Measure("script_steps", "Catalogs", "Script steps", lambda m: len(m.entities.script_steps)),
    Measure("custom_functions", "Catalogs", "Custom functions", lambda m: len(m.entities.custom_functions)),
    Measure("value_lists", "Catalogs", "Value lists", lambda m: len(m.entities.value_lists)),
    Measure("privilege_sets", "Catalogs", "Privilege sets", lambda m: len(m.entities.privilege_sets)),
    Measure("accounts", "Catalogs", "Accounts", lambda m: len(m.entities.accounts)),
    Measure("extended_privileges", "Catalogs", "Extended privileges", lambda m: len(m.entities.extended_privileges)),
    Measure("custom_menus", "Catalogs", "Custom menus", lambda m: len(m.entities.custom_menus)),
    Measure("custom_menu_sets", "Catalogs", "Custom menu sets", lambda m: len(m.entities.custom_menu_sets)),
    Measure("themes", "Catalogs", "Themes", lambda m: len(m.entities.themes)),
    Measure("file_access", "Catalogs", "File Access authorizations", lambda m: len(m.entities.file_references)),
    Measure("external_data_sources", "Catalogs", "External data sources", lambda m: len(m.external_data_sources)),
    Measure("graph_notes", "Catalogs", "Relationship graph notes", lambda m: len(m.graph_notes)),
    # Scripts
    Measure("steps_with_filemaker_text", "Scripts", "Steps shown as FileMaker prints them",
            lambda m: sum(1 for s in _steps(m) if s.fm_text is not None),
            "Steps without it are rebuilt from their parameters."),
    Measure("comment_steps_with_text", "Scripts", "Comments with text shown",
            lambda m: sum(1 for s in _steps(m) if _comment_shown(s))),
    Measure("set_variable_names", "Scripts", "Set Variable names shown",
            lambda m: sum(1 for s in _steps(m) if _variable_shown(s)), "The name appears in the step's text."),
    Measure("step_calculations", "Scripts", "Step calculations shown in full", _calcs_shown,
            "Each calculation's whole text appears in its step's text."),
    Measure("scripts_full_access", "Scripts", "Scripts run with full access",
            lambda m: sum(1 for s in m.entities.scripts.values() if s.run_with_full_access)),
    Measure("scripts_hidden", "Scripts", "Scripts left out of the Scripts menu",
            lambda m: sum(1 for s in m.entities.scripts.values() if s.show_in_menu is False)),
    Measure("file_script_triggers", "Scripts", "File Options script triggers",
            lambda m: len(m.file_options.script_triggers) if m.file_options else 0),
    Measure("layout_script_triggers", "Scripts", "Layout script triggers",
            lambda m: sum(len(lay.script_triggers) for lay in m.entities.layouts.values())),
    Measure("object_script_triggers", "Scripts", "Layout object script triggers",
            lambda m: sum(len(o.script_triggers) for o in _objects(m))),
    # Buttons
    Measure("button_actions", "Buttons", "Button actions (all kinds)",
            lambda m: sum(1 for o in _objects(m) if o.button_script_doc_id or o.button_step)),
    Measure("grouped_button_actions", "Buttons", "Button group actions",
            lambda m: sum(1 for o in _objects(m) if o.button_kind == "buttonGroup")),
    Measure("popover_button_actions", "Buttons", "Popover button actions",
            lambda m: sum(1 for o in _objects(m) if o.button_kind == "popoverButton")),
    # Layouts
    Measure("layout_parts", "Layouts", "Layout parts", lambda m: sum(len(lay.parts) for lay in m.entities.layouts.values())),
    Measure("sub_summary_break_fields", "Layouts", "Sub-summary break fields",
            lambda m: sum(1 for lay in m.entities.layouts.values() for p in lay.parts if p.break_field_doc_id)),
    Measure("layout_menu_sets", "Layouts", "Layouts with their own menu set",
            lambda m: sum(1 for lay in m.entities.layouts.values() if lay.menu_set)),
    Measure("value_list_controls", "Layouts", "Value lists on field controls",
            lambda m: sum(1 for o in _objects(m) if o.value_list_doc_id)),
    Measure("portals", "Layouts", "Portals", lambda m: sum(1 for o in _objects(m) if o.portal is not None)),
    Measure("sorted_portals", "Layouts", "Sorted portals",
            lambda m: sum(1 for o in _objects(m) if o.portal is not None and o.portal.sort)),
    Measure("filtered_portals", "Layouts", "Filtered portals",
            lambda m: sum(1 for o in _objects(m) if any(c.role == "portalFilter" for c in o.calculations))),
    Measure("portals_allow_deletion", "Layouts", "Portals allowing record deletion",
            lambda m: sum(1 for o in _objects(m) if o.portal is not None and o.portal.allow_deletion)),
    Measure("tooltips", "Layouts", "Tooltips",
            lambda m: sum(1 for o in _objects(m) if any(c.role == "tooltip" for c in o.calculations))),
    # Fields
    Measure("field_comments", "Fields", "Field comments", lambda m: sum(1 for f in _fields(m) if f.comment)),
    Measure("field_annotations", "Fields", "Field annotations", lambda m: sum(1 for f in _fields(m) if f.annotation)),
    Measure("calculation_fields", "Fields", "Field calculations",
            lambda m: sum(1 for f in _fields(m) if f.calculation)),
    Measure("stored_flag_known", "Fields", "Stored / unstored known",
            lambda m: sum(1 for f in _fields(m) if f.storage.stored is not None)),
    Measure("summary_operations", "Fields", "Summary operations",
            lambda m: sum(1 for f in _fields(m) if f.summary_operation)),
    Measure("summary_sources", "Fields", "Summary source fields",
            lambda m: sum(1 for f in _fields(m) if f.summary_field_doc_id)),
    Measure("auto_enter", "Fields", "Auto-enter options",
            lambda m: sum(1 for a in _ae(m) if a.type != "none")),
    Measure("lookups", "Fields", "Looked-up values", lambda m: sum(1 for a in _ae(m) if a.lookup_field)),
    Measure("prohibit_modification", "Fields", "Prohibit modification",
            lambda m: sum(1 for a in _ae(m) if a.no_modify_auto_enter)),
    Measure("validation_rules", "Fields", "Fields with validation", lambda m: len(_val(m))),
    Measure("validation_calculations", "Fields", "Validation calculations",
            lambda m: sum(1 for v in _val(m) if v.has_calculation)),
    Measure("validation_messages", "Fields", "Validation messages", lambda m: sum(1 for v in _val(m) if v.message)),
    Measure("validation_strict", "Fields", "Strict data types", lambda m: sum(1 for v in _val(m) if v.strict_type)),
    Measure("validation_max_size", "Fields", "Maximum characters", lambda m: sum(1 for v in _val(m) if v.max_characters)),
    Measure("external_container_storage", "Fields", "Containers stored externally",
            lambda m: sum(1 for f in _fields(m) if f.storage.external_storage)),
    # Relationships
    Measure("join_predicates", "Relationships", "Join predicates",
            lambda m: sum(len(r.predicates) for r in m.entities.relationships.values())),
    Measure("relationship_allow_create", "Relationships", "Sides allowing record creation",
            lambda m: sum(1 for s in _sides(m) if s.allow_create)),
    Measure("relationship_delete", "Relationships", "Sides deleting related records",
            lambda m: sum(1 for s in _sides(m) if s.delete)),
    Measure("relationship_sorts", "Relationships", "Sorted sides", lambda m: sum(1 for s in _sides(m) if s.sort)),
    # Value lists
    Measure("value_lists_custom", "Value lists", "Custom value lists", lambda m: _list_type(m, "customValues")),
    Measure("value_lists_field", "Value lists", "Value lists from a field", lambda m: _list_type(m, "field")),
    Measure("value_lists_external", "Value lists", "Value lists from another file", lambda m: _list_type(m, "external")),
    Measure("value_lists_external_targets", "Value lists", "Other-file lists named",
            lambda m: sum(1 for vl in m.entities.value_lists.values()
                          if vl.external_value_list is not None or "external list" in vl.missing),
            "Includes lists FileMaker reports as missing in the other file."),
    Measure("value_lists_source_fields", "Value lists", "Source fields",
            lambda m: sum(1 for vl in m.entities.value_lists.values()
                          if vl.source_field_doc_id or "source field" in vl.missing)),
    Measure("value_lists_related_only", "Value lists", "Related values only",
            lambda m: sum(1 for vl in m.entities.value_lists.values() if vl.related_from_to_doc_id)),
    Measure("value_lists_second_field", "Value lists", "Second fields",
            lambda m: sum(1 for vl in m.entities.value_lists.values()
                          if vl.second_field_doc_id or "second field" in vl.missing),
            "Includes fields FileMaker reports as missing."),
    Measure("custom_value_lines", "Value lists", "Custom value lines",
            lambda m: sum(len(vl.values) for vl in m.entities.value_lists.values() if vl.list_type == "customValues")),
    # Privileges
    Measure("privilege_rows_records", "Privileges", "Custom record privileges (rows)",
            lambda m: _privilege_rows(m, "records")),
    Measure("privilege_rows_layouts", "Privileges", "Custom layout privileges (rows)",
            lambda m: _privilege_rows(m, "layouts")),
    Measure("privilege_rows_value_lists", "Privileges", "Custom value list privileges (rows)",
            lambda m: _privilege_rows(m, "value_lists")),
    Measure("privilege_rows_scripts", "Privileges", "Custom script privileges (rows)",
            lambda m: _privilege_rows(m, "scripts")),
    Measure("privilege_limited_calcs", "Privileges", "Limited-access calculations",
            lambda m: sum(len(item.calculations) for ps in m.entities.privilege_sets.values()
                          for cat in (ps.records, ps.layouts, ps.value_lists, ps.scripts)
                          if cat is not None for item in cat.custom or [])),
    # File
    Measure("file_default_layout", "File", "Default layout on open",
            lambda m: 1 if m.file_options and m.file_options.default_layout else 0),
]


def build_coverage(model: DocumentModel) -> CoverageReport:
    inventory = model.coverage_inventory
    if inventory is None:
        return CoverageReport(available=False)
    rows = [
        CoverageRow(area=ms.area, key=ms.key, label=ms.label, in_xml=inventory.measures.get(ms.key, 0),
                    in_docs=ms.count(model), note=ms.note)
        for ms in MEASURES
    ]
    return CoverageReport(available=True, rows=rows, unrecognised=inventory.unrecognised,
                          skipped=inventory.skipped)
