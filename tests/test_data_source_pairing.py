"""G5: each data source records which file of a batch it was paired with (entities.json, index.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.cli import app

WHOLE = Path(__file__).parent.parent / "samples" / "multi_file_export" / "SaXML_no_separate_catalogue"
runner = CliRunner()

pytestmark = pytest.mark.skipif(not WHOLE.exists(), reason="multi-file samples not present")


@pytest.fixture(scope="module")
def batch_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("pairing") / "docs"
    result = runner.invoke(app, ["build", str(WHOLE), "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def _sources(out: Path, folder: str) -> dict:
    return json.loads((out / folder / "entities.json").read_text(encoding="utf-8"))["externalDataSources"]


def test_entities_json_names_the_paired_file(batch_out):
    [ds] = _sources(batch_out, "FileB").values()
    assert ds["pairing"] == {"file": "FileA", "folder": "FileA", "match": "path", "reason": ""}
    for d in _sources(batch_out, "FileA").values():
        assert d["pairing"] is not None  # every data source of a batch file says how it went


def test_index_links_the_paired_file(batch_out):
    index = (batch_out / "FileB" / "index.md").read_text(encoding="utf-8")
    assert "| Name | Type | File Path List | Paired With |" in index
    assert "[FileA](../FileA/index.md)" in index


def test_single_file_build_has_no_pairing(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(WHOLE / "FileB.xml"), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert all(d["pairing"] is None for d in _sources(out, ".").values())
    assert "Paired With" not in (out / "index.md").read_text(encoding="utf-8")
