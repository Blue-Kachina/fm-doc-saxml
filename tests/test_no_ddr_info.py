"""Exports without DDR info (D1): agentic-fm's scripted Save a Copy as XML writes Has_DDR_INFO="False".

The fixture is the Mac exploder run's export (samples/EverythingBagel_mac_run/), a no-DDR twin of
samples/by_type/whole/ plus the two scripts pasted in to run Explode XML.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fm_saxml.cli import _run_pipeline
from fm_saxml.contract_models import CatalogFile, ContractSource
from fm_saxml.normalize.normalize import normalize
from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.render.json.writer import build_root_catalog, write_split_json
from fm_saxml.render.markdown.renderer import render_markdown

ROOT = Path(__file__).resolve().parent.parent
WHOLE = ROOT / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
NO_DDR = ROOT / "samples" / "EverythingBagel_mac_run" / "saxml" / "EverythingBagel.xml"
PASTED = {"script:Explode XML", "script:Get agentic-fm path"}  # pasted into the Mac copy to run the exploder


@pytest.fixture(scope="module")
def models():
    if not (WHOLE.exists() and NO_DDR.exists()):
        pytest.skip("sample exports not present")
    return _run_pipeline(WHOLE, coverage=True), _run_pipeline(NO_DDR, coverage=True)


def _is_pasted(doc_id: str) -> bool:
    return any(doc_id == p or doc_id.startswith(f"{p.replace('script:', 'scriptStep:')}:")
               or doc_id.startswith(f"variable:{p[len('script:'):]}::") for p in PASTED)


def test_source_says_whether_the_export_has_ddr_info(models):
    whole, no_ddr = models
    assert whole.source.has_ddr_info is True
    assert no_ddr.source.has_ddr_info is False


def test_same_entities_apart_from_the_pasted_scripts(models):
    whole, no_ddr = models
    for name in type(whole.entities).model_fields:
        a, b = set(getattr(whole.entities, name)), set(getattr(no_ddr.entities, name))
        assert a <= b, name
        # $$AGENTIC.FM is the pasted scripts' global
        assert all(_is_pasted(d) or d == "variable:$$AGENTIC.FM" for d in b - a), (name, b - a)


def test_references_differ_only_in_the_external_base_table(models):
    whole, no_ddr = models

    def keys(model):
        return {json.dumps(r.model_dump(by_alias=True, exclude_none=True), sort_keys=True): r
                for r in model.references if not _is_pasted(r.source_doc_id)}

    a, b = keys(whole), keys(no_ddr)
    assert not set(b) - set(a)
    lost = [a[k] for k in set(a) - set(b)]
    assert [(r.source_doc_id, r.relationship_type, r.external_target.target_doc_id) for r in lost] == [
        ("to:Empty", "basedOnBaseTable", "table:Empty")]


def test_one_warning_names_what_is_missing(models):
    whole, no_ddr = models
    assert not [w for w in whole.warnings if w.code == "NO_DDR_INFO"]
    [w] = [w for w in no_ddr.warnings if w.code == "NO_DDR_INFO"]
    for lost in ("Script Workspace text", "calculation references", "popover titles", "base table"):
        assert lost in w.message
    assert "include_details" in w.detail


def test_contract_source_and_catalog_carry_the_flag(models, tmp_path):
    _, no_ddr = models
    write_split_json(no_ddr, tmp_path)
    for name in ("entities.json", "references.json", "backlinks.json", "external-references.json"):
        doc = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert ContractSource.model_validate(doc["source"]).has_ddr_info is False, name
    catalog = build_root_catalog("single", "EverythingBagel", [(no_ddr, "", "EverythingBagel")])
    assert CatalogFile.model_validate(catalog["files"][0]).has_ddr_info is False


def test_pages_say_so(models, tmp_path):
    whole, no_ddr = models
    render_markdown(no_ddr, tmp_path / "no_ddr")
    render_markdown(whole, tmp_path / "whole")
    for page in ("index.md", "Reports/coverage.md"):
        assert "Exported without DDR info" in (tmp_path / "no_ddr" / page).read_text(encoding="utf-8"), page
        assert "Exported without DDR info" not in (tmp_path / "whole" / page).read_text(encoding="utf-8"), page


def test_missing_attribute_is_unknown_not_false(tmp_path):
    xml = tmp_path / "t.xml"
    xml.write_text('<FMSaveAsXML version="2.2.3.0" File="t.fmp12"><Structure><AddAction/></Structure></FMSaveAsXML>',
                   encoding="utf-8")
    model = normalize(parse_savexml(xml), "t.xml")
    assert model.source.has_ddr_info is None
    assert not [w for w in model.warnings if w.code == "NO_DDR_INFO"]
