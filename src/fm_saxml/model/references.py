"""Reference record model — first-class cross-entity references."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

# "external": confidently points at another file of a multi-file solution (not resolvable here)
ReferenceConfidence = Literal["exact", "parsed", "inferred", "unresolved", "external"]

RelationshipType = Literal[
    "contains",
    "usesField",
    "usesLayout",
    "usesScript",
    "usesCustomFunction",
    "usesValueList",
    "basedOnTableOccurrence",
    "basedOnBaseTable",
    "joinsTo",
    "readsFrom",
    "writesTo",
    "deletesFrom",
    "opensWindowOn",
    "navigatesTo",
]


class ExternalTarget(BaseModel):
    """Everything known about a reference that points into another file.

    Captured so a later multi-file run can resolve it against the sister
    file's export: match ``uuid`` first, then ``fmp_id``, then ``name``
    (for fields: ``base_table`` + ``name``). ``data_source`` is the *name of
    the external data source* in this file, which is a label, not necessarily
    the target file's name — see ``DocumentModel.external_data_sources``.
    """

    data_source: str = Field(alias="dataSource")
    data_source_id: Optional[str] = Field(None, alias="dataSourceId")
    data_source_uuid: Optional[str] = Field(None, alias="dataSourceUuid")
    target_type: str = Field(alias="targetType")  # field | script | layout
    name: str = ""
    fmp_id: Optional[str] = Field(None, alias="fmpId")
    uuid: Optional[str] = None
    # Table occurrence (in THIS file) the target was reached through, if any
    table_occurrence: Optional[str] = Field(None, alias="tableOccurrence")
    # That external TO's base table, as named in the target file
    base_table: Optional[str] = Field(None, alias="baseTable")
    base_table_id: Optional[str] = Field(None, alias="baseTableId")
    base_table_uuid: Optional[str] = Field(None, alias="baseTableUuid")

    model_config = ConfigDict(populate_by_name=True)


class ReferenceRecord(BaseModel):
    source_doc_id: str = Field(alias="sourceDocId")
    source_entity_type: str = Field(alias="sourceEntityType")
    target_doc_id: str = Field(alias="targetDocId")
    target_entity_type: str = Field(alias="targetEntityType")
    relationship_type: str = Field(alias="relationshipType")
    role: Optional[str] = None
    confidence: ReferenceConfidence = "exact"
    raw_text: Optional[str] = Field(None, alias="rawText")
    external_target: Optional[ExternalTarget] = Field(None, alias="externalTarget")  # set when confidence == "external"

    model_config = ConfigDict(populate_by_name=True)
