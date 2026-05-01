"""Main entry point for parsing a FileMaker SaveAsXML file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from .version_detector import detect_version, strip_namespace
from .extractors._helpers import find_child
from .extractors.tables import extract_tables
from .extractors.fields import extract_fields
from .extractors.table_occurrences import extract_table_occurrences
from .extractors.relationships import extract_relationships
from .extractors.layouts import extract_layouts
from .extractors.scripts import extract_scripts
from .extractors.custom_functions import extract_custom_functions
from .extractors.value_lists import extract_value_lists
from .extractors.privileges import extract_privilege_sets


@dataclass
class RawModel:
    """Unprocessed records straight from the XML — before normalization."""

    file_name: str = ""
    filemaker_version: str = "unknown"
    solution_name: str = ""
    tables: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    table_occurrences: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    layouts: list[dict[str, Any]] = field(default_factory=list)
    scripts: list[dict[str, Any]] = field(default_factory=list)
    custom_functions: list[dict[str, Any]] = field(default_factory=list)
    value_lists: list[dict[str, Any]] = field(default_factory=list)
    privilege_sets: list[dict[str, Any]] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def parse_savexml(xml_path: Path) -> RawModel:
    """Parse a FileMaker SaveAsXML file and return a RawModel."""
    raw = RawModel(file_name=xml_path.name)

    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        raw.parse_warnings.append(f"XML parse error: {exc}")
        return raw

    root = tree.getroot()

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag == "FMSaveAsXML" and _is_v2_format(root):
        return _parse_v2(xml_path, root, raw)
    return _parse_v1(xml_path, root, raw)


def _is_v2_format(root) -> bool:
    """Return True for FMSaveAsXML v2.x format.

    v2 has a 'File' attribute (the .fmp12 filename) and a dotted version like '2.2.3.0'.
    v1 has only 'Version="1.0"' and no 'File' attribute.
    """
    if root.get("File") or root.get("file"):
        return True
    version = root.get("version") or root.get("Version") or ""
    return version.startswith("2.")


def _parse_v2(xml_path: Path, root, raw: RawModel) -> RawModel:
    """Handle FileMaker SaveAsXML v2.x format."""
    fm_source = root.get("Source", "")
    xml_version = root.get("version", "unknown")
    raw.filemaker_version = fm_source if fm_source else xml_version

    file_attr = root.get("File", "")
    raw.solution_name = file_attr.replace(".fmp12", "").replace(".fmp7", "") or xml_path.stem

    structure = find_child(root, "Structure")
    if structure is None:
        raw.parse_warnings.append("v2: Could not find <Structure> element.")
        return raw

    add_action = find_child(structure, "AddAction")
    if add_action is None:
        raw.parse_warnings.append("v2: Could not find <AddAction> element.")
        return raw

    container = add_action
    fields_for_tables = find_child(container, "FieldsForTables")
    options_for_vl = find_child(container, "OptionsForValueLists")
    calcs_for_cf = find_child(container, "CalcsForCustomFunctions")
    steps_for_scripts = find_child(container, "StepsForScripts")

    raw.tables = extract_tables(container)
    raw.fields = extract_fields(container, v2_fields_elem=fields_for_tables)
    raw.table_occurrences = extract_table_occurrences(container)
    raw.relationships = extract_relationships(container)
    raw.layouts = extract_layouts(container)
    raw.scripts = extract_scripts(container, v2_steps_elem=steps_for_scripts)
    raw.custom_functions = extract_custom_functions(container, v2_calcs_elem=calcs_for_cf)
    raw.value_lists = extract_value_lists(container, v2_options_elem=options_for_vl)
    raw.privilege_sets = extract_privilege_sets(container)

    return raw


def _parse_v1(xml_path: Path, root, raw: RawModel) -> RawModel:
    """Handle FileMaker SaveAsXML v1.x format."""
    raw.filemaker_version = detect_version(root)

    file_elem = find_child(root, "File")
    if file_elem is not None:
        raw.solution_name = (
            file_elem.get("name") or file_elem.get("Name") or file_elem.get("fileName") or ""
        )
        database_elem = find_child(file_elem, "Database")
    else:
        database_elem = find_child(root, "Database")

    if database_elem is None:
        raw.parse_warnings.append("Could not find <Database> element. XML structure may be unexpected.")
        return raw

    if not raw.solution_name:
        raw.solution_name = (
            database_elem.get("name") or database_elem.get("Name") or
            database_elem.get("fileName") or xml_path.stem
        )

    raw.tables = extract_tables(database_elem)
    raw.fields = extract_fields(database_elem)
    raw.table_occurrences = extract_table_occurrences(database_elem)
    raw.relationships = extract_relationships(database_elem)
    raw.layouts = extract_layouts(database_elem)
    raw.scripts = extract_scripts(database_elem)
    raw.custom_functions = extract_custom_functions(database_elem)
    raw.value_lists = extract_value_lists(database_elem)
    raw.privilege_sets = extract_privilege_sets(database_elem)

    return raw
