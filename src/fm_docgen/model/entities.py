"""Pydantic entity models for the normalized FileMaker documentation model."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class SourceXmlInfo(BaseModel):
    """Trace back to the originating XML location for debugging."""

    model_config = ConfigDict(populate_by_name=True)

    path: str
    line: Optional[int] = None


class StorageOptions(BaseModel):
    global_storage: bool = Field(False, alias="global")
    indexed: bool = False
    max_repeat: int = Field(1, alias="maxRepeat")

    model_config = ConfigDict(populate_by_name=True)


class AutoEnterOptions(BaseModel):
    type: str = "none"  # none, serial, data, calculation, lookup, modification
    value: Optional[str] = None
    calculation: Optional[str] = None
    no_modify_auto_enter: bool = False

    model_config = ConfigDict(populate_by_name=True)


class ValidationOptions(BaseModel):
    required: bool = False
    not_empty: bool = False
    unique: bool = False
    max_characters: Optional[int] = None
    message: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class TableEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("table", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    fields: list[str] = []           # field docIds
    table_occurrences: list[str] = Field([], alias="tableOccurrences")  # TO docIds
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class FieldEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("field", alias="entityType")
    name: str
    qualified_name: str = Field(alias="qualifiedName")
    base_table_doc_id: str = Field(alias="baseTableDocId")
    data_type: str = Field(alias="dataType")
    field_type: str = Field(alias="fieldType")
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    calculation: Optional[str] = None
    auto_enter: Optional[AutoEnterOptions] = Field(None, alias="autoEnter")
    validation: Optional[ValidationOptions] = None
    storage: StorageOptions = Field(default_factory=StorageOptions)
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class TableOccurrenceEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("tableOccurrence", alias="entityType")
    name: str
    base_table_doc_id: str = Field(alias="baseTableDocId")
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    relationships: list[str] = []    # relationship docIds
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class RelationshipPredicate(BaseModel):
    left_field_doc_id: str = Field(alias="leftFieldDocId")
    operator: str = "="
    right_field_doc_id: str = Field(alias="rightFieldDocId")

    model_config = ConfigDict(populate_by_name=True)


class RelationshipOptions(BaseModel):
    allow_create_related: bool = Field(False, alias="allowCreateRelated")
    delete_related: bool = Field(False, alias="deleteRelated")
    sort_related: bool = Field(False, alias="sortRelated")

    model_config = ConfigDict(populate_by_name=True)


class RelationshipEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("relationship", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    left_table_occurrence_doc_id: str = Field(alias="leftTableOccurrenceDocId")
    right_table_occurrence_doc_id: str = Field(alias="rightTableOccurrenceDocId")
    predicates: list[RelationshipPredicate] = []
    options: RelationshipOptions = Field(default_factory=RelationshipOptions)
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class LayoutEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("layout", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    base_table_occurrence_doc_id: Optional[str] = Field(None, alias="baseTableOccurrenceDocId")
    theme: Optional[str] = None
    referenced_fields: list[str] = Field([], alias="referencedFields")
    layout_objects: list[str] = Field([], alias="layoutObjects")  # LayoutObject docIds
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class LayoutObjectBounds(BaseModel):
    """Pixel bounds of a layout object on the layout."""

    top: Optional[float] = None
    left: Optional[float] = None
    bottom: Optional[float] = None
    right: Optional[float] = None

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
    raw_text: Optional[str] = Field(None, alias="rawText")  # Plain-text label (Text objects)
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ScriptStepEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("scriptStep", alias="entityType")
    script_doc_id: str = Field(alias="scriptDocId")
    index: int
    step_id: str = Field(alias="stepId")   # FileMaker's built-in step type ID
    name: str
    enabled: bool = True
    raw_text: Optional[str] = Field(None, alias="rawText")
    parameters: dict[str, Any] = {}
    references: list[dict[str, str]] = []

    model_config = ConfigDict(populate_by_name=True)


class ScriptEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("script", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    folder_path: Optional[str] = Field(None, alias="folderPath")
    steps: list[str] = []            # scriptStep docIds
    referenced_fields: list[str] = Field([], alias="referencedFields")
    referenced_layouts: list[str] = Field([], alias="referencedLayouts")
    referenced_scripts: list[str] = Field([], alias="referencedScripts")
    warnings: list[str] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class CustomFunctionEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customFunction", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    parameters: list[str] = []
    calculation: Optional[str] = None
    references: list[str] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ValueListEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("valueList", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    uuid: Optional[str] = None
    list_type: str = Field("customValues", alias="listType")  # customValues, field, related
    values: list[str] = []
    source_field_doc_id: Optional[str] = Field(None, alias="sourceFieldDocId")
    second_field_doc_id: Optional[str] = Field(None, alias="secondFieldDocId")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class PrivilegeSetEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("privilegeSet", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    description: Optional[str] = None
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class AccountEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("account", alias="entityType")
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
    name: str
    fmp_id: str = Field(alias="fmpId")
    description: Optional[str] = None
    privilege_set_doc_ids: list[str] = Field([], alias="privilegeSetDocIds")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuItem(BaseModel):
    """Embedded within CustomMenuEntity — not a standalone entity."""

    name: str
    action_type: str = Field("", alias="actionType")
    install_condition: Optional[str] = Field(None, alias="installCondition")

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customMenu", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    base_menu_name: Optional[str] = Field(None, alias="baseMenuName")
    install_condition: Optional[str] = Field(None, alias="installCondition")
    browse_mode: bool = Field(True, alias="browseMode")
    find_mode: bool = Field(True, alias="findMode")
    preview_mode: bool = Field(True, alias="previewMode")
    items: list[CustomMenuItem] = []
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class CustomMenuSetEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("customMenuSet", alias="entityType")
    name: str
    fmp_id: str = Field(alias="fmpId")
    menu_doc_ids: list[str] = Field([], alias="menuDocIds")
    source_xml: Optional[SourceXmlInfo] = Field(None, alias="sourceXml")

    model_config = ConfigDict(populate_by_name=True)


class ThemeEntity(BaseModel):
    doc_id: str = Field(alias="docId")
    entity_type: str = Field("theme", alias="entityType")
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
