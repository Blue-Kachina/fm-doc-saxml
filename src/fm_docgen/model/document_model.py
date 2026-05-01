"""Top-level DocumentModel — the canonical normalized representation of a FileMaker solution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from .entities import (
    TableEntity,
    FieldEntity,
    TableOccurrenceEntity,
    RelationshipEntity,
    LayoutEntity,
    ScriptStepEntity,
    ScriptEntity,
    CustomFunctionEntity,
    ValueListEntity,
    PrivilegeSetEntity,
)
from .references import ReferenceRecord


SCHEMA_VERSION = "0.1.0"


class SourceInfo(BaseModel):
    type: str = "FileMakerSaveAsXML"
    file_name: str = Field(alias="fileName")
    file_maker_version: str = Field("unknown", alias="fileMakerVersion")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="generatedAt")

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
    scripts: dict[str, ScriptEntity] = {}
    script_steps: dict[str, ScriptStepEntity] = Field({}, alias="scriptSteps")
    custom_functions: dict[str, CustomFunctionEntity] = Field({}, alias="customFunctions")
    value_lists: dict[str, ValueListEntity] = Field({}, alias="valueLists")
    privilege_sets: dict[str, PrivilegeSetEntity] = Field({}, alias="privilegeSets")

    model_config = ConfigDict(populate_by_name=True)


class Warning(BaseModel):
    code: str
    message: str
    entity_doc_id: Optional[str] = Field(None, alias="entityDocId")
    detail: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class DocumentModel(BaseModel):
    schema_version: str = Field(SCHEMA_VERSION, alias="schemaVersion")
    source: SourceInfo
    solution: SolutionInfo = Field(default_factory=SolutionInfo)
    entities: EntityMaps = Field(default_factory=EntityMaps)
    references: list[ReferenceRecord] = []
    backlinks: dict[str, list[dict]] = {}
    warnings: list[Warning] = []

    model_config = ConfigDict(populate_by_name=True)

    def get_entity(self, doc_id: str):
        """Return any entity by docId, searching across all entity maps."""
        prefix = doc_id.split(":")[0] if ":" in doc_id else ""
        maps = {
            "table": self.entities.tables,
            "field": self.entities.fields,
            "to": self.entities.table_occurrences,
            "relationship": self.entities.relationships,
            "layout": self.entities.layouts,
            "script": self.entities.scripts,
            "scriptStep": self.entities.script_steps,
            "customFunction": self.entities.custom_functions,
            "valueList": self.entities.value_lists,
            "privilegeSet": self.entities.privilege_sets,
        }
        entity_map = maps.get(prefix)
        if entity_map is not None:
            return entity_map.get(doc_id)
        for em in maps.values():
            if doc_id in em:
                return em[doc_id]
        return None

    def add_warning(self, code: str, message: str, entity_doc_id: Optional[str] = None, detail: Optional[str] = None) -> None:
        self.warnings.append(Warning(code=code, message=message, entity_doc_id=entity_doc_id, detail=detail))
