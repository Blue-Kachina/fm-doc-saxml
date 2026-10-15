"""Top-level DocumentModel — the canonical normalized representation of a FileMaker solution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, PrivateAttr

from .entities import (
    TableEntity,
    FieldEntity,
    TableOccurrenceEntity,
    RelationshipEntity,
    LayoutEntity,
    LayoutObjectEntity,
    ScriptStepEntity,
    ScriptEntity,
    CustomFunctionEntity,
    ValueListEntity,
    PrivilegeSetEntity,
    AccountEntity,
    ExtendedPrivilegeEntity,
    CustomMenuEntity,
    CustomMenuSetEntity,
    ThemeEntity,
    FileReferenceEntity,
    VariableEntity,
    ScriptTriggerInfo,
    GraphRect,
)
from .indirection import IndirectionSite
from .references import ReferenceRecord


SCHEMA_VERSION = "0.5.0"  # 0.3.0: script step params, variables. 0.4.0: file options, per-side relationship
#   options, value list sources, privilege set access, field and script options (all additive)
#   0.5.0: indirectionSites, reference via / siteDocId, step calc mode (additive)


class SourceInfo(BaseModel):
    type: str = "FileMakerSaveAsXML"
    file_name: str = Field(alias="fileName")
    file_maker_version: str = Field("unknown", alias="fileMakerVersion")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="generatedAt")
    # Modification time (mtime) of the source XML file, captured at parse time.
    # Disambiguated in rendered docs as "XML Created At" vs the model's
    # generated_at timestamp ("Support Documentation Created At").
    source_modified_at: Optional[datetime] = Field(None, alias="sourceModifiedAt")
    # Identity of the FileMaker file this export describes. A later multi-file
    # run uses these to pair an export with the data sources that name it.
    fmp_file_name: Optional[str] = Field(None, alias="fmpFileName")  # e.g. "idiClients.fmp12"
    file_uuid: Optional[str] = Field(None, alias="fileUuid")
    # Prefix that makes this file's docIds globally unique: "<scope>/<docId>".
    # The file UUID when known, else "file:<fmp file name>". See normalize/ids.py.
    scope: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class ExternalDataSource(BaseModel):
    """An entry of the file's External Data Sources catalog (other files it reaches into)."""

    name: str
    fmp_id: Optional[str] = Field(None, alias="fmpId")
    uuid: Optional[str] = None
    type: str = "FileMaker"
    paths: list[str] = []  # e.g. ["file:idiClients"]

    model_config = ConfigDict(populate_by_name=True)


class SolutionInfo(BaseModel):
    name: str = "Unknown Solution"
    files: list[str] = []

    model_config = ConfigDict(populate_by_name=True)


class EntityMaps(BaseModel):
    tables: dict[str, TableEntity] = {}
    fields: dict[str, FieldEntity] = {}
    table_occurrences: dict[str, TableOccurrenceEntity] = Field({}, alias="tableOccurrences")
    relationships: dict[str, RelationshipEntity] = {}
    layouts: dict[str, LayoutEntity] = {}
    layout_objects: dict[str, LayoutObjectEntity] = Field({}, alias="layoutObjects")
    scripts: dict[str, ScriptEntity] = {}
    script_steps: dict[str, ScriptStepEntity] = Field({}, alias="scriptSteps")
    custom_functions: dict[str, CustomFunctionEntity] = Field({}, alias="customFunctions")
    value_lists: dict[str, ValueListEntity] = Field({}, alias="valueLists")
    privilege_sets: dict[str, PrivilegeSetEntity] = Field({}, alias="privilegeSets")
    accounts: dict[str, AccountEntity] = {}
    extended_privileges: dict[str, ExtendedPrivilegeEntity] = Field({}, alias="extendedPrivileges")
    custom_menus: dict[str, CustomMenuEntity] = Field({}, alias="customMenus")
    custom_menu_sets: dict[str, CustomMenuSetEntity] = Field({}, alias="customMenuSets")
    themes: dict[str, ThemeEntity] = {}
    file_references: dict[str, FileReferenceEntity] = Field({}, alias="fileReferences")
    variables: dict[str, VariableEntity] = {}

    model_config = ConfigDict(populate_by_name=True)


