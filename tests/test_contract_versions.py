"""Contract versions over time: models, upgrade chain, JSON Schemas, golden output (C1d, C1e).

After an intended change to the contract output or models, regenerate the
committed copies with:   uv run pytest tests/test_contract_versions.py --update-golden
"""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path

import pytest

from fm_saxml.cli import _run_pipeline
from fm_saxml.contract import CONTRACT_FILES, CONTRACT_VERSION, ROOT_CATALOG, format_version
from fm_saxml.contract_migrations import (
    ContractVersionError, file_version, read_contract_file, upgrade,
)
from fm_saxml.contract_models import (
    DOC_MODELS, ContractEnvelope, EntitiesDoc, SCHEMA_ROOT, json_schemas, schema_dir_name, write_schemas,
)
from fm_saxml.model.document_model import EntityMaps
from fm_saxml.render.json.writer import build_root_catalog, write_root_catalog, write_split_json

ROOT = Path(__file__).resolve().parent.parent
BAGEL = ROOT / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
V0 = Path(__file__).resolve().parent / "fixtures" / "contract_v0"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "contract_golden" / "EverythingBagel"
SCHEMAS = ROOT / SCHEMA_ROOT / schema_dir_name()


@pytest.fixture(scope="module")
def bagel_out(tmp_path_factory):
    if not BAGEL.exists():
        pytest.skip("samples/by_type fixture not present")
    out = tmp_path_factory.mktemp("bagel_contract")
    model = _run_pipeline(BAGEL)
    write_split_json(model, out)
    write_root_catalog(out, build_root_catalog("single", "EverythingBagel", [(model, "", model.solution.name)]))
    return out


ALL_FILES = (ROOT_CATALOG, *CONTRACT_FILES)  # docs.json has its own model, outside DOC_MODELS


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Models describe the output exactly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", CONTRACT_FILES)
def test_models_round_trip_every_contract_file(bagel_out, name):
    data = _load(bagel_out / name)
    back = DOC_MODELS[name].model_validate(data).model_dump(by_alias=True, mode="json", exclude_unset=True)
    assert back == data  # a key the writer adds without a model field would be dropped here


def test_entities_model_covers_every_entity_map():
    fields = {info.alias or n for n, info in EntitiesDoc.model_fields.items()}
    assert {info.alias or n for n, info in EntityMaps.model_fields.items()} <= fields


@pytest.mark.parametrize("name", CONTRACT_FILES)
def test_read_contract_file_returns_the_typed_model(bagel_out, name):
    doc = read_contract_file(bagel_out / name)
    assert isinstance(doc, DOC_MODELS[name]) and doc.schema_version == format_version(CONTRACT_VERSION)


# ---------------------------------------------------------------------------
# Upgrade chain
# ---------------------------------------------------------------------------

def test_versions_of_old_and_current_files():
    assert file_version([{"sourceDocId": "x"}]) == (0, 0)          # bare references array
    assert file_version({"tables": {}}) == (0, 0)                  # entities without envelope
    assert file_version({"schemaVersion": "1.0.0"}) == (0, 0)      # old external-references version
    assert file_version({"schemaVersion": "1.0"}) == (1, 0)
    assert file_version({"schemaVersion": "1.9"}) == (1, 9)
    with pytest.raises(ContractVersionError):
        file_version({"schemaVersion": "one"})


@pytest.mark.parametrize("name", CONTRACT_FILES)
def test_v0_fixture_upgrades_and_validates(name):
    raw = _load(V0 / name)
    assert file_version(raw) == (0, 0)
    upgraded = upgrade(name, raw)
    assert upgraded["schemaVersion"] == "1.0" and upgraded["generator"] is None
    DOC_MODELS[name].model_validate(upgraded)


def test_v0_upgrade_keeps_the_data():
    ents = read_contract_file(V0 / "entities.json")
    raw = _load(V0 / "entities.json")
    assert set(ents.scripts) == set(raw["scripts"]) and set(ents.fields) == set(raw["fields"])
    assert ents.accounts == {}  # a collection the old file lacked takes its default

    refs = read_contract_file(V0 / "references.json")
    assert len(refs.references) == len(_load(V0 / "references.json"))
    assert refs.references[0].via is None  # key added after v0: default

    links = read_contract_file(V0 / "backlinks.json")
    assert set(links.backlinks) == set(_load(V0 / "backlinks.json"))

    ext = read_contract_file(V0 / "external-references.json")
    assert ext.source.fmp_file_name == "EverythingBagel.fmp12"
    dumped = json.dumps(upgrade("external-references.json", _load(V0 / "external-references.json")))
    assert "fileName" not in dumped and "D:\\\\" not in dumped  # the absolute input path is dropped


