"""Pydantic entity models for the normalized FileMaker documentation model."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict

from .references import ExternalTarget


class CalcChunkRef(BaseModel):
    """A field or custom function FileMaker itself resolved inside a calculation (a ChunkList token)."""

    type: str                          # field | customFunction
    name: str
    table: Optional[str] = None        # for fields: the table occurrence it is reached through
    fmp_id: Optional[str] = Field(None, alias="fmpId")
    uuid: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class EntityCalculation(BaseModel):
    """A calculation an entity owns: a field's formula, a layout object's hide condition, ..."""

    role: str  # calculation, autoEnter, validation, hideCondition, tooltip, buttonParameter, ...
    text: str
    # None when there was no ChunkList (v1 export, or a calc FileMaker could not tokenize):
    # its references are then parsed from the text instead.
    chunk_refs: Optional[list[CalcChunkRef]] = Field(None, alias="chunkRefs")

    model_config = ConfigDict(populate_by_name=True)


class ScriptTriggerInfo(BaseModel):
    """A script trigger on a layout or layout object, e.g. OnLayoutEnter -> script."""

    event: str
    script_doc_id: str = Field(alias="scriptDocId")
    script_external: Optional[ExternalTarget] = Field(None, alias="scriptExternal")  # script in another file

    model_config = ConfigDict(populate_by_name=True)


class SourceXmlInfo(BaseModel):
    """Trace back to the originating XML location for debugging."""

    model_config = ConfigDict(populate_by_name=True)

    path: str
    line: Optional[int] = None


class StorageOptions(BaseModel):
    global_storage: bool = Field(False, alias="global")
    indexed: bool = False
    # Raw 3-state indexing mode ("None"/"Minimal"/"All") and the separate
    # auto-index flag — `indexed` above is a derived yes/no view of `index`.
    index: str = "None"
    auto_index: bool = Field(False, alias="autoIndex")
    max_repeat: int = Field(1, alias="maxRepeat")
    stored: Optional[bool] = None  # calculation fields: "Do not store calculation results" unchecked
    external_storage: Optional[str] = Field(None, alias="externalStorage")  # container stored externally: Secure | Open
    external_storage_directory: Optional[str] = Field(None, alias="externalStorageDirectory")

    model_config = ConfigDict(populate_by_name=True)


class AutoEnterOptions(BaseModel):
    type: str = "none"  # none, serial, data, calculation, lookup, modification
    value: Optional[str] = None
    calculation: Optional[str] = None
    no_modify_auto_enter: bool = False  # "Prohibit modification of value during data entry"
    overwrite_existing: Optional[bool] = Field(None, alias="overwriteExisting")  # False = "Do not replace existing value"
    serial_increment: Optional[str] = Field(None, alias="serialIncrement")
    serial_generate: Optional[str] = Field(None, alias="serialGenerate")  # OnCreation | OnCommit
    # Looked-up value: copied from this field, starting from the context TO
    lookup_table_occurrence: Optional[str] = Field(None, alias="lookupTableOccurrence")
    lookup_field: Optional[str] = Field(None, alias="lookupField")
    lookup_field_doc_id: Optional[str] = Field(None, alias="lookupFieldDocId")
    lookup_external: Optional[ExternalTarget] = Field(None, alias="lookupExternal")  # source field in another file
    lookup_context: Optional[str] = Field(None, alias="lookupContext")
    lookup_dont_copy_if_empty: Optional[bool] = Field(None, alias="lookupDontCopyIfEmpty")
    lookup_no_match: Optional[str] = Field(None, alias="lookupNoMatch")  # DoNotCopy | CopyNext | CopyPrevious | Constant
    lookup_no_match_value: Optional[str] = Field(None, alias="lookupNoMatchValue")

    model_config = ConfigDict(populate_by_name=True)


class ValidationOptions(BaseModel):
    required: bool = False
    not_empty: bool = False
    unique: bool = False
    max_characters: Optional[int] = None
    message: Optional[str] = None
    value_list_doc_id: Optional[str] = Field(None, alias="valueListDocId")  # "member of value list"
    existing: bool = False  # "Existing value"
    strict_type: Optional[str] = Field(None, alias="strictType")  # "Strict data type": Numeric, FourDigitYear, TimeOfDay
    has_calculation: bool = Field(False, alias="hasCalculation")  # text: the field's calculations, role "validation"
    has_message_calculation: bool = Field(False, alias="hasMessageCalculation")  # role "validationMessage"
    always_validate: Optional[bool] = Field(None, alias="alwaysValidate")  # False = "only if field has been modified"
    range: Optional[str] = None
    validate_on: Optional[str] = Field(None, alias="validateOn")  # Always | OnlyDuringDataEntry
    allow_override: Optional[bool] = Field(None, alias="allowOverride")  # "Allow user to override during data entry"
    other: dict[str, str] = {}  # validation options not recognised by the parser, by element name

    model_config = ConfigDict(populate_by_name=True)


class ModificationInfo(BaseModel):
    """Who last changed an item, and when (from the SaXML ``<UUID>`` stamp)."""

    model_config = ConfigDict(populate_by_name=True)

    user_name: Optional[str] = Field(None, alias="userName")  # OS/host user
    account_name: Optional[str] = Field(None, alias="accountName")  # FileMaker account
    timestamp: Optional[str] = None
    modifications: Optional[int] = None  # change counter


class TableEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("table", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    comment: Optional[str] = None
    fields: list[str] = []           # field docIds
    table_occurrences: list[str] = Field([], alias="tableOccurrences")  # TO docIds
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class FieldEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("field", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    qualified_name: str = Field(alias="qualifiedName")
    base_table_doc_id: str = Field(alias="baseTableDocId")
    data_type: str = Field(alias="dataType")
    field_type: str = Field(alias="fieldType")
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    comment: Optional[str] = None
    calculation: Optional[str] = None
    auto_enter: Optional[AutoEnterOptions] = Field(None, alias="autoEnter")
    validation: Optional[ValidationOptions] = None
    storage: StorageOptions = Field(default_factory=StorageOptions)
    # The field this one summarizes, when this is itself a summary field
    # (e.g. a "Total Of" field) — always a field on this same base table.
    summary_field_doc_id: Optional[str] = Field(None, alias="summaryFieldDocId")
    annotation: Optional[str] = None  # the field's annotation (FileMaker 2025+)
    summary_operation: Optional[str] = Field(None, alias="summaryOperation")  # Total, Count, List, ...
    summary_restart_each_group: Optional[bool] = Field(None, alias="summaryRestartEachGroup")
    summary_repetitions: Optional[str] = Field(None, alias="summaryRepetitions")  # Together | Individually
    # Calculation fields: True = "Do not evaluate if all referenced fields are empty" is unchecked
    always_evaluate: Optional[bool] = Field(None, alias="alwaysEvaluate")
    calculations: list[EntityCalculation] = []  # formula, auto-enter, validation, storage location
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class GraphRect(BaseModel):
    """A rectangle on the relationship graph (or a layout), in points."""

    top: float
    left: float
    bottom: float
    right: float

    def overlaps(self, other: "GraphRect") -> bool:
        return not (other.left >= self.right or other.right <= self.left
                    or other.top >= self.bottom or other.bottom <= self.top)


class TableOccurrenceEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("tableOccurrence", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    base_table_doc_id: str = Field(alias="baseTableDocId")
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    external_data_source: Optional[str] = Field(None, alias="externalDataSource")  # set for type="External" TOs
    external_data_source_id: Optional[str] = Field(None, alias="externalDataSourceId")
    external_data_source_uuid: Optional[str] = Field(None, alias="externalDataSourceUuid")
    # Base table as named in the other file (never a local table)
    external_base_table: Optional[str] = Field(None, alias="externalBaseTable")
    external_base_table_id: Optional[str] = Field(None, alias="externalBaseTableId")
    external_base_table_uuid: Optional[str] = Field(None, alias="externalBaseTableUuid")
    # Scoped docId of that base table (the target of this TO's external basedOnBaseTable reference)
    external_base_table_doc_id: Optional[str] = Field(None, alias="externalBaseTableDocId")
    relationships: list[str] = []    # relationship docIds
    graph_bounds: Optional[GraphRect] = Field(None, alias="graphBounds")  # where it sits on the relationship graph
    collapsed: Optional[bool] = None  # shown collapsed on the graph
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class RelationshipPredicate(BaseModel):
    left_field_doc_id: str = Field(alias="leftFieldDocId")
    operator: str = "="
    right_field_doc_id: str = Field(alias="rightFieldDocId")
    # Set when that side of the predicate is a field in another file
    left_external: Optional["ExternalTarget"] = Field(None, alias="leftExternal")
    right_external: Optional["ExternalTarget"] = Field(None, alias="rightExternal")

    model_config = ConfigDict(populate_by_name=True)


class SortField(BaseModel):
    """One sort level: a field and its order. A custom order names the value list giving it."""

    field_doc_id: Optional[str] = Field(None, alias="fieldDocId")  # None: FileMaker reports the field missing
    order: str = "Ascending"  # Ascending | Descending | Custom
    value_list_doc_id: Optional[str] = Field(None, alias="valueListDocId")
    external: Optional[ExternalTarget] = None  # the field lives in another file

    model_config = ConfigDict(populate_by_name=True)


class RelationshipSide(BaseModel):
    """Options about the records of one side's table occurrence."""

    allow_create: bool = Field(False, alias="allowCreate")  # create records here via this relationship
    delete: bool = Field(False, alias="delete")  # delete records here when the other side's record is deleted
    sort: list[SortField] = []

    model_config = ConfigDict(populate_by_name=True)


