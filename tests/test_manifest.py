"""Summary.xml: synthesized in memory when a folder has none (M1, M2), and pairing ignores it (M3).

See docs/manifest.md.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.parser.input_scan import manifest_mismatches, scan_input

SAMPLES = Path(__file__).parent.parent / "samples" / "multi_file_export"
WHOLE = SAMPLES / "SaXML_no_separate_catalogue"
SPLIT = SAMPLES / "SaXML_separate_catalogue"
V1 = Path(__file__).parent / "fixtures" / "small_sample.xml"
runner = CliRunner()

pytestmark = pytest.mark.skipif(not WHOLE.exists(), reason="multi-file samples not present")


def _without_manifest(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    (dst / "Summary.xml").unlink()
    return dst


def _build(folder: Path, out: Path, *args: str):
    result = runner.invoke(app, ["build", str(folder), "--out", str(out), *args])
    assert result.exit_code == 0, result.output
    return result


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src, split", [(WHOLE, False), (SPLIT, True)])
def test_folder_without_manifest_gets_one_in_memory(src, split, tmp_path):
    folder = _without_manifest(src, tmp_path / "export")
    scan = scan_input(folder)
    m = scan.manifest
    assert m is not None and m.synthesized and m.path is None
    assert [e.fmp_file_name for e in m.entries] == ["FileA.fmp12", "FileB.fmp12"]
    assert m.created == "" and not any(e.host for e in m.entries)
    assert all(e.xml_path.endswith(os.sep) == split for e in m.entries)
    assert manifest_mismatches(scan) == ([], [])
    assert not (folder / "Summary.xml").exists()


def test_real_manifest_is_not_synthesized():
    m = scan_input(WHOLE).manifest
    assert m is not None and not m.synthesized and m.created and m.generator == ""


def test_single_export_folder_needs_no_manifest(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    shutil.copy(WHOLE / "FileA.xml", folder)
    scan = scan_input(folder)
    assert not scan.is_batch and scan.manifest is None


def test_v1_export_is_named_after_its_xml(tmp_path):
    folder = _without_manifest(WHOLE, tmp_path / "export")
    shutil.copy(V1, folder / "Legacy.xml")
    names = [e.fmp_file_name for e in scan_input(folder).manifest.entries]
    assert "Legacy.fmp12" in names and len(names) == 3


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", [WHOLE, SPLIT])
def test_build_without_manifest_says_so(src, tmp_path):
    folder = _without_manifest(src, tmp_path / "export")
    out = tmp_path / "docs"
    result = _build(folder, out, "--strict")
    assert "No Summary.xml in this folder" in result.output
    assert not (folder / "Summary.xml").exists()  # never written into the input

    index = _read(out / "index.md")
    assert "| Summary.xml | not present (built from 2 exports) |" in index
    assert "XML Created At" not in index and "Exported From" not in index
    assert "| Summary.xml | not present (built from 2 exports) |" in _read(out / "Reports" / "batch-summary.md")
    assert json.loads(_read(out / "docs.json"))["synthesizedManifest"] is True


def test_build_with_manifest_says_present(tmp_path):
    out = tmp_path / "docs"
    _build(WHOLE, out)
    index = _read(out / "index.md")
    assert "| Summary.xml | present |" in index and "| XML Created At | 2026-10-14 10:19:47 AM |" in index
    assert json.loads(_read(out / "docs.json"))["synthesizedManifest"] is False


def test_manifest_from_another_tool_is_labelled(tmp_path):
    folder = tmp_path / "export"
    shutil.copytree(WHOLE, folder)
    xml = _read(folder / "Summary.xml").replace('type="Summary"', 'type="Summary" generator="agentic-fm"', 1)
    (folder / "Summary.xml").write_text(xml, encoding="utf-8")
    out = tmp_path / "docs"
    _build(folder, out)
    assert "| Summary.xml | present (written by agentic-fm) |" in _read(out / "index.md")


def test_v1_export_builds_in_a_folder_without_manifest(tmp_path):
    folder = _without_manifest(WHOLE, tmp_path / "export")
    shutil.copy(V1, folder / "Legacy.xml")
    out = tmp_path / "docs"
    _build(folder, out)
    assert (out / "Legacy" / "index.md").exists()
    assert "| Summary.xml | not present (built from 3 exports) |" in _read(out / "index.md")


# ---------------------------------------------------------------------------
# M3: pairing never uses the manifest
# ---------------------------------------------------------------------------

def _pairing_section(summary: str) -> str:
    return re.search(r"## Data Source Pairings\n(.*?)(?=\n## |\Z)", summary, re.S).group(1)


def test_pairing_is_the_same_with_and_without_manifest(tmp_path):
    with_m, without_m = tmp_path / "with", tmp_path / "without"
    _build(WHOLE, with_m)
    _build(_without_manifest(WHOLE, tmp_path / "export"), without_m)

    a, b = _read(with_m / "Reports" / "batch-summary.md"), _read(without_m / "Reports" / "batch-summary.md")
    assert "| FileB | FileA | file:FileA | FileA | path |" in a
    assert _pairing_section(a) == _pairing_section(b)

    line = re.compile(r"Cross-file references: \d+ of \d+ resolved\.")
    xa, xb = line.search(_read(with_m / "index.md")).group(), line.search(_read(without_m / "index.md")).group()
    assert xa == xb == "Cross-file references: 7 of 7 resolved."
    assert json.loads(_read(with_m / "docs.json"))["pairings"] == json.loads(_read(without_m / "docs.json"))["pairings"]