FILE_OPTIONS_DOC_ID = "fileOptions"  # source of the file's own script-trigger references


class FileOptions(BaseModel):
    """File > File Options: what runs and opens when the file does."""

    default_layout: Optional[str] = Field(None, alias="defaultLayout")  # layout docId
    minimum_version: Optional[str] = Field(None, alias="minimumVersion")  # minimum FileMaker version allowed
    login_type: Optional[str] = Field(None, alias="loginType")  # FileMaker's raw value; "-1" = not set
    login_account: Optional[str] = Field(None, alias="loginAccount")  # "Log in using" account (never its password)
    encrypted: Optional[bool] = None
    allow_save_password: Optional[bool] = Field(None, alias="allowSavePassword")
    require_mobile_password: Optional[bool] = Field(None, alias="requireMobilePassword")
    show_sign_in_fields: Optional[bool] = Field(None, alias="showSignInFields")
    hide_from_client_sharing: Optional[bool] = Field(None, alias="hideFromClientSharing")
    hide_from_webdirect_sharing: Optional[bool] = Field(None, alias="hideFromWebDirectSharing")
    use_default_fields: Optional[bool] = Field(None, alias="useDefaultFields")  # new tables get the default fields
    default_menu_set: Optional[str] = Field(None, alias="defaultMenuSet")  # Manage Custom Menus: default for this file
    script_triggers: list[ScriptTriggerInfo] = Field([], alias="scriptTriggers")  # OnFirstWindowOpen, ...

    model_config = ConfigDict(populate_by_name=True)


class GraphNote(BaseModel):
    """A text note on the relationship graph, and the table occurrences it lies over."""

    text: str = ""
    bounds: Optional[GraphRect] = None
    table_occurrence_doc_ids: list[str] = Field([], alias="tableOccurrenceDocIds")
    # By position only: TOs below the note, within its width, down to the next such note.
    # Notes are usually headings over a group of TOs; this is that group, as laid out.
    below_doc_ids: list[str] = Field([], alias="belowDocIds")

    model_config = ConfigDict(populate_by_name=True)


class XmlInventory(BaseModel):
    """What the export contains, counted from the XML for the coverage report (parser/coverage.py)."""

    measures: dict[str, int] = {}
    unrecognised: dict[str, dict[str, int]] = {}  # context -> element / @attribute name -> count
    skipped: dict[str, dict[str, int]] = {}  # left out on purpose

    model_config = ConfigDict(populate_by_name=True)


class Warning(BaseModel):
    code: str
    message: str
    entity_doc_id: Optional[str] = Field(None, alias="entityDocId")
    detail: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class ScrubFinding(BaseModel):
    """One redacted occurrence, or one flagged for review. Holds the placeholder, never the value."""

    category: str
    detector: str
    location: str = ""
    placeholder: str = ""
    preview: str = ""
    action: str = "redacted"  # "redacted" | "flagged" (left as-is, needs a human look) | "allowed" (fm-saxml:allow)
    note: str = ""


class ScrubSummary(BaseModel):
    """What scrubbing did to this model. ``applied=False`` means the output is unredacted."""

    applied: bool = False
    level: Optional[str] = None
    engine_version: Optional[str] = Field(None, alias="engineVersion")
    # "numbered" (#1, #2: comparable within one run) or "fingerprint" (keyed hash:
    # comparable across runs that share a salt, identified by salt_id).
    placeholder_style: str = Field("numbered", alias="placeholderStyle")
    salt_id: Optional[str] = Field(None, alias="saltId")
    counts: dict[str, int] = {}  # distinct values per category
    findings: list[ScrubFinding] = []

    model_config = ConfigDict(populate_by_name=True)

    @property
    def redactions(self) -> list[ScrubFinding]:
        return [f for f in self.findings if f.action == "redacted"]

    @property
    def flagged(self) -> list[ScrubFinding]:
        return [f for f in self.findings if f.action == "flagged"]

    @property
    def allowed(self) -> list[ScrubFinding]:
        return [f for f in self.findings if f.action == "allowed"]

    @property
    def distinct_values(self) -> int:
        return len({f.placeholder for f in self.redactions})