class RelationshipOptions(BaseModel):
    # True when either side has the option; see ``left`` / ``right`` for which one.
    allow_create_related: bool = Field(False, alias="allowCreateRelated")
    delete_related: bool = Field(False, alias="deleteRelated")
    sort_related: bool = Field(False, alias="sortRelated")
    left: Optional[RelationshipSide] = None
    right: Optional[RelationshipSide] = None

    model_config = ConfigDict(populate_by_name=True)


class RelationshipEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("relationship", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    left_table_occurrence_doc_id: str = Field(alias="leftTableOccurrenceDocId")
    right_table_occurrence_doc_id: str = Field(alias="rightTableOccurrenceDocId")
    predicates: list[RelationshipPredicate] = []
    options: RelationshipOptions = Field(default_factory=RelationshipOptions)
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class LayoutPart(BaseModel):
    """A layout part (Header, Body, Sub-summary, ...), top to bottom."""

    type: str
    name: Optional[str] = None  # e.g. "Sub-summary by idEntite (Leading)"
    height: Optional[int] = None  # points
    break_field_doc_id: Optional[str] = Field(None, alias="breakFieldDocId")  # sub-summary "when sorted by"
    object_count: int = Field(0, alias="objectCount")  # objects placed directly in the part

    model_config = ConfigDict(populate_by_name=True)


class LayoutEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("layout", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    base_table_occurrence_doc_id: Optional[str] = Field(None, alias="baseTableOccurrenceDocId")
    theme: Optional[str] = None
    folder_path: Optional[str] = Field(None, alias="folderPath")  # layout folder(s), e.g. "DEV/Old"
    referenced_fields: list[str] = Field([], alias="referencedFields")
    layout_objects: list[str] = Field([], alias="layoutObjects")  # LayoutObject docIds
    parts: list[LayoutPart] = []
    menu_set: Optional[str] = Field(None, alias="menuSet")  # custom menu set used on this layout
    script_triggers: list[ScriptTriggerInfo] = Field([], alias="scriptTriggers")
    calculations: list[EntityCalculation] = []  # script trigger parameters
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class LayoutObjectBounds(BaseModel):
    """Pixel bounds of a layout object on the layout."""

    top: Optional[float] = None
    left: Optional[float] = None
    bottom: Optional[float] = None
    right: Optional[float] = None

    model_config = ConfigDict(populate_by_name=True)


class PortalOptions(BaseModel):
    """A portal's setup: which rows it shows and in what order (its filter is in the object's calculations)."""

    initial_row: Optional[int] = Field(None, alias="initialRow")
    rows: Optional[int] = None  # number of rows shown
    allow_deletion: Optional[bool] = Field(None, alias="allowDeletion")  # "Allow deletion of portal records"
    sort: list[SortField] = []

    model_config = ConfigDict(populate_by_name=True)


class LayoutObjectEntity(BaseModel):
    """A single object placed on a layout — a field, button, text block, portal, etc.

    Layout objects are nested inside ``<Part><ObjectList>`` in the SaveAsXML
    format. They carry the field placements that the layout displays, along
    with text, buttons, and other on-layout content.
    """

    doc_id: str = Field(alias="docId")
    entity_type: str = Field("layoutObject", alias="entityType")
    layout_doc_id: str = Field(alias="layoutDocId")
    part: Optional[str] = None  # e.g. "Body", "Header", "Top Navigation"
    object_id: str = Field("", alias="objectId")  # FM's id="..." within the layout
    object_type: str = Field("", alias="objectType")  # "Edit Box", "Text", "Button", "Portal", etc.
    kind: Optional[str] = None  # FM's kind="..." numeric flag (kept as string)
    name: str = ""  # Object name (often blank for plain text/edit boxes)
    uuid: Optional[str] = None
    bounds: Optional[LayoutObjectBounds] = None
    field_doc_id: Optional[str] = Field(None, alias="fieldDocId")
    table_occurrence_doc_id: Optional[str] = Field(None, alias="tableOccurrenceDocId")
    value_list_doc_id: Optional[str] = Field(None, alias="valueListDocId")  # value list on the control
    external_target: Optional["ExternalTarget"] = Field(None, alias="externalTarget")  # field lives in another file
    button_script_doc_id: Optional[str] = Field(None, alias="buttonScriptDocId")  # script this button performs
    button_script_external: Optional["ExternalTarget"] = Field(None, alias="buttonScriptExternal")
    button_kind: Optional[str] = Field(None, alias="buttonKind")  # button | buttonGroup | popoverButton
    button_step: Optional[str] = Field(None, alias="buttonStep")  # single-step button's step, e.g. "Go to Layout [ X ]"
    # Container object (portal, tab/slide panel, button bar, popover) this one sits in
    parent_object_doc_id: Optional[str] = Field(None, alias="parentObjectDocId")
    portal: Optional[PortalOptions] = None
    script_triggers: list[ScriptTriggerInfo] = Field([], alias="scriptTriggers")
    calculations: list[EntityCalculation] = []  # hide condition, conditional formatting, tooltip, ...
    # Direct targets of the button step and a portal's sort fields; same shape as ScriptStepEntity.references
    references: list[dict[str, Any]] = []
    raw_text: Optional[str] = Field(None, alias="rawText")  # Plain-text label (Text objects)
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class StepCalculation(BaseModel):
    """One calculated parameter of a script step, e.g. Set Variable's value or repetition."""
    position: Optional[int] = None    # FileMaker's ordinal for the calc within the step
    parameter: Optional[str] = None   # <Parameter type>: Variable, Calculation, Message, WindowReference...
    slot: Optional[str] = None        # element holding the calc in that parameter: value, repetition, top...
    text: str


class ScriptStepEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("scriptStep", alias="entityType")
    script_doc_id: str = Field(alias="scriptDocId")
    index: int
    step_id: str = Field(alias="stepId")   # FileMaker's built-in step type ID
    name: str
    enabled: bool = True
    raw_text: Optional[str] = Field(None, alias="rawText")  # short preview; see model/step_text.py for the full text
    parameters: dict[str, Any] = {}
    # What the Script Workspace shows between the brackets, in order: comment text, targets,
    # references, options, and calcs (by index into ``calculations``). See parser/extractors/scripts.py.
    params: list[dict[str, Any]] = []
    # The step exactly as FileMaker prints it (DDR_INFO StepText), when the export carries it
    fm_text: Optional[str] = Field(None, alias="fmText")
    calculations: list[StepCalculation] = []
    references: list[dict[str, Any]] = []  # values are strings, except "external" (an ExternalTarget)

    model_config = ConfigDict(populate_by_name=True)


class ScriptEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("script", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    folder_path: Optional[str] = Field(None, alias="folderPath")
    run_with_full_access: Optional[bool] = Field(None, alias="runWithFullAccess")
    show_in_menu: Optional[bool] = Field(None, alias="showInMenu")  # "Include in menu" (Scripts menu)
    siri_shortcut: Optional[bool] = Field(None, alias="siriShortcut")
    steps: list[str] = []            # scriptStep docIds
    referenced_fields: list[str] = Field([], alias="referencedFields")
    referenced_layouts: list[str] = Field([], alias="referencedLayouts")
    referenced_scripts: list[str] = Field([], alias="referencedScripts")
    variables: list[str] = []        # variable docIds set or read by the script's steps
    warnings: list[str] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class VariableUse(BaseModel):
    """One place a variable is assigned or read."""

    source_doc_id: str = Field(alias="sourceDocId")      # a script step, field, layout object, ...
    script_doc_id: Optional[str] = Field(None, alias="scriptDocId")
    step: Optional[int] = None    # 1-based step number, for script steps
    access: str                   # set | read
    via: str                      # step name ("Set Variable", "Insert from URL"), "Let", or a calc role

    model_config = ConfigDict(populate_by_name=True)


class VariableEntity(BaseModel):
    """A ``$$global`` (file-wide) or a ``$local`` (one script) variable.

    FileMaker variable names are case-insensitive; ``name`` keeps the first spelling seen.
    """

    doc_id: str = Field(alias="docId")
    entity_type: str = Field("variable", alias="entityType")
    name: str
    scope: str                    # global | local
    script_doc_id: Optional[str] = Field(None, alias="scriptDocId")  # locals only
    uses: list[VariableUse] = []

    model_config = ConfigDict(populate_by_name=True)

    @property
    def sets(self) -> list[VariableUse]:
        return [u for u in self.uses if u.access == "set"]

    @property
    def reads(self) -> list[VariableUse]:
        return [u for u in self.uses if u.access == "read"]


class CustomFunctionEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customFunction", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    parameters: list[str] = []
    calculation: Optional[str] = None
    calculations: list[EntityCalculation] = []
    references: list[str] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ValueListEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("valueList", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    list_type: str = Field("customValues", alias="listType")  # customValues, field, related, external
    values: list[str] = []  # custom values exactly as typed; "" is a blank separator line
    source_field_doc_id: Optional[str] = Field(None, alias="sourceFieldDocId")
    second_field_doc_id: Optional[str] = Field(None, alias="secondFieldDocId")
    source_field_external: Optional[ExternalTarget] = Field(None, alias="sourceFieldExternal")
    second_field_external: Optional[ExternalTarget] = Field(None, alias="secondFieldExternal")
    # Table occurrences the values are read through (the field link goes to the base table's field)
    source_field_to_doc_id: Optional[str] = Field(None, alias="sourceFieldToDocId")
    second_field_to_doc_id: Optional[str] = Field(None, alias="secondFieldToDocId")
    show_first_field: Optional[bool] = Field(None, alias="showFirstField")  # False = "Show values only from second field"
    sort_by: Optional[str] = Field(None, alias="sortBy")  # "first" | "second" field
    related_from_to_doc_id: Optional[str] = Field(None, alias="relatedFromToDocId")  # "Include only related values starting from"
    external_value_list: Optional[ExternalTarget] = Field(None, alias="externalValueList")  # "Use value list from another file"
    external_data_source: Optional[str] = Field(None, alias="externalDataSource")  # that file, even if the list is gone
    # Parts FileMaker reports as missing (a deleted field or list): "source field", "second field", "external list"
    missing: list[str] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class PrivilegeItem(BaseModel):
    """One row of a custom privilege list: a table, layout, value list or script and its access."""

    kind: str  # Table | Layout | ValueList | Script (FileMaker's element name)
    target_doc_id: Optional[str] = Field(None, alias="targetDocId")  # None for the "[New ...]" row
    label: str = ""
    access: dict[str, str] = {}  # column -> value, e.g. {"View": "ReadWrite", "Delete": "NoAccess"}
    calculations: list[EntityCalculation] = []  # "limited" access calcs; role = the column
    attributes: dict[str, str] = {}

    model_config = ConfigDict(populate_by_name=True)


class PrivilegeCategory(BaseModel):
    """Records, Layouts, Value Lists or Scripts: a blanket setting, or a custom per-object list."""

    summary: str = ""  # e.g. "Create, edit and delete in all", "View only", "No access", "Custom"
    settings: dict[str, str] = {}  # the raw attributes
    custom: Optional[list[PrivilegeItem]] = None

    model_config = ConfigDict(populate_by_name=True)


class PrivilegeSetEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("privilegeSet", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    description: Optional[str] = None
    built_in: bool = Field(False, alias="builtIn")  # [Full Access], [Data Entry Only], [Read-Only Access]
    records: Optional[PrivilegeCategory] = None
    layouts: Optional[PrivilegeCategory] = None
    value_lists: Optional[PrivilegeCategory] = Field(None, alias="valueLists")
    scripts: Optional[PrivilegeCategory] = None
    # Other privileges, as FileMaker names them: Print, Export, manageDatabase, manageAccounts,
    # allowOverride (of data validation warnings), disconnectIdle, commands (menu commands: All |
    # Editing | Minimal), passwordChangeProhibited, ...
    other: dict[str, str] = {}
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class AccountEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("account", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    account_type: str = Field("FileMaker", alias="accountType")
    enabled: bool = True
    description: Optional[str] = None
    privilege_set_doc_id: Optional[str] = Field(None, alias="privilegeSetDocId")
    privilege_set_name: Optional[str] = Field(None, alias="privilegeSetName")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ExtendedPrivilegeEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("extPriv", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    description: Optional[str] = None
    privilege_set_doc_ids: list[str] = Field([], alias="privilegeSetDocIds")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuItem(BaseModel):
    """Embedded within CustomMenuEntity — not a standalone entity."""

    name: str
    action_type: str = Field("", alias="actionType")  # separator | submenu | command | script | action
    install_condition: Optional[str] = Field(None, alias="installCondition")
    script_doc_id: Optional[str] = Field(None, alias="scriptDocId")  # script the item performs
    script_external: Optional[ExternalTarget] = Field(None, alias="scriptExternal")  # ...if it lives in another file
    submenu_doc_id: Optional[str] = Field(None, alias="submenuDocId")  # custom menu this item opens

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customMenu", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    base_menu_name: Optional[str] = Field(None, alias="baseMenuName")
    install_condition: Optional[str] = Field(None, alias="installCondition")
    browse_mode: bool = Field(True, alias="browseMode")
    find_mode: bool = Field(True, alias="findMode")
    preview_mode: bool = Field(True, alias="previewMode")
    items: list[CustomMenuItem] = []
    calculations: list[EntityCalculation] = []  # menu / item install conditions, item actions
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuSetEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customMenuSet", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    menu_doc_ids: list[str] = Field([], alias="menuDocIds")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ThemeEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("theme", alias="entityType")
    modified: Optional[ModificationInfo] = None
    name: str
    fmp_id: str = Field(alias="fmpId")
    display_name: str = Field("", alias="displayName")
    group: Optional[str] = None
    default_theme: bool = Field(False, alias="defaultTheme")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class FileReferenceEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("fileRef", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    ref_type: str = Field("Local", alias="refType")
    is_self: bool = Field(False, alias="isSelf")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)
