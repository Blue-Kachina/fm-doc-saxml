"""Write the normalized model to JSON files."""

from __future__ import annotations

from pathlib import Path

import orjson

from ...model.document_model import DocumentModel
from ...utils.file_writer import write_bytes


def write_model_json(model: DocumentModel, out_path: Path) -> None:
    """Serialize the full DocumentModel to a single JSON file."""
    data = model.model_dump(by_alias=True, mode="json")
    write_bytes(out_path, orjson.dumps(data, option=orjson.OPT_INDENT_2))


EXTERNAL_REFERENCES_SCHEMA_VERSION = "1.0.0"


def build_external_references(model: DocumentModel) -> dict:
    """Every outgoing reference into another file, plus this file's identity.

    Self-contained on purpose: a later multi-file run can read these
    documents instead of re-parsing each XML export. Resolve a reference
    against the sister file by matching ``target.uuid`` first, then
    ``target.fmpId``, then ``target.name`` (fields: ``target.baseTable`` +
    ``target.name``). ``target.dataSource`` is only a label; use
    ``dataSources`` (paths, UUIDs) to work out which file it names.

    DocIds are file-scoped as ``<scope>/<docId>`` (see ``normalize/ids.py``):
    ``sourceScopedDocId`` uses this file's ``source.scope``; ``target.scopedDocId``
    uses the provisional ``ds:<data source uuid>`` scope, to be swapped for the
    target file's UUID once paired. ``target.targetDocId`` is the unscoped id.
    """
    external = [r for r in model.references if r.confidence == "external"]
    return {
        "schemaVersion": EXTERNAL_REFERENCES_SCHEMA_VERSION,
        "source": {
            "fileName": model.source.file_name,
            "fmpFileName": model.source.fmp_file_name,
            "fileUuid": model.source.file_uuid,
            "scope": model.source.scope,
            "fileMakerVersion": model.source.file_maker_version,
            "generatedAt": model.source.generated_at.isoformat(),
        },
        "dataSources": [ds.model_dump(by_alias=True, mode="json") for ds in model.external_data_sources],
        "externalTableOccurrences": [
            {
                "docId": to.doc_id,
                "name": to.name,
                "fmpId": to.fmp_id,
                "uuid": to.uuid,
                "dataSource": to.external_data_source,
                "dataSourceId": to.external_data_source_id,
                "dataSourceUuid": to.external_data_source_uuid,
                "baseTable": to.external_base_table,
                "baseTableId": to.external_base_table_id,
                "baseTableUuid": to.external_base_table_uuid,
            }
            for to in model.entities.table_occurrences.values()
            if to.external_data_source
        ],
        "references": [
            {
                "sourceDocId": r.source_doc_id,
                "sourceScopedDocId": model.scoped(r.source_doc_id),
                "sourceEntityType": r.source_entity_type,
                "relationshipType": r.relationship_type,
                "role": r.role,
                "rawText": r.raw_text,
                "target": r.external_target.model_dump(by_alias=True, mode="json") if r.external_target else None,
            }
            for r in external
        ],
    }


def write_external_references_json(model: DocumentModel, output_dir: Path) -> None:
    write_bytes(
        output_dir / "external-references.json",
        orjson.dumps(build_external_references(model), option=orjson.OPT_INDENT_2),
    )


def write_split_json(model: DocumentModel, output_dir: Path) -> None:
    """Write entities.json, references.json, and backlinks.json into output_dir."""
    entities_data = {}
    for key, entity_map in {
        "tables": model.entities.tables,
        "fields": model.entities.fields,
        "tableOccurrences": model.entities.table_occurrences,
        "relationships": model.entities.relationships,
        "layouts": model.entities.layouts,
        "layoutObjects": model.entities.layout_objects,
        "scripts": model.entities.scripts,
        "scriptSteps": model.entities.script_steps,
        "customFunctions": model.entities.custom_functions,
        "valueLists": model.entities.value_lists,
        "privilegeSets": model.entities.privilege_sets,
    }.items():
        entities_data[key] = {
            doc_id: entity.model_dump(by_alias=True, mode="json")
            for doc_id, entity in entity_map.items()
        }

    write_bytes(output_dir / "entities.json", orjson.dumps(entities_data, option=orjson.OPT_INDENT_2))
    write_bytes(output_dir / "references.json", orjson.dumps(
        [r.model_dump(by_alias=True, mode="json") for r in model.references],
        option=orjson.OPT_INDENT_2,
    ))
    write_bytes(output_dir / "backlinks.json", orjson.dumps(model.backlinks, option=orjson.OPT_INDENT_2))
    write_external_references_json(model, output_dir)
