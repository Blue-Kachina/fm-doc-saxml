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
from .extractors.chunk_lists import extract_chunk_lists
from .extractors.custom_functions import extract_custom_functions
from .extractors.value_lists import extract_value_lists
from .extractors.external_data_sources import extract_external_data_sources
from .extractors.privileges import extract_privilege_sets
from .extractors.accounts import extract_accounts
from .extractors.extended_privileges import extract_extended_privileges
from .extractors.custom_menus import extract_custom_menus, extract_custom_menu_sets
from .extractors.themes import extract_themes
from .extractors.file_access import extract_file_references


@dataclass
class RawModel:
    """Unprocessed records straight from the XML — before normalization."""

    file_name: str = ""
    filemaker_version: str = "unknown"
    solution_name: str = ""
    fmp_file_name: str = ""
    file_uuid: str = ""
    external_data_sources: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    table_occurrences: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    layouts: list[dict[str, Any]] = field(default_factory=list)
    scripts: list[dict[str, Any]] = field(default_factory=list)
    custom_functions: list[dict[str, Any]] = field(default_factory=list)
    value_lists: list[dict[str, Any]] = field(default_factory=list)
    privilege_sets: list[dict[str, Any]] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    extended_privileges: list[dict[str, Any]] = field(default_factory=list)
    custom_menus: list[dict[str, Any]] = field(default_factory=list)
    custom_menu_sets: list[dict[str, Any]] = field(default_factory=list)
    themes: list[dict[str, Any]] = field(default_factory=list)
    file_references: list[dict[str, Any]] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def parse_savexml(xml_path: Path, fragments: list[Path] | None = None) -> RawModel:
    """Parse a FileMaker SaveAsXML file and return a RawModel.

    ``xml_path`` may also be the folder of a "separate catalogs" export, holding one
    XML per catalog; pass ``fragments`` to name those XMLs explicitly (otherwise every
    ``*.xml`` in the folder is used). They are merged back into one document first.
    """
    raw = RawModel(file_name=xml_path.name)

    try:
        if fragments or xml_path.is_dir():
            paths = fragments or sorted(p for p in xml_path.iterdir() if p.suffix.lower() == ".xml")
            if not paths:
                raw.parse_warnings.append("XML parse error: no catalog XML files in this folder")
                return raw
            root = merge_split_catalogs([etree.parse(str(p)).getroot() for p in paths])
        else:
            root = etree.parse(str(xml_path)).getroot()
    except etree.XMLSyntaxError as exc:
        raw.parse_warnings.append(f"XML parse error: {exc}")
        return raw

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag == "FMSaveAsXML" and _is_v2_format(root):
        return _parse_v2(xml_path, root, raw)
    return _parse_v1(xml_path, root, raw)


def merge_split_catalogs(roots: list) -> etree._Element:
    """Rebuild one whole-file document from the per-catalog documents of a split export.

    Each fragment is a full ``FMSaveAsXML`` holding one catalog in
    ``Structure/AddAction`` (or the ``Metadata`` block), plus its own ``DDR_INFO``.
    The merged document has every catalog in a single ``AddAction`` and every
    ``DDR_INFO`` section's entries combined, which is the shape ``_parse_v2`` reads.
    The fragments' elements are moved, not copied.
    """
    first = roots[0]
    ns = first.tag[: first.tag.index("}") + 1] if first.tag.startswith("{") else ""
    merged = etree.Element(first.tag, dict(first.attrib), nsmap=first.nsmap)
    add_action = etree.SubElement(etree.SubElement(merged, f"{ns}Structure"), f"{ns}AddAction")
    ddr_info = etree.Element(f"{ns}DDR_INFO")

    for root in roots:
        for child in list(root):
            if not isinstance(child.tag, str):
                continue
            name = strip_namespace(child.tag)
            if name == "Structure":
                for action in child:
                    if isinstance(action.tag, str) and strip_namespace(action.tag) == "AddAction":
                        add_action.extend(list(action))
            elif name == "DDR_INFO":
                _merge_by_name(ddr_info, child, depth=2)  # DDR_INFO / <section> / ObjectList / entries
            else:
                merged.append(child)

    merged.append(ddr_info)
    return merged


def _merge_by_name(dst, src, depth: int) -> None:
    """Move ``src``'s children into ``dst``, merging same-named containers ``depth`` levels down."""
    for child in list(src):
        if not isinstance(child.tag, str):
            continue
        same = find_child(dst, strip_namespace(child.tag)) if depth > 0 else None
        if same is None:
            dst.append(child)
        else:
            _merge_by_name(same, child, depth - 1)


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
    raw.fmp_file_name = file_attr
    raw.file_uuid = root.get("UUID", "") or root.get("uuid", "")

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

    # Tokenized calcs with FileMaker's own resolution of the fields / custom functions they use
    chunk_lists = extract_chunk_lists(root)

    raw.tables = extract_tables(container)
    raw.fields = extract_fields(container, v2_fields_elem=fields_for_tables, chunk_lists=chunk_lists)
    raw.table_occurrences = extract_table_occurrences(container)
    raw.relationships = extract_relationships(container)
    raw.layouts = extract_layouts(container, chunk_lists=chunk_lists)
    raw.scripts = extract_scripts(container, v2_steps_elem=steps_for_scripts, chunk_lists=chunk_lists)
    raw.custom_functions = extract_custom_functions(container, v2_calcs_elem=calcs_for_cf, chunk_lists=chunk_lists)
    raw.value_lists = extract_value_lists(container, v2_options_elem=options_for_vl)
    raw.privilege_sets = extract_privilege_sets(container)
    raw.accounts = extract_accounts(container)
    raw.extended_privileges = extract_extended_privileges(container)
    raw.custom_menus = extract_custom_menus(container, chunk_lists=chunk_lists)
    raw.custom_menu_sets = extract_custom_menu_sets(container)
    raw.themes = extract_themes(container)
    raw.file_references = extract_file_references(container)
    raw.external_data_sources = extract_external_data_sources(container)

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
    raw.accounts = extract_accounts(database_elem)
    raw.extended_privileges = extract_extended_privileges(database_elem)
    raw.custom_menus = extract_custom_menus(database_elem)
    raw.custom_menu_sets = extract_custom_menu_sets(database_elem)
    raw.themes = extract_themes(database_elem)
    raw.file_references = extract_file_references(database_elem)

    return raw
