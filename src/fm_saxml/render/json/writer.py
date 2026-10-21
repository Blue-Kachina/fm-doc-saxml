"""Write the normalized model to JSON files."""

from __future__ import annotations

from pathlib import Path

import orjson

from ...contract import CONTRACT_VERSION, GENERATOR_NAME, ROOT_CATALOG, envelope, format_version
from ... import __version__
from ...model.document_model import DocumentModel, EntityMaps
from ...normalize.ids import data_source_doc_id
from ...utils.file_writer import write_bytes


def write_model_json(model: DocumentModel, out_path: Path) -> None:
    """Serialize the full DocumentModel to a single JSON file."""
    data = model.model_dump(by_alias=True, mode="json")
    write_bytes(out_path, orjson.dumps(data, option=orjson.OPT_INDENT_2))


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
        **envelope(model),
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


def build_entities(model: DocumentModel) -> dict:
    """entities.json: every entity map of the model, keyed by docId, after the contract envelope.

    The collections come from ``EntityMaps``' fields, so a new entity type is written
    without touching this function.
    """
    def dump(value) -> dict:
        return value.model_dump(by_alias=True, mode="json")

    data = envelope(model)
    for name, info in EntityMaps.model_fields.items():
        data[info.alias or name] = {doc_id: dump(e) for doc_id, e in getattr(model.entities, name).items()}
    # Kept as lists on the model; keyed here like every other collection.
    data["externalDataSources"] = {data_source_doc_id(ds.name): dump(ds) for ds in model.external_data_sources}
    data["indirectionSites"] = {site.doc_id: dump(site) for site in model.indirection}
    data["fileOptions"] = dump(model.file_options) if model.file_options else None
    data["graphNotes"] = [dump(note) for note in model.graph_notes]
    return data


def _write(path: Path, data) -> None:
    write_bytes(path, orjson.dumps(data, option=orjson.OPT_INDENT_2))


def write_split_json(model: DocumentModel, output_dir: Path) -> None:
    """Write the contract files (see ``contract.py``) into output_dir."""
    _write(output_dir / "entities.json", build_entities(model))
    _write(output_dir / "references.json", {
        **envelope(model),
        "references": [r.model_dump(by_alias=True, mode="json") for r in model.references],
    })
    _write(output_dir / "backlinks.json", {**envelope(model), "backlinks": model.backlinks})
    write_external_references_json(model, output_dir)


def build_root_catalog(kind: str, solution: str, files: list[tuple[DocumentModel, str, str]],
                       pairings=None, synthesized_manifest: bool = False) -> dict:
    """docs.json: ``files`` is ``[(model, folder, name)]``; ``pairings`` a batch's ``BatchLinks.pairings``.

    ``synthesized_manifest``: the input folder had no Summary.xml, so fm-saxml built one from the exports.
    """
    out = {
        "schemaVersion": format_version(CONTRACT_VERSION),
        "generator": {"name": GENERATOR_NAME, "version": __version__},
        "kind": kind,
        "solution": solution,
        "files": [
            {
                "name": name,
                "folder": folder,
                "fmpFileName": m.source.fmp_file_name,
                "fileUuid": m.source.file_uuid,
                "scope": m.source.scope,
                "fileMakerVersion": m.source.file_maker_version,
                "saxmlVersion": m.source.saxml_version,
                "hasDdrInfo": m.source.has_ddr_info,
            }
            for m, folder, name in files
        ],
        "pairings": [],
        "synthesizedManifest": synthesized_manifest,
    }
    by_folder = {folder: m for m, folder, _ in files}
    for p in pairings or []:
        ds = next((d for d in by_folder[p.source].external_data_sources if d.name == p.data_source), None)
        out["pairings"].append({
            "folder": p.source,
            "dataSource": p.data_source,
            "dataSourceUuid": ds.uuid if ds else None,
            "targetFolder": p.target,
            "match": p.match,
            "reason": p.reason,
        })
    return out


def write_root_catalog(output_dir: Path, catalog: dict) -> None:
    _write(output_dir / ROOT_CATALOG, catalog)
