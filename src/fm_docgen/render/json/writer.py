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