class DocumentModel(BaseModel):
    schema_version: str = Field(SCHEMA_VERSION, alias="schemaVersion")
    source: SourceInfo
    solution: SolutionInfo = Field(default_factory=SolutionInfo)
    entities: EntityMaps = Field(default_factory=EntityMaps)
    external_data_sources: list[ExternalDataSource] = Field([], alias="externalDataSources")
    file_options: Optional[FileOptions] = Field(None, alias="fileOptions")
    graph_notes: list[GraphNote] = Field([], alias="graphNotes")
    coverage_inventory: Optional[XmlInventory] = Field(None, alias="coverageInventory")
    references: list[ReferenceRecord] = []
    # Places that name an entity in a string (GetField, Perform Script by name, ...)
    indirection: list[IndirectionSite] = Field([], alias="indirectionSites")
    backlinks: dict[str, list[dict]] = {}
    warnings: list[Warning] = []
    scrubbing: Optional[ScrubSummary] = None

    model_config = ConfigDict(populate_by_name=True)

    # FileMaker script id -> docId, built from the export before anything links to a script.
    # FileMaker allows two scripts with one name; the later ones get a docId with their id.
    _script_doc_ids: dict[str, str] = PrivateAttr(default_factory=dict)
    _layout_doc_ids: dict[str, str] = PrivateAttr(default_factory=dict)  # same, for layouts
    # analyze/coverage.py's report, built once: the index, the reports, the batch summary and the
    # console line all read it, and it walks every entity dozens of times.
    _coverage_report: Optional[object] = PrivateAttr(None)

    def local_layout_doc_id(self, name: str, fmp_id: Optional[str] = None) -> str:
        """docId of a layout in this file: by FileMaker id when known, else by name."""
        from ..normalize.ids import layout_doc_id
        from ..normalize.names import normalize_name
        if fmp_id and str(fmp_id) in self._layout_doc_ids:
            return self._layout_doc_ids[str(fmp_id)]
        return layout_doc_id(normalize_name(name))

    def local_script_doc_id(self, name: str, fmp_id: Optional[str] = None) -> str:
        """docId of a script in this file: by FileMaker id when known, else by name."""
        from ..normalize.ids import script_doc_id
        from ..normalize.names import normalize_name
        if fmp_id and str(fmp_id) in self._script_doc_ids:
            return self._script_doc_ids[str(fmp_id)]
        return script_doc_id(normalize_name(name))

    def get_entity(self, doc_id: str):
        """Return any entity by docId, searching across all entity maps."""
        prefix = doc_id.split(":")[0] if ":" in doc_id else ""
        maps = {
            "table": self.entities.tables,
            "field": self.entities.fields,
            "to": self.entities.table_occurrences,
            "relationship": self.entities.relationships,
            "layout": self.entities.layouts,
            "layoutObject": self.entities.layout_objects,
            "script": self.entities.scripts,
            "scriptStep": self.entities.script_steps,
            "customFunction": self.entities.custom_functions,
            "valueList": self.entities.value_lists,
            "privilegeSet": self.entities.privilege_sets,
            "account": self.entities.accounts,
            "extPriv": self.entities.extended_privileges,
            "customMenu": self.entities.custom_menus,
            "customMenuSet": self.entities.custom_menu_sets,
            "theme": self.entities.themes,
            "fileRef": self.entities.file_references,
            "variable": self.entities.variables,
        }
        entity_map = maps.get(prefix)
        if entity_map is not None:
            return entity_map.get(doc_id)
        for em in maps.values():
            if doc_id in em:
                return em[doc_id]
        return None

    def scoped(self, doc_id: str) -> str:
        """``doc_id`` qualified with this file's scope, safe to merge with other files' ids."""
        return f"{self.source.scope}/{doc_id}" if self.source.scope else doc_id

    def add_warning(self, code: str, message: str, entity_doc_id: Optional[str] = None, detail: Optional[str] = None) -> None:
        self.warnings.append(Warning(code=code, message=message, entity_doc_id=entity_doc_id, detail=detail))
