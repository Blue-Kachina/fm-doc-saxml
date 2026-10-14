"""Multi-file builds: FileMaker 26 folder exports, split catalogs, pairing and cross-file links.

Uses ``samples/multi_file_export`` (FileB has an external TO onto FileA), exported
both as one XML per file and as one folder of catalog XMLs per file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.batch.links import BatchFile, find_target, link_batch, path_file_names
from fm_saxml.cli import OUTPUT_MARKER, app
from fm_saxml.model.document_model import DocumentModel, ExternalDataSource, SourceInfo
from fm_saxml.model.references import ExternalTarget
from fm_saxml.parser.input_scan import manifest_mismatches, scan_input, sniff_root
from fm_saxml.parser.saxml_reader import parse_savexml

SAMPLES = Path(__file__).parent.parent / "samples" / "multi_file_export"
WHOLE = SAMPLES / "SaXML_no_separate_catalogue"
SPLIT = SAMPLES / "SaXML_separate_catalogue"
runner = CliRunner()

pytestmark = pytest.mark.skipif(not WHOLE.exists(), reason="multi-file samples not present")


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Input scanning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder, split", [(WHOLE, False), (SPLIT, True)])
def test_scan_finds_both_files_and_the_manifest(folder, split):
    scan = scan_input(folder)
    assert [s.name for s in scan.solutions] == ["FileA", "FileB"]
    assert all(s.is_split == split for s in scan.solutions)
    assert scan.is_batch
    assert scan.manifest is not None and len(scan.manifest.entries) == 2
    assert manifest_mismatches(scan) == ([], [])
    assert scan.skipped == []


def test_split_solution_lists_every_catalog_fragment():
    scan = scan_input(SPLIT)
    a = scan.solutions[0]
    assert a.path == SPLIT / "FileA"
    assert a.fmp_file_name == "FileA.fmp12"
    assert len(a.fragments) == 19
    assert all(p.parent == SPLIT / "FileA" for p in a.fragments)


def test_a_catalog_folder_on_its_own_is_one_solution():
    scan = scan_input(SPLIT / "FileA")
    assert [s.name for s in scan.solutions] == ["FileA"]
    assert not scan.is_batch
    assert scan.solutions[0].path == SPLIT / "FileA"


def test_sniff_reads_only_the_root(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text('<FMSaveAsXML File="X.fmp12" split_catalogs="True"><never closed', encoding="utf-8")
    root = sniff_root(xml)
    assert root.tag == "FMSaveAsXML" and root.is_fragment


def test_non_exports_are_skipped_with_a_reason(tmp_path):
    folder = _copy(WHOLE, tmp_path / "export")
    (folder / "notes.xml").write_text("<notes/>", encoding="utf-8")
    (folder / "broken.xml").write_text("not xml at all", encoding="utf-8")
    (folder / "readme.txt").write_text("ignored", encoding="utf-8")
    scan = scan_input(folder)
    assert [s.name for s in scan.solutions] == ["FileA", "FileB"]
    reasons = {s.path.name: s.reason for s in scan.skipped}
    assert set(reasons) == {"notes.xml", "broken.xml"}
    assert "not a FileMaker" in reasons["notes.xml"]
    assert "not valid XML" in reasons["broken.xml"]


def test_manifest_reports_missing_and_unlisted_files(tmp_path):
    folder = _copy(WHOLE, tmp_path / "export")
    (folder / "FileB.xml").rename(tmp_path / "FileB.xml")
    shutil.copy(WHOLE / "FileA.xml", folder / "Extra.xml")
    xml = (folder / "Extra.xml").read_text(encoding="utf-8").replace('File="FileA.fmp12"', 'File="Extra.fmp12"', 1)
    (folder / "Extra.xml").write_text(xml, encoding="utf-8")
    missing, extra = manifest_mismatches(scan_input(folder))
    assert [m.fmp_file_name for m in missing] == ["FileB.fmp12"]
    assert [s.name for s in extra] == ["Extra"]


def test_loose_fragments_beside_whole_exports_are_grouped(tmp_path):
    folder = tmp_path / "mixed"
    folder.mkdir()
    shutil.copy(WHOLE / "FileB.xml", folder)
    for frag in (SPLIT / "FileA").iterdir():
        shutil.copy(frag, folder)
    scan = scan_input(folder)
    assert [(s.name, s.is_split) for s in scan.solutions] == [("FileA", True), ("FileB", False)]
    assert scan.solutions[0].path == folder / "FileA"


# ---------------------------------------------------------------------------
# Split catalogs merge back into the whole-file shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["FileA", "FileB"])
def test_split_and_whole_exports_parse_identically(name):
    whole = vars(parse_savexml(WHOLE / f"{name}.xml"))
    split = vars(parse_savexml(SPLIT / name))
    for key in whole:
        if key != "file_name":
            assert json.dumps(whole[key], sort_keys=True, default=str) == json.dumps(split[key], sort_keys=True, default=str), key


def test_empty_catalog_folder_is_a_parse_error(tmp_path):
    raw = parse_savexml(tmp_path)
    assert raw.parse_warnings and raw.parse_warnings[0].startswith("XML parse error")


# ---------------------------------------------------------------------------
# Pairing and target resolution
# ---------------------------------------------------------------------------

def test_path_file_names():
    assert path_file_names(["file:Clients"]) == ["clients"]
    assert path_file_names(["fmnet:/host.example.com/Clients.fmp12"]) == ["clients"]
    assert path_file_names(["filewin:/C:/Data/Clients.fmp12\nfile:Backup"]) == ["clients", "backup"]
    assert path_file_names(["filemac:/Macintosh HD/Data/Clients.fmp7"]) == ["clients"]
    assert path_file_names(["$path", "file:$name"]) == []


def _file(name: str, *sources: ExternalDataSource, uuid: str = "") -> BatchFile:
    model = DocumentModel(source=SourceInfo(fileName=f"{name}.xml", fileUuid=uuid or None))
    model.external_data_sources = list(sources)
    return BatchFile(folder=name, name=name, model=model)


def _ds(name: str, *paths: str, uuid: str | None = None, type: str = "FileMaker") -> ExternalDataSource:
    return ExternalDataSource(name=name, uuid=uuid, type=type, paths=list(paths))


def _pairing(files, source="A"):
    return {p.data_source: p for p in link_batch(files).pairings if p.source == source}


def test_pairs_by_path_not_by_data_source_uuid():
    # The data source UUID is the data source's own; even if it happened to equal
    # another file's UUID, only the path decides.
    a = _file("A", _ds("Main", "file:B", uuid="C-UUID"))
    p = _pairing([a, _file("B"), _file("C", uuid="C-UUID")])["Main"]
    assert (p.target, p.match) == ("B", "path")


def test_pairing_outcomes():
    a = _file(
        "A",
        _ds("Missing", "file:Nowhere"),
        _ds("ByName", ),
        _ds("Variable", "$path"),
        _ds("Self", "file:A"),
        _ds("Both", "file:B\nfile:C"),
        _ds("Sql", "", type="ODBC"),
    )
    p = _pairing([a, _file("B"), _file("C"), _file("ByName")])
    assert p["Missing"].target is None and p["Missing"].reason == "file not in this build"
    assert (p["ByName"].target, p["ByName"].match) == ("ByName", "name")
    assert p["Variable"].target is None and "variable" in p["Variable"].reason
    assert (p["Self"].target, p["Self"].match) == ("A", "path (its own file)")
    assert p["Both"].target is None and p["Both"].reason.startswith("ambiguous")
    assert p["Sql"].target is None and "ODBC" in p["Sql"].reason


def _parsed(name: str) -> DocumentModel:
    from fm_saxml.normalize.normalize import normalize
    from fm_saxml.normalize.references import resolve_references

    return resolve_references(normalize(parse_savexml(WHOLE / f"{name}.xml"), source_file=name))


def _target(**kw) -> ExternalTarget:
    return ExternalTarget(dataSource="FileA", **kw)


def test_find_target_by_uuid_id_and_name():
    a = _parsed("FileA")
    table = next(iter(a.entities.tables.values()))
    field = next(f for f in a.entities.fields.values() if f.name == "PrimaryKey")
    assert find_target(a, _target(targetType="table", name="?", uuid=table.uuid)) == table.doc_id
    assert find_target(a, _target(targetType="table", name="?", fmpId=table.fmp_id)) == table.doc_id
    assert find_target(a, _target(targetType="table", name=table.name.upper())) == table.doc_id
    assert find_target(a, _target(targetType="field", name="?", uuid=field.uuid)) == field.doc_id
    by_id = _target(targetType="field", name="?", fmpId=field.fmp_id, baseTable=table.name)
    assert find_target(a, by_id) == field.doc_id
    assert find_target(a, _target(targetType="field", name="Gone", baseTable=table.name)) is None
    assert find_target(a, _target(targetType="script", name="Nope")) is None


def test_sample_references_resolve_across_files():
    from fm_saxml.analyze.backlinks import generate_backlinks
    from fm_saxml.analyze.warnings import generate_warnings

    models = {n: generate_warnings(generate_backlinks(_parsed(n))) for n in ("FileA", "FileB")}
    assert any(w.code == "UNUSED_FIELD_CANDIDATE" for w in models["FileA"].warnings)
    links = link_batch([BatchFile(n, n, m) for n, m in models.items()])

    assert len(links.references) == 7 and all(r.resolved for r in links.references)
    kinds = sorted(r.ref.external_target.target_type for r in links.references)
    assert kinds == ["field"] * 6 + ["table"]
    # FileA learns who uses it, and its fields stop looking unused
    pk = models["FileA"].backlinks["field:FileA::PrimaryKey"]
    assert {b["sourceDocId"] for b in pk if b["sourceDocId"].startswith("xfile:")} == {"xfile:FileB/relationship:FileB__FileA", "xfile:FileB/layout:FileA"}
    assert not any(w.code == "UNUSED_FIELD_CANDIDATE" for w in models["FileA"].warnings)
    assert links.cross_file["FileA"]["xfile:FileB/layout:FileA"][0] == "../FileB/Layouts/FileA.md"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder", [WHOLE, SPLIT])
def test_build_folder(folder, tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(folder), "--out", str(out), "--html"])
    assert result.exit_code == 0, result.output

    assert (out / OUTPUT_MARKER).exists()
    assert (out / "FileA" / "index.md").exists() and (out / "FileB" / "index.md").exists()
    index = (out / "index.md").read_text(encoding="utf-8")
    assert "- [FileA](FileA/index.md)" in index
    assert "Cross-file references: 7 of 7 resolved." in index
    summary = (out / "Reports" / "batch-summary.md").read_text(encoding="utf-8")
    assert "| FileB | FileA | file:FileA | FileA | path |" in summary

    to_page = (out / "FileB" / "TableOccurrences" / "FileA.md").read_text(encoding="utf-8")
    assert "External — table [FileA](../../FileA/Tables/FileA.md) in file `FileA`" in to_page
    field_page = (out / "FileA" / "Fields" / "FileA" / "PrimaryKey.md").read_text(encoding="utf-8")
    assert "[FileB__FileA (FileB)](../../../FileB/Relationships/FileB__FileA.md)" in field_page
    assert "UNUSED_FIELD_CANDIDATE" not in (out / "FileA" / "Reports" / "warnings.md").read_text(encoding="utf-8")

    manifest = (out / "_viewer" / "manifest.js").read_text(encoding="utf-8")
    assert '"dir":"FileA"' in manifest.replace(" ", "")


def test_default_output_is_next_to_the_folder(tmp_path):
    folder = _copy(WHOLE, tmp_path / "Export 1")
    result = runner.invoke(app, [str(folder)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Export 1_docs" / "FileA" / "index.md").exists()


def test_single_catalog_folder_builds_as_one_file(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(SPLIT / "FileB"), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "index.md").exists() and not (out / "FileB").exists()


@pytest.mark.parametrize("path, hint", [
    (WHOLE / "Summary.xml", "summary of a multi-file export"),
    (SPLIT / "FileA" / "FileA_LayoutCatalog.xml", "one catalog"),
])
def test_files_that_belong_to_a_folder_point_at_it(path, hint, tmp_path):
    result = runner.invoke(app, ["build", str(path), "--out", str(tmp_path / "docs")])
    assert result.exit_code == 1
    assert hint in result.output
    assert not (tmp_path / "docs").exists()


def test_folder_without_exports_fails(tmp_path):
    (tmp_path / "in").mkdir()
    result = runner.invoke(app, ["build", str(tmp_path / "in"), "--out", str(tmp_path / "docs")])
    assert result.exit_code == 1
    assert "No FileMaker Save a Copy as XML exports" in result.output


def test_name_collision_fails_before_writing(tmp_path):
    folder = _copy(WHOLE, tmp_path / "export")
    shutil.copytree(SPLIT / "FileA", folder / "FileA")
    result = runner.invoke(app, ["build", str(folder), "--out", str(tmp_path / "docs")])
    assert result.exit_code == 1
    assert "would both be written to 'FileA/'" in result.output
    assert not (tmp_path / "docs").exists()


def test_one_bad_export_does_not_stop_the_others(tmp_path):
    folder = _copy(WHOLE, tmp_path / "export")
    (folder / "Empty.xml").write_text('<FMSaveAsXML version="2.3.0.0" File="Empty.fmp12"/>', encoding="utf-8")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(folder), "--out", str(out)])
    assert result.exit_code == 1
    assert "Not converted" in result.output
    assert (out / "FileA" / "index.md").exists() and (out / "FileB" / "index.md").exists()
    assert not (out / "Empty").exists()
    assert "Empty.xml" in (out / "index.md").read_text(encoding="utf-8")


def test_strict_fails_on_a_file_missing_from_the_manifest(tmp_path):
    folder = _copy(WHOLE, tmp_path / "export")
    shutil.copy(WHOLE / "FileA.xml", folder / "FileC.xml")
    xml = (folder / "FileC.xml").read_text(encoding="utf-8").replace('File="FileA.fmp12"', 'File="FileC.fmp12"', 1)
    (folder / "FileC.xml").write_text(xml, encoding="utf-8")
    (folder / "FileA.xml").unlink()

    result = runner.invoke(app, ["build", str(folder), "--out", str(tmp_path / "a")])
    assert result.exit_code == 0, result.output
    assert "Summary.xml lists FileA.fmp12" in result.output

    result = runner.invoke(app, ["build", str(folder), "--out", str(tmp_path / "b"), "--strict"])
    assert result.exit_code == 1
    assert "listed in Summary.xml but not found" in result.output


def test_model_out_is_rejected_for_a_folder(tmp_path):
    result = runner.invoke(app, ["build", str(WHOLE), "--out", str(tmp_path / "d"), "--model-out", str(tmp_path / "m.json")])
    assert result.exit_code == 1
    assert "--model-out" in result.output


def test_value_found_in_a_later_file_is_redacted_in_earlier_ones(tmp_path):
    # FileA (analyzed first) has the address only as a modifier's account name, which
    # standard scrubbing doesn't inspect; FileB has it in a comment, where it's detected.
    folder = _copy(WHOLE, tmp_path / "export")
    a = (folder / "FileA.xml").read_text(encoding="utf-8")
    (folder / "FileA.xml").write_text(a.replace('accountName="Admin"', 'accountName="jane.doe@example.com"'), encoding="utf-8")
    b = (folder / "FileB.xml").read_text(encoding="utf-8")
    assert 'comment="Unique identifier of each record in this table"' in b
    b = b.replace('comment="Unique identifier of each record in this table"', 'comment="Owner: jane.doe@example.com"', 1)
    (folder / "FileB.xml").write_text(b, encoding="utf-8")

    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(folder), "--out", str(out)])
    assert result.exit_code == 0, result.output
    leaks = [p for p in out.rglob("*") if p.is_file() and "jane.doe@example.com" in p.read_text(encoding="utf-8")]
    assert leaks == []
    a_pages = "".join(p.read_text(encoding="utf-8") for p in (out / "FileA").rglob("*.md"))
    assert "[EMAIL#" in a_pages

    # The master list shows one placeholder used by both files
    master = (out / "Reports" / "redactions.md").read_text(encoding="utf-8")
    assert "appear in more than one file; they're listed first." in master
    row = next(line for line in master.splitlines() if line.startswith("| `[EMAIL#"))
    assert "[FileA](../FileA/Reports/redactions.md)" in row and "[FileB](../FileB/Reports/redactions.md)" in row
    assert "[Redactions](Reports/redactions.md)" in (out / "index.md").read_text(encoding="utf-8")
    assert "See Reports/redactions.md" in " ".join(result.output.split())


def test_master_redactions_report_when_scrubbing_is_disabled(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(WHOLE), "--out", str(out), "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    assert "Scrubbing was disabled" in (out / "Reports" / "redactions.md").read_text(encoding="utf-8")


def test_inspect_and_validate_accept_a_folder():
    result = runner.invoke(app, ["inspect", str(SPLIT)])
    assert result.exit_code == 0, result.output
    assert "Cross-file references: 7 total, 7 resolved" in result.output
    result = runner.invoke(app, ["validate", str(WHOLE)])
    assert result.exit_code == 0, result.output