def test_newer_minor_reads_and_ignores_unknown_keys(tmp_path):
    path = tmp_path / "references.json"
    path.write_text(json.dumps({
        "schemaVersion": "1.9", "generator": {"name": "fm-saxml-converter", "version": "9.9.9"},
        "source": {"fileUuid": "U", "somethingNew": True},
        "references": [{"sourceDocId": "script:A", "sourceEntityType": "script", "targetDocId": "layout:B",
                        "targetEntityType": "layout", "relationshipType": "navigatesTo", "addedIn19": 1}],
        "anotherNewCollection": {},
    }), encoding="utf-8")
    doc = read_contract_file(path)
    assert doc.schema_version == "1.9" and doc.references[0].target_doc_id == "layout:B"
    assert "addedIn19" not in doc.references[0].model_dump(by_alias=True)


@pytest.mark.parametrize("name", CONTRACT_FILES)
def test_newer_major_fails_clearly(tmp_path, name):
    path = tmp_path / name
    path.write_text(json.dumps({"schemaVersion": "2.0"}), encoding="utf-8")
    with pytest.raises(ContractVersionError) as exc:
        read_contract_file(path)
    msg = str(exc.value)
    assert str(path) in msg
    assert f"docs written by schema 2.x; this fm-saxml reads up to {CONTRACT_VERSION[0]}.x — upgrade fm-saxml" in msg


def test_not_a_contract_file(tmp_path):
    path = tmp_path / "model.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a contract file"):
        read_contract_file(path)


# ---------------------------------------------------------------------------
# JSON Schemas (docs/contract/schema-<version>/)
# ---------------------------------------------------------------------------

def test_committed_json_schemas_are_current(request):
    if request.config.getoption("--update-golden"):
        write_schemas(SCHEMAS)
    committed = {p.name: _load(p) for p in SCHEMAS.glob("*.schema.json")}
    assert committed == json_schemas(), (
        "The contract models changed: run `uv run pytest tests/test_contract_versions.py --update-golden` "
        "and commit docs/contract/. A change that removes or renames a key needs a new major version."
    )


@pytest.mark.parametrize("name", ALL_FILES)
def test_build_validates_against_committed_schema(bagel_out, name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = _load(SCHEMAS / name.replace(".json", ".schema.json"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [f"{list(e.absolute_path)[:4]}: {e.message[:150]}" for e in validator.iter_errors(_load(bagel_out / name))]
    assert not errors, errors[:5]


def test_contract_doc_lists_every_collection():
    doc = (ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
    envelope = set(ContractEnvelope.model_fields)
    for name, info in EntitiesDoc.model_fields.items():
        if name not in envelope:
            assert f"`{info.alias or name}`" in doc, f"docs/contract.md doesn't mention {info.alias or name}"
    assert f"schema-{CONTRACT_VERSION[0]}.{CONTRACT_VERSION[1]}" in doc


# ---------------------------------------------------------------------------
# Golden output (tests/fixtures/contract_golden/)
# ---------------------------------------------------------------------------

def _comparable(data):
    """The package version changes every release without changing the contract."""
    if isinstance(data, dict) and isinstance(data.get("generator"), dict):
        data = {**data, "generator": {**data["generator"], "version": "<version>"}}
    return data


@pytest.mark.parametrize("name", ALL_FILES)
def test_contract_output_matches_golden(bagel_out, name, request):
    golden = GOLDEN / name
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bagel_out / name, golden)
    new, old = _comparable(_load(bagel_out / name)), _comparable(_load(golden))
    if new != old:
        diff = difflib.unified_diff(
            json.dumps(old, indent=1, sort_keys=True).splitlines(),
            json.dumps(new, indent=1, sort_keys=True).splitlines(),
            "golden", "build", lineterm="", n=2,
        )
        pytest.fail(f"{name} differs from the golden copy (rerun with --update-golden if intended):\n"
                    + "\n".join(list(diff)[:80]))
