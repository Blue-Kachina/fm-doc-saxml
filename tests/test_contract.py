"""The published JSON contract (contract.py): envelope, versions, complete entities.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.cli import _run_pipeline, app
from fm_saxml.contract import CONTRACT_FILES, CONTRACT_VERSION, ENVELOPE_KEYS, format_version, parse_version
from fm_saxml.model.document_model import EntityMaps
from fm_saxml.normalize.ids import split_scoped_doc_id
from fm_saxml.normalize.normalize import normalize
from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.render.json.writer import write_model_json, write_split_json

BAGEL = Path(__file__).resolve().parent.parent / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
runner = CliRunner()


@pytest.fixture(scope="module")
def bagel_model():
    if not BAGEL.exists():
        pytest.skip("samples/by_type fixture not present")
    return _run_pipeline(BAGEL)


@pytest.fixture(scope="module")
def bagel_docs(bagel_model, tmp_path_factory):
    out = tmp_path_factory.mktemp("bagel_docs")
    write_split_json(bagel_model, out)
    return {name: json.loads((out / name).read_text(encoding="utf-8")) for name in CONTRACT_FILES}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

def test_parse_version_compares_numbers_not_strings():
    assert parse_version("1.0") == (1, 0)
    assert parse_version("0.5.0") == (0, 5, 0)
    assert parse_version("0.10.0") > parse_version("0.5.0")  # "0.10.0" < "0.5.0" as strings
    assert parse_version("0.5.0") >= (0, 5)
    assert parse_version("0.4.9") < (0, 5)
    assert format_version((1, 0)) == "1.0"


@pytest.mark.parametrize("bad", ["", "1.x", "v1.0", "1..0", None])
def test_parse_version_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def test_every_contract_file_has_the_same_envelope(bagel_docs):
    envelopes = []
    for name, doc in bagel_docs.items():
        assert isinstance(doc, dict), name
        assert list(doc)[:3] == list(ENVELOPE_KEYS), name
        envelopes.append({k: doc[k] for k in ENVELOPE_KEYS})
    assert all(e == envelopes[0] for e in envelopes)
    env = envelopes[0]
    assert env["schemaVersion"] == format_version(CONTRACT_VERSION)
    assert env["generator"]["name"] == "fm-saxml-converter"
    assert env["source"] == {
        "fmpFileName": "EverythingBagel.fmp12",
        "fileUuid": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
        "scope": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
        "fileMakerVersion": "26.0.3",
        "saxmlVersion": "2.3.0.0",
        "hasDdrInfo": True,
    }


def test_payloads_sit_under_named_keys(bagel_docs, bagel_model):
    refs = bagel_docs["references.json"]["references"]
    assert isinstance(refs, list) and len(refs) == len(bagel_model.references)
    assert isinstance(bagel_docs["backlinks.json"]["backlinks"], dict)
    ext = bagel_docs["external-references.json"]
    assert {"dataSources", "externalTableOccurrences", "references"} <= set(ext)


def test_no_absolute_input_path_in_contract_files(bagel_docs):
    for name, doc in bagel_docs.items():
        text = json.dumps(doc)
        assert str(BAGEL.parent) not in text and "fileName" not in doc["source"], name
    assert "fileName" not in json.dumps(bagel_docs["external-references.json"]["source"])


def test_contract_files_are_byte_reproducible(bagel_model, tmp_path):
    write_split_json(bagel_model, tmp_path / "a")
    write_split_json(_run_pipeline(BAGEL), tmp_path / "b")  # a fresh run: new generatedAt in the model
    for name in CONTRACT_FILES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


# ---------------------------------------------------------------------------
# entities.json is complete
# ---------------------------------------------------------------------------

def test_entities_json_holds_every_entity_map(bagel_docs):
    ents = bagel_docs["entities.json"]
    for name, info in EntityMaps.model_fields.items():
        assert (info.alias or name) in ents, info.alias or name
    for key in ("externalDataSources", "indirectionSites", "fileOptions", "graphNotes"):
        assert key in ents
    assert not set(ENVELOPE_KEYS) & {info.alias or n for n, info in EntityMaps.model_fields.items()}


def test_entities_json_has_the_previously_missing_collections(bagel_docs):
    ents = bagel_docs["entities.json"]
    assert "customMenuSet:Custom Menu Set" in ents["customMenuSets"]
    assert len(ents["customMenus"]) >= 25
    assert {t["displayName"] for t in ents["themes"].values()} >= {"Vibrant Custom", "Apex Blue Copy"}
    assert set(ents["accounts"]) == {"account:Admin", "account:[Guest]"}
    assert set(ents["externalDataSources"]) == {"dataSource:Empty", "dataSource:odbc_test"}
    assert ents["externalDataSources"]["dataSource:Empty"]["paths"] == ["file:Empty", "fmnet:/127.0.0.1/Empty"]
    assert ents["fileOptions"] is not None
    assert all(k == v["docId"] for k, v in ents["indirectionSites"].items())


def test_every_reference_target_is_in_entities_or_external_or_unresolved(bagel_docs):
    ents = bagel_docs["entities.json"]
    known = {doc_id for key, coll in ents.items() if isinstance(coll, dict) and key not in ENVELOPE_KEYS
             for doc_id in coll}
    dangling = []
    for r in bagel_docs["references.json"]["references"]:
        target = r.get("targetDocId")
        if not target or target in known or r["confidence"] == "unresolved":
            continue
        if split_scoped_doc_id(target)[0] is not None:  # another file: <scope>/<docId>
            continue
        dangling.append((r["sourceDocId"], r["relationshipType"], target))
    assert not dangling, dangling[:10]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_render_writes_the_contract_files_too(bagel_model, tmp_path):
    model_json = tmp_path / "model.json"
    write_model_json(bagel_model, model_json)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["render", "markdown", "-m", str(model_json), "-o", str(out), "-y",
                                 "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    for name in CONTRACT_FILES:
        assert json.loads((out / name).read_text(encoding="utf-8"))["schemaVersion"] == format_version(CONTRACT_VERSION)


def test_render_no_include_json_skips_them(bagel_model, tmp_path):
    model_json = tmp_path / "model.json"
    write_model_json(bagel_model, model_json)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["render", "markdown", "-m", str(model_json), "-o", str(out), "-y",
                                 "--disable-scrubbing", "--no-include-json"])
    assert result.exit_code == 0, result.output
    assert not (out / "entities.json").exists()


# ---------------------------------------------------------------------------
# Duplicate names no longer vanish silently
# ---------------------------------------------------------------------------

def test_duplicate_names_are_reported():
    raw = RawModel(
        file_name="Dup.xml",
        tables=[{"name": "T", "id": "1"}, {"name": "T", "id": "2"}],
        value_lists=[{"name": "VL", "id": "1"}, {"name": "VL", "id": "2"}, {"name": "Other", "id": "3"}],
    )
    model = normalize(raw)
    dups = [w for w in model.warnings if w.code == "DUPLICATE_NAME"]
    assert {w.entity_doc_id for w in dups} == {"table:T", "valueList:VL"}
    assert all("only one is kept" in w.message for w in dups)


def test_unique_names_give_no_duplicate_warning(bagel_model):
    assert not [w for w in bagel_model.warnings if w.code == "DUPLICATE_NAME"]
