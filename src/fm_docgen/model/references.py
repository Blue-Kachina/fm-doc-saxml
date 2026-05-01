"""Reference record model — first-class cross-entity references."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

ReferenceConfidence = Literal["exact", "parsed", "inferred", "unresolved"]

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


class ReferenceRecord(BaseModel):
    source_doc_id: str = Field(alias="sourceDocId")
    source_entity_type: str = Field(alias="sourceEntityType")
    target_doc_id: str = Field(alias="targetDocId")
    target_entity_type: str = Field(alias="targetEntityType")
    relationship_type: str = Field(alias="relationshipType")
    role: Optional[str] = None
    confidence: ReferenceConfidence = "exact"
    raw_text: Optional[str] = Field(None, alias="rawText")

    model_config = ConfigDict(populate_by_name=True)
