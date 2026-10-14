"""What the XML contains, counted independently of the extractors, for the coverage report.

Two halves:

* **measures**: counts of things an analysis needs (scripts, step comments, grouped-button
  actions, relationship options, ...), taken straight from the XML with XPath. The report
  (``analyze/coverage.py``) sets each against the same thing counted in the finished model,
  so anything the extractors drop shows up as a shortfall.
* **unrecognised**: under each kind of element (a Field, a LayoutObject, a script step, ...),
  every child element and attribute name the converter has no rule for. A new FileMaker
  option shows up here the first time an export carries it, instead of vanishing. Names the
  converter deliberately leaves out (images, CSS, layout geometry) are counted under
  **skipped**, so the report says what was left out on purpose.

Keys in ``MEASURE_XPATHS`` must match ``analyze.coverage.MEASURES``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from lxml import etree

AA = "/FMSaveAsXML/Structure/AddAction"
_STEPS = f"{AA}/StepsForScripts/Script/ObjectList/Step"
_LAYOUTS = (f"{AA}/LayoutCatalog/Layout[not(@isFolder='True') and not(@isFolder='Marker') "
            "and not(@isSeparatorItem='True')]")
_SCRIPTS = (f"{AA}/ScriptCatalog/Script[not(@isFolder='True') and not(@isFolder='Marker') "
            "and not(@isSeparatorItem='True')]")
_FIELDS = f"{AA}/FieldsForTables/FieldCatalog/ObjectList/Field"
_OBJECTS = f"{_LAYOUTS}//LayoutObject"
_REL = f"{AA}/RelationshipCatalog/Relationship"
_VL_OPTIONS = f"{AA}/OptionsForValueLists/ValueList"
_VL_CATALOG = f"{AA}/ValueListCatalog//ValueList"
# A value list's details: in <OptionsForValueLists>, or inline in the catalog entry (FileMaker 26)
_VL_DETAILS = f"({_VL_OPTIONS} | {_VL_CATALOG}[CustomValues or Field or External])"
_PRIV_ACCESS = f"{AA}/PrivilegeSetsCatalog/ObjectList/PrivilegeSet/access"
_META = "/FMSaveAsXML/Metadata/AddAction"
_ACTION = "action[ScriptReference[@name!=''] or Step]"


def _validation_rule(v: str) -> str:
    """XPath predicate: a ``<Validation>`` that sets any rule (the default element sets none)."""
    return (f"{v}[@notEmpty='True' or @unique='True' or @existing='True' or Strict or Message[normalize-space()]"
            " or MaximumSize or MaximumCharacters or Range or ValueListReference[@name!='']"
            " or Calculated[not(@enable='False')] or Calculation or MessageCalc[not(@enable='False')]]")


# key -> XPath counted with count(...). Numbers that need more than a count are in _FUNCS.
MEASURE_XPATHS: dict[str, str] = {
    # Catalogs
    "tables": f"{AA}/BaseTableCatalog/BaseTable",
    "fields": _FIELDS,
    "table_occurrences": f"{AA}/TableOccurrenceCatalog/TableOccurrence",
    "relationships": _REL,
    "layouts": _LAYOUTS,
    "layout_objects": _OBJECTS,
    "scripts": _SCRIPTS,
    "script_steps": _STEPS,
    "custom_functions": f"{AA}/CustomFunctionsCatalog//CustomFunction",
    "value_lists": _VL_CATALOG,
    "privilege_sets": f"{AA}/PrivilegeSetsCatalog/ObjectList/PrivilegeSet",
    "accounts": f"{AA}/AccountsCatalog/ObjectList/Account",
    "extended_privileges": f"{AA}/ExtendedPrivilegesCatalog/ObjectList/ExtendedPrivilege",
    "custom_menus": f"{AA}/CustomMenuCatalog//CustomMenu",
    "custom_menu_sets": f"{AA}/CustomMenuSetCatalog/ObjectList/CustomMenuSet",
    "themes": f"{AA}/ThemeCatalog//Theme",
    "file_access": f"{AA}/FileAccessCatalog/ObjectList/Authorization",
    "external_data_sources": f"{AA}/ExternalDataSourceCatalog//ExternalDataSource",
    "graph_notes": f"{AA}/TableOccurrenceCatalog/TableOccurrenceNotes//LayoutObject",
    # Scripts
    "comment_steps_with_text": f"{_STEPS}[@name='# (comment)'][ParameterValues/Parameter/Comment[normalize-space(@value)!='']]",
    "set_variable_names": f"{_STEPS}[@name='Set Variable'][ParameterValues/Parameter[@type='Variable']/Name[@value!='']]",
    "scripts_full_access": f"{_SCRIPTS}[Options/@runwithfullaccess='True']",
    "scripts_hidden": f"{_SCRIPTS}[Options/@hidden='True']",
    "file_script_triggers": f"{_META}/ScriptTriggers/ScriptTrigger[ScriptReference/@name!='']",
    "layout_script_triggers": f"{_LAYOUTS}/ScriptTriggers/ScriptTrigger[ScriptReference/@name!='']",
    "object_script_triggers": f"{_OBJECTS}/ScriptTriggers/ScriptTrigger[ScriptReference/@name!='']",
    # Buttons
    "button_actions": f"{_OBJECTS}/*/{_ACTION}",
    "grouped_button_actions": f"{_OBJECTS}/GroupedButton/{_ACTION}",
    "popover_button_actions": f"{_OBJECTS}/PopoverButton/{_ACTION}",
    # Layouts
    "layout_parts": f"{_LAYOUTS}/PartsList/Part",
    "sub_summary_break_fields": f"{_LAYOUTS}/PartsList/Part/Definition/FieldReference[@name!='']",
    "layout_menu_sets": f"{_LAYOUTS}/MenuSet/CustomMenuSetReference[@name!='' and @name!='[File Default]']",
    "value_list_controls": f"{_OBJECTS}/Field/Display/ValueListReference[@name!='']",
    "portals": f"{_OBJECTS}/Portal",
    "sorted_portals": f"{_OBJECTS}/Portal[SortSpecification[@value='True']//Sort]",
    "filtered_portals": f"{_OBJECTS}/Portal[Calculation]",
    "portals_allow_deletion": f"{_OBJECTS}/Portal[number(Options) mod 8 >= 4]",  # bit 4
    "tooltips": f"{_OBJECTS}/Tooltip[.//Calculation]",
    # Fields
    "field_comments": f"{_FIELDS}[normalize-space(@comment)!='']",
    "field_annotations": f"{_FIELDS}/Annotation[normalize-space()!='']",
    "calculation_fields": f"{_FIELDS}[Calculation/Text[normalize-space()!='']]",  # FileMaker can export an empty formula
    "stored_flag_known": f"{_FIELDS}/Storage[@storeCalculationResults]",
    "summary_operations": f"{_FIELDS}/SummaryInfo[@operation!='']",
    "summary_sources": f"{_FIELDS}/SummaryInfo/SummaryField/FieldReference[@name!='']",
    "auto_enter": f"{_FIELDS}/AutoEnter[@type!='']",
    "lookups": f"{_FIELDS}/AutoEnter[@type='Looked_up' or @type='Lookup']",
    "prohibit_modification": f"{_FIELDS}/AutoEnter[@prohibitModification='True']",
    "validation_rules": _validation_rule(f"{_FIELDS}/Validation"),
    "validation_calculations": f"{_FIELDS}/Validation/Calculated[not(@enable='False')]",
    "validation_messages": f"{_FIELDS}/Validation/Message[normalize-space()!='']",
    "validation_strict": f"{_FIELDS}/Validation/Strict",
    "validation_max_size": f"{_FIELDS}/Validation[MaximumSize or MaximumCharacters]",
    "external_container_storage": f"{_FIELDS}/Storage/Remote",
    # Relationships
    "join_predicates": f"{_REL}/JoinPredicateList/JoinPredicate",
    "relationship_allow_create": f"{_REL}/*[@cascadeCreate='True']",
    "relationship_delete": f"{_REL}/*[@cascadeDelete='True']",
    "relationship_sorts": f"{_REL}/*[SortSpecification[@value='True']//Sort]",
    # Value lists
    "value_lists_custom": f"{_VL_CATALOG}[Source/@value='Custom']",
    "value_lists_field": f"{_VL_CATALOG}[Source/@value='FromField']",
    "value_lists_external": f"{_VL_CATALOG}[Source/@value='External']",
    "value_lists_external_targets": f"{_VL_DETAILS}/External[DataSourceReference and ValueListReference]",
    "value_lists_source_fields": f"{_VL_DETAILS}[Source/@value='FromField']",  # each has one, possibly missing
    "value_lists_related_only": f"{_VL_DETAILS}/Field/ShowRelated[@value='True']",
    "value_lists_second_field": f"{_VL_DETAILS}/Field/SecondaryField[FieldReference]",
    # Privileges
    "privilege_rows_records": f"{_PRIV_ACCESS}/Records/Custom/ObjectList/*",
    "privilege_rows_layouts": f"{_PRIV_ACCESS}/Layouts/Custom/ObjectList/*",
    "privilege_rows_value_lists": f"{_PRIV_ACCESS}/ValueLists/Custom/ObjectList/*",
    "privilege_rows_scripts": f"{_PRIV_ACCESS}/Scripts/Custom/ObjectList/*",
    "privilege_limited_calcs": f"{_PRIV_ACCESS}/*/Custom/ObjectList/*/*[.//Calculation]",
    # File
    "file_default_layout": f"{_META}/Defaults/LayoutReference[@name!='']",
}


def _custom_value_lines(root: etree._Element) -> int:
    """Lines of all custom value lists, blank separator lines included (trailing line breaks are not values)."""
    total = 0
    for text in root.xpath(f"{_VL_DETAILS}[Source/@value='Custom']/CustomValues/Text"):
        lines = (text.text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        total += len(lines)
    return total


def _step_texts(root: etree._Element) -> int:
    """Steps whose ``<DDRREF kind="StepText">`` points at an entry of ``DDR_INFO/Script``."""
    keys: set[str] = set()
    for entry in root.xpath("/FMSaveAsXML/DDR_INFO/Script/ObjectList/*[@datatype='StepText']"):
        keys.add(entry.tag if entry.tag != "_" else f"#{entry.get('hash')}")
    found = 0
    for ref in root.xpath(f"{_STEPS}/DDRREF[@kind='StepText']"):
        key = (ref.text or "").strip()
        if (key if key and key != "_" else f"#{ref.get('hash')}") in keys:
            found += 1
    return found


def _step_calcs(root: etree._Element) -> int:
    """Calculations inside steps, without default repetition ``1``s (FileMaker doesn't print those)."""
    total = 0
    for calc in root.xpath(f"{_STEPS}/ParameterValues//Calculation[Text]"):
        text = (calc.findtext("Text") or "").strip()
        in_repetition = any(a.tag == "repetition" for a in calc.iterancestors())
        if text and not (in_repetition and text == "1"):
            total += 1
    return total


_FUNCS: dict[str, Callable[[etree._Element], int]] = {
    "steps_with_filemaker_text": _step_texts,
    "step_calculations": _step_calcs,
    "custom_value_lines": _custom_value_lines,
}


# ---------------------------------------------------------------------------
# Unrecognised elements and attributes
# ---------------------------------------------------------------------------

class Context:
    """Children and attributes of one kind of element, sorted into read / deliberately skipped."""

    def __init__(self, label: str, xpath: str, read: str = "", skipped: str = "",
                 read_attrs: str = "", skipped_attrs: str = "") -> None:
        self.label, self.xpath = label, xpath
        self.read, self.skipped = set(read.split()), set(skipped.split())
        self.read_attrs, self.skipped_attrs = set(read_attrs.split()), set(skipped_attrs.split())


_COMMON_SKIPPED = "UUID TagList SourceUUID OwnerID"  # bookkeeping on every catalog entry

CONTEXTS: list[Context] = [
    Context("Catalogs (Structure/AddAction)", AA,
            read="BaseTableCatalog TableOccurrenceCatalog ValueListCatalog FieldsForTables CustomMenuCatalog "
                 "ScriptCatalog ThemeCatalog LayoutCatalog PrivilegeSetsCatalog ExtendedPrivilegesCatalog "
                 "AccountsCatalog StepsForScripts FileAccessCatalog RelationshipCatalog CustomMenuSetCatalog "
                 "ExternalDataSourceCatalog CustomFunctionsCatalog OptionsForValueLists CalcsForCustomFunctions",
            skipped="BaseDirectoryCatalog LibraryCatalog PasteIndexList",
            read_attrs="membercount"),  # bookkeeping; absent when split catalogs are merged
    Context("File options (Metadata)", _META,
            read="Minimum Login Defaults ScriptTriggers Encryption SavePassword ShowSignInFields "
                 "HideClientSharing HideWebDirectSharing UseDefaultFields",
            skipped="PageSetup IconData Text", read_attrs="membercount"),
    Context("Field", _FIELDS,
            read="AutoEnter Validation Storage Calculation SummaryInfo Annotation",
            skipped=f"{_COMMON_SKIPPED} DisplayNames FieldReference",
            read_attrs="id name fieldtype datatype comment"),
    Context("Field / Validation", f"{_FIELDS}/Validation",
            read="NotEmpty Required Unique MaximumCharacters MaximumSize ValueListReference Message MessageCalc "
                 "Strict Calculation Calculated Range",
            read_attrs="type allowOverride notEmpty unique existing alwaysValidate"),
    Context("Field / Auto-enter", f"{_FIELDS}/AutoEnter",
            read="Calculated SerialNumber ConstantData Looked_up",
            read_attrs="type prohibitModification alwaysEvaluate overwriteExisting"),
    Context("Field / Storage", f"{_FIELDS}/Storage",
            read="Remote", skipped="LanguageReference",
            read_attrs="global maxRepetitions index autoIndex storeCalculationResults"),
    Context("Table occurrence", f"{AA}/TableOccurrenceCatalog/TableOccurrence",
            read="BaseTableSourceReference CoordRect", skipped=f"{_COMMON_SKIPPED} Color",
            read_attrs="View id name type", skipped_attrs="height"),
    Context("Relationship", _REL,
            read="LeftTable RightTable JoinPredicateList", skipped=_COMMON_SKIPPED, read_attrs="id"),
    Context("Relationship side", f"{_REL}/LeftTable | {_REL}/RightTable",
            read="TableOccurrenceReference SortSpecification", read_attrs="cascadeCreate cascadeDelete type"),
    Context("Layout", _LAYOUTS,
            read="PartsList TableOccurrenceReference LayoutThemeReference ScriptTriggers MenuSet",
            skipped=f"{_COMMON_SKIPPED} GridStyle ClientType Options TableView LocalCSS FixedMargins "
                    "LayoutReference ColumnCount LayoutCustomStyle",
            read_attrs="id name isFolder isSeparatorItem", skipped_attrs="width"),
    Context("Layout part", f"{_LAYOUTS}/PartsList/Part", read="Definition ObjectList",
            read_attrs="type kind name"),
    Context("Layout object", _OBJECTS,
            read="Bounds Field Text Button PopoverButton GroupedButton ButtonBar Portal ScriptTriggers ObjectList "
                 "Tooltip Conditions External TabControl TabPanel SlideControl SlidePanel Title DisplayCalculations",
            skipped=f"{_COMMON_SKIPPED} Options LocalCSS ExtendedAttributes FieldList Accessibility Line Rectangle "
                    "RoundedRectangle Oval Graphic TabOrder",
            read_attrs="id type name kind", skipped_attrs="hash position Options Orientation"),
    Context("Portal", f"{_OBJECTS}/Portal",
            read="TableOccurrenceReference Options SortSpecification Calculation ObjectList"),
    Context("Script", _SCRIPTS, read="Options", skipped=_COMMON_SKIPPED,
            read_attrs="id name isFolder isSeparatorItem"),
    Context("Script options", f"{_SCRIPTS}/Options",
            read_attrs="hidden runwithfullaccess SiriShortcutVisible", skipped_attrs="access compatibility"),
    Context("Script step", _STEPS, read="ParameterValues DDRREF", skipped=f"{_COMMON_SKIPPED} Options",
            read_attrs="index id name enable", skipped_attrs="hash breakpoint"),
    Context("Value list", _VL_CATALOG, read="Source CustomValues Field External",
            skipped=_COMMON_SKIPPED, read_attrs="id name"),
    Context("Value list options", _VL_OPTIONS,
            read="ValueListReference Source Field CustomValues External"),
    Context("Value list from field", f"{_VL_DETAILS}/Field", read="PrimaryField SecondaryField ShowRelated"),
    Context("Privilege set", f"{AA}/PrivilegeSetsCatalog/ObjectList/PrivilegeSet",
            read="Description access", skipped=_COMMON_SKIPPED, read_attrs="id name"),
    Context("Privilege set access", _PRIV_ACCESS, read="Records Layouts ValueLists Scripts Other",
            read_attrs="default"),
    Context("Account", f"{AA}/AccountsCatalog/ObjectList/Account",
            read="Description PrivilegeSetReference AccountName", skipped=f"{_COMMON_SKIPPED} Authentication",
            read_attrs="id type enable", skipped_attrs="kind"),
    Context("Custom function", f"{AA}/CustomFunctionsCatalog//CustomFunction",
            read="Calculation ObjectList Display", skipped=_COMMON_SKIPPED, read_attrs="id name access"),
    Context("Custom menu", f"{AA}/CustomMenuCatalog//CustomMenu",
            read="MenuItemList Conditions Base Options Comment", skipped=_COMMON_SKIPPED, read_attrs="id name"),
    Context("Extended privilege", f"{AA}/ExtendedPrivilegesCatalog/ObjectList/ExtendedPrivilege",
            read="Description ObjectList", skipped=_COMMON_SKIPPED, read_attrs="id name"),
    Context("External data source", f"{AA}/ExternalDataSourceCatalog//ExternalDataSource",
            read="File", skipped=_COMMON_SKIPPED, read_attrs="id name type"),
    Context("Base table", f"{AA}/BaseTableCatalog/BaseTable", skipped=_COMMON_SKIPPED,
            read_attrs="id name comment"),
]


def _local_tree(root: etree._Element) -> etree._Element:
    """The tree with namespaces stripped (a copy, only when there are any), so plain XPath works."""
    if not (isinstance(root.tag, str) and root.tag.startswith("{")):
        return root
    root = copy.deepcopy(root)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def xml_inventory(root: etree._Element) -> dict[str, Any]:
    """Counts and unrecognised names for one v2 SaveAsXML document."""
    root = _local_tree(root)
    measures = {key: int(root.xpath(f"count({xp})")) for key, xp in MEASURE_XPATHS.items()}
    measures.update({key: fn(root) for key, fn in _FUNCS.items()})

    unrecognised: dict[str, dict[str, int]] = {}
    skipped: dict[str, dict[str, int]] = {}
    for ctx in CONTEXTS:
        for elem in root.xpath(ctx.xpath):
            for child in elem:
                if not isinstance(child.tag, str):
                    continue
                bucket = (None if child.tag in ctx.read else
                          skipped if child.tag in ctx.skipped else unrecognised)
                if bucket is not None:
                    names = bucket.setdefault(ctx.label, {})
                    names[child.tag] = names.get(child.tag, 0) + 1
            for name in elem.attrib:
                bucket = (None if name in ctx.read_attrs else
                          skipped if name in ctx.skipped_attrs else unrecognised)
                if bucket is not None:
                    names = bucket.setdefault(ctx.label, {})
                    names[f"@{name}"] = names.get(f"@{name}", 0) + 1
    return {"measures": measures, "unrecognised": unrecognised, "skipped": skipped}
