"""The Python reader API (C2): fm_saxml.load(), SolutionDocs, BatchDocs.resolve()."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fm_saxml
from fm_saxml import BatchDocs, ContractVersionError, DocsNotFoundError, SolutionDocs, load
from fm_saxml.cli import app
from fm_saxml.model import LayoutObjectEntity, ScriptEntity, ThemeEntity
from fm_saxml.model.references import ReferenceRecord

ROOT = Path(__file__).resolve().parent.parent
BY_TYPE = ROOT / "samples" / "by_type"
V0 = Path(__file__).resolve().parent / "fixtures" / "contract_v0"
runner = CliRunner()

# The scrubbing guard trips on this sample (backlog B1), so build it unscrubbed: it's public.
BUILD = ["build", "-y", "--disable-scrubbing"]


@pytest.fixture(scope="module")
def single(tmp_path_factory) -> Path:
    if not BY_TYPE.exists():
        pytest.skip("samples/by_type fixture not present")
    out = tmp_path_factory.mktemp("api") / "bagel"
    result = runner.invoke(app, [*BUILD, str(BY_TYPE / "whole" / "EverythingBagel.xml"), "-o", str(out)])
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture(scope="module")
def batch(tmp_path_factory) -> Path:
    if not BY_TYPE.exists():
        pytest.skip("samples/by_type fixture not present")
    out = tmp_path_factory.mktemp("api") / "two_files"
    result = runner.invoke(app, [*BUILD, str(BY_TYPE / "second_file"), "-o", str(out)])
    assert result.exit_code == 0, result.output
    return out


# ---------------------------------------------------------------------------
# One file
# ---------------------------------------------------------------------------

def test_public_surface():
    for name in fm_saxml.__all__:
        assert getattr(fm_saxml, name) is not None
    import fm_saxml.model as m
    assert {"LayoutObjectEntity", "AccountEntity", "VariableEntity", "ExternalTarget", "IndirectionSite"} <= set(m.__all__)
    for name in m.__all__:
        assert getattr(m, name) is not None


def test_load_one_file(single):
    docs = load(single)
    assert isinstance(docs, SolutionDocs)
    assert docs.catalog.kind == "single" and docs.catalog.solution == "EverythingBagel"
    assert docs.schema_version == "1.0"
    assert docs.name == "EverythingBagel"
    assert docs.source.file_uuid == "400FEDB4-F509-8F4D-AF05-472A0DE02EAC"
    script = docs.entities.scripts["script:OneOfEverything"]
    assert isinstance(script, ScriptEntity)
    assert all(isinstance(o, LayoutObjectEntity) for o in docs.entities.layout_objects.values())
    assert all(isinstance(r, ReferenceRecord) for r in docs.references)


def test_find_ignores_case_and_matches_qualified_and_display_names(single):
    docs = load(single)
    assert [s.doc_id for s in docs.find("script", "oneofeverything")] == ["script:OneOfEverything"]
    assert [s.doc_id for s in docs.find("scripts", "ONEOFEVERYTHING")] == ["script:OneOfEverything"]
    field = next(iter(docs.entities.fields.values()))
    assert docs.find("field", field.qualified_name.upper()) == [field]
    assert docs.find("field", field.name) and field in docs.find("field", field.name)
    themes = docs.find("theme", "vibrant custom")
    assert len(themes) == 1 and isinstance(themes[0], ThemeEntity)
    assert docs.find("dataSource", "EMPTY")[0].name == "Empty"
    assert docs.find("script", "no such script") == []
    with pytest.raises(ValueError, match="unknown kind"):
        docs.find("gizmo", "x")


def test_get_and_collection(single):
    docs = load(single)
    for doc_id in ("script:OneOfEverything", "dataSource:Empty", "customMenuSet:Custom Menu Set"):
        assert docs.get(doc_id) is not None, doc_id
    assert docs.get("script:missing") is None and docs.get("nonsense") is None
    assert docs.collection("tableOccurrence") is docs.entities.table_occurrences


def test_refs_from_and_to(single):
    docs = load(single)
    for r in docs.references[:50]:
        assert r in docs.refs_from(r.source_doc_id)
        assert r in docs.refs_to(r.target_doc_id)
    assert docs.refs_to("script:missing") == []


def test_v0_docs_load_through_the_upgrade_chain():
    docs = load(V0)  # pre-contract output: no docs.json, no envelope
    assert isinstance(docs, SolutionDocs) and docs.catalog is None
    assert docs.schema_version == "1.0"
    assert docs.source.fmp_file_name == "EverythingBagel.fmp12"  # from external-references
    assert docs.name == "EverythingBagel"
    assert docs.entities.scripts and docs.references


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def test_not_docs(tmp_path):
    with pytest.raises(DocsNotFoundError, match="not a folder"):
        load(tmp_path / "missing")
    with pytest.raises(DocsNotFoundError, match="holds no fm-saxml docs"):
        load(tmp_path)


def test_missing_contract_file_names_its_path(tmp_path, single):
    shutil.copyfile(single / "entities.json", tmp_path / "entities.json")
    docs = load(tmp_path)
    assert docs.entities.scripts
    with pytest.raises(DocsNotFoundError) as exc:
        docs.references
    assert str(tmp_path / "references.json") in str(exc.value)


def test_newer_major_fails_on_load(tmp_path, single):
    shutil.copytree(single, tmp_path / "docs")
    catalog = tmp_path / "docs" / "docs.json"
    catalog.write_text(json.dumps({**json.loads(catalog.read_text(encoding="utf-8")), "schemaVersion": "2.0"}),
                       encoding="utf-8")
    with pytest.raises(ContractVersionError, match="docs written by schema 2.x") as exc:
        load(tmp_path / "docs")
    assert str(catalog) in str(exc.value)


# ---------------------------------------------------------------------------
# A batch
# ---------------------------------------------------------------------------

def test_load_batch(batch):
    docs = load(batch)
    assert isinstance(docs, BatchDocs) and len(docs) == 2
    assert set(docs) == {"EverythingBagel", "Empty"}
    assert docs["empty"] is docs["Empty"] is docs["Empty.fmp12"]
    assert docs["Empty"].entities.tables
    with pytest.raises(KeyError, match="not in"):
        docs["Nope"]
    pairing = next(p for p in docs.catalog.pairings if p.data_source == "Empty")
    assert pairing.target_folder == docs.catalog.files[[f.name for f in docs.catalog.files].index("Empty")].folder
    assert pairing.match == "path" and pairing.data_source_uuid


def _external_target(docs: BatchDocs) -> str:
    bagel = docs["EverythingBagel"]
    return next(r.target_doc_id for r in bagel.references if r.confidence == "external")


def test_resolve_every_scope_form(batch):
    docs = load(batch)
    target = _external_target(docs)          # ds:<uuid>/<docId>
    hit = docs.resolve(target)
    assert hit.file is docs["Empty"] and hit.entity is not None and hit.entity.doc_id == hit.doc_id

    empty = docs["Empty"]
    assert docs.resolve(f"{empty.source.file_uuid}/{hit.doc_id}").entity is hit.entity
    assert docs.resolve(f"{empty.source.file_uuid.lower()}/{hit.doc_id}").file is empty
    assert docs.resolve(f"file:Empty.fmp12/{hit.doc_id}").file is empty

    xfile = next(b.source_doc_id for links in empty.backlinks.values() for b in links
                 if b.source_doc_id.startswith("xfile:"))
    back = docs.resolve(xfile)
    assert back.file is docs["EverythingBagel"] and back.entity is not None

    assert docs.resolve(f"{empty.source.file_uuid}/script:missing").entity is None
    assert docs.resolve("00000000-0000-0000-0000-000000000000/table:X") is None
    with pytest.raises(ValueError, match="no file scope"):
        docs.resolve(hit.doc_id)


def test_resolve_in_a_batch_built_before_docs_json(tmp_path, batch):
    shutil.copytree(batch, tmp_path / "old")
    (tmp_path / "old" / "docs.json").unlink()
    docs = load(tmp_path / "old")
    assert isinstance(docs, BatchDocs) and docs.catalog is None and len(docs) == 2
    hit = docs.resolve(_external_target(docs))  # paired by path, as the build does
    assert hit is not None and hit.file.name == "Empty" and hit.entity is not None


# ---------------------------------------------------------------------------
# rename-check reads a docs folder (dogfooding load())
# ---------------------------------------------------------------------------

def _report(args, tmp_path: Path, name: str) -> list[str]:
    out = tmp_path / f"{name}.md"
    result = runner.invoke(app, ["rename-check", *args, "-o", str(out), "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    return [line for line in out.read_text(encoding="utf-8").splitlines() if not line.startswith("Source:")]


def test_rename_check_on_docs_folder_matches_the_xml(single, tmp_path):
    docs = load(single)
    names = [s.qualified_name for s in list(docs.entities.fields.values())[:3]]
    names += [s.name for s in list(docs.entities.scripts.values())[:2]]
    names += sorted({c.name for site in docs.entities.indirection_sites.values() for c in site.candidates})[:3]
    from_xml = _report([str(BY_TYPE / "whole" / "EverythingBagel.xml"), *names], tmp_path, "xml")
    from_docs = _report([str(single), *names], tmp_path, "docs")
    assert from_docs == from_xml


def test_rename_check_refuses_a_batch_root(batch):
    result = runner.invoke(app, ["rename-check", str(batch), "Anything"])
    assert result.exit_code == 1
    assert "several files" in result.output


def test_importing_the_reader_loads_no_cli_dependencies():
    """agentic-fm imports fm_saxml to read docs: that must not pull in the parser or the CLI (Q7)."""
    import subprocess
    import sys

    code = ("import sys, fm_saxml; "
            "print(','.join(m for m in ('lxml', 'typer', 'rich', 'jinja2', 'slugify') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == ""
