"""Pydantic models of the contract files (see ``contract.py``), one per file.

They describe exactly what ``render/json/writer.py`` writes: a test round-trips
every file of a build through them. Readers validate with them, and
``docs/contract/schema-<version>/`` holds the JSON Schema generated from them
(``write_schemas``).

Unknown keys are ignored, so a reader built for 1.0 reads a 1.x file (a minor
version only adds keys). Keys a file lacks take the defaults below.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .contract import CONTRACT_VERSION, format_version
from .model.document_model import EntityMaps, ExternalDataSource, FileOptions, GraphNote
from .model.indirection import IndirectionSite
from .model.references import ExternalTarget, ReferenceRecord


class Generator(BaseModel):
    """What wrote the file. ``None`` on a file upgraded from before the contract existed."""

    name: str
    version: Optional[str] = None


class ContractSource(BaseModel):
    """The FileMaker file the docs describe. Never a path on the machine that built them."""

    fmp_file_name: Optional[str] = Field(None, alias="fmpFileName")
    file_uuid: Optional[str] = Field(None, alias="fileUuid")
    scope: Optional[str] = None  # prefix of this file's scoped docIds: "<scope>/<docId>"
    file_maker_version: Optional[str] = Field(None, alias="fileMakerVersion")
    saxml_version: Optional[str] = Field(None, alias="saxmlVersion")

    model_config = ConfigDict(populate_by_name=True)


class ContractEnvelope(BaseModel):
    """The keys every contract file starts with."""

    schema_version: str = Field(alias="schemaVersion")  # "MAJOR.MINOR"
    generator: Optional[Generator] = None
    source: ContractSource = Field(default_factory=ContractSource)

    model_config = ConfigDict(populate_by_name=True)


class EntitiesDoc(EntityMaps, ContractEnvelope):
    """entities.json: every entity collection ``{docId: entity}``, next to the envelope keys."""

    external_data_sources: dict[str, ExternalDataSource] = Field({}, alias="externalDataSources")
    indirection_sites: dict[str, IndirectionSite] = Field({}, alias="indirectionSites")
    file_options: Optional[FileOptions] = Field(None, alias="fileOptions")
    graph_notes: list[GraphNote] = Field([], alias="graphNotes")

    model_config = ConfigDict(populate_by_name=True)


class ReferencesDoc(ContractEnvelope):
    """references.json: every reference from one entity to another."""

    references: list[ReferenceRecord] = []


class Backlink(BaseModel):
    """One incoming reference, filed under its target's docId."""

    # In a multi-file build, a reference from another file has sourceDocId "xfile:<folder>/<docId>"
    source_doc_id: str = Field(alias="sourceDocId")
    source_entity_type: str = Field(alias="sourceEntityType")
    relationship_type: str = Field(alias="relationshipType")
    role: Optional[str] = None
    confidence: str
    via: Optional[str] = None  # "byName": named in a string (see indirectionSites)
    site_doc_id: Optional[str] = Field(None, alias="siteDocId")

    model_config = ConfigDict(populate_by_name=True)


class BacklinksDoc(ContractEnvelope):
    """backlinks.json: references.json inverted, ``{targetDocId: [backlink, ...]}``."""

    backlinks: dict[str, list[Backlink]] = {}


class ExternalTableOccurrence(BaseModel):
    """A table occurrence of this file whose base table lives in another file."""

    doc_id: str = Field(alias="docId")
    name: str
    fmp_id: Optional[str] = Field(None, alias="fmpId")
    uuid: Optional[str] = None
    data_source: Optional[str] = Field(None, alias="dataSource")
    data_source_id: Optional[str] = Field(None, alias="dataSourceId")
    data_source_uuid: Optional[str] = Field(None, alias="dataSourceUuid")
    base_table: Optional[str] = Field(None, alias="baseTable")
    base_table_id: Optional[str] = Field(None, alias="baseTableId")
    base_table_uuid: Optional[str] = Field(None, alias="baseTableUuid")

    model_config = ConfigDict(populate_by_name=True)


class ExternalReference(BaseModel):
    """A reference from this file into another one, with everything needed to resolve it there."""

    source_doc_id: str = Field(alias="sourceDocId")
    source_scoped_doc_id: str = Field(alias="sourceScopedDocId")
    source_entity_type: str = Field(alias="sourceEntityType")
    relationship_type: str = Field(alias="relationshipType")
    role: Optional[str] = None
    raw_text: Optional[str] = Field(None, alias="rawText")
    target: Optional[ExternalTarget] = None

    model_config = ConfigDict(populate_by_name=True)


class ExternalReferencesDoc(ContractEnvelope):
    """external-references.json: this file's data sources and every reference into another file."""

    data_sources: list[ExternalDataSource] = Field([], alias="dataSources")
    external_table_occurrences: list[ExternalTableOccurrence] = Field([], alias="externalTableOccurrences")
    references: list[ExternalReference] = []

    model_config = ConfigDict(populate_by_name=True)


DOC_MODELS: dict[str, type[ContractEnvelope]] = {
    "entities.json": EntitiesDoc,
    "references.json": ReferencesDoc,
    "backlinks.json": BacklinksDoc,
    "external-references.json": ExternalReferencesDoc,
}

SCHEMA_ROOT = Path("docs") / "contract"  # relative to the repository root


def schema_dir_name() -> str:
    return f"schema-{format_version(CONTRACT_VERSION)}"


def json_schemas() -> dict[str, dict]:
    """JSON Schema of each contract file, keyed by the schema's file name."""
    out = {}
    for file_name, model in DOC_MODELS.items():
        schema = model.model_json_schema(by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"fm-saxml/contract/{schema_dir_name()}/{file_name.removesuffix('.json')}.schema.json"
        out[f"{file_name.removesuffix('.json')}.schema.json"] = schema
    return out


def write_schemas(directory: Path) -> None:
    """Write ``json_schemas()`` into ``directory`` (LF line endings, stable key order)."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, schema in json_schemas().items():
        (directory / name).write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8", newline="\n")
