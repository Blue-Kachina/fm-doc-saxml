"""B3: scrubbed raw XML of scripts, layouts, themes and custom menus in raw/*.json."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

import fm_saxml
from fm_saxml.cli import _make_scrubber, _run_pipeline, app
from fm_saxml.contract import RAW_DIR, RAW_FILES
from fm_saxml.render.json.raw_xml import write_raw_xml
from fm_saxml.render.json.writer import build_root_catalog, write_root_catalog, write_split_json

ROOT = Path(__file__).resolve().parent.parent
BAGEL = ROOT / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
MULTI = ROOT / "samples" / "multi_file_export" / "SaXML_no_separate_catalogue"
SCHEMA = ROOT / "docs" / "contract" / "schema-1.0" / "raw-xml.schema.json"
SECRET = "hunter2-Sup3r!"
runner = CliRunner()

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


def _seed(dst: Path) -> Path:
    """F0 with a password in its (empty) Set Variable step, in FileMaker's own shape."""
    src = BAGEL.read_text(encoding="utf-8")
    pat = re.compile(r'(name="Set Variable".*?<Parameter type="Variable">\s*)<value></value>(\s*)<Name value=""></Name>',
                     re.S)
    seeded = pat.sub(r'\1<value><Calculation datatype="1" position="1"><Calculation><Text><![CDATA["'
                     + SECRET + r'"]]></Text></Calculation></Calculation></value>\2<Name value="$password"></Name>',
                     src, count=1)
    assert seeded != src
    dst.write_text(seeded, encoding="utf-8")
    return dst


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The seeded F0 built with scrubbing on, the way ``build`` writes it (raw XML before the pages)."""
    tmp = tmp_path_factory.mktemp("raw")
    scrubber = _make_scrubber(False, "standard", None, None)
    model = _run_pipeline(_seed(tmp / "EverythingBagel.xml"), scrubber)
    out = tmp / "docs"
    assert write_raw_xml(model, out, scrubber) > 0
    write_split_json(model, out)
    write_root_catalog(out, build_root_catalog("single", "EverythingBagel", [(model, "", model.solution.name)]))
    return model, out


def _raw(out: Path, kind: str) -> dict:
    return json.loads((out / RAW_DIR / RAW_FILES[kind]).read_text(encoding="utf-8"))


def test_every_script_layout_theme_and_menu_has_its_xml(built):
    model, out = built
    e = model.entities
    assert set(_raw(out, "scripts")["xml"]) == set(e.scripts)
    assert set(_raw(out, "layouts")["xml"]) == set(e.layouts)
    assert set(_raw(out, "themes")["xml"]) == set(e.themes)
    assert set(_raw(out, "menus")["xml"]) == set(e.custom_menus) | set(e.custom_menu_sets)


def test_files_carry_the_envelope_and_match_the_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    _, out = built
    entities = json.loads((out / "entities.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for kind in RAW_FILES:
        doc = _raw(out, kind)
        assert {k: doc[k] for k in ("schemaVersion", "generator", "source")} == {
            k: entities[k] for k in ("schemaVersion", "generator", "source")}
        jsonschema.validate(doc, schema)


def test_script_xml_parses_and_holds_every_step_in_order(built):
    model, out = built
    for doc_id, xml in _raw(out, "scripts")["xml"].items():
        script = etree.fromstring(xml)
        indexes = [int(s.get("index")) for s in script.find("ObjectList").findall("Step")]
        expected = sorted(s.index for s in model.entities.script_steps.values() if s.script_doc_id == doc_id)
        assert indexes == expected, doc_id


def test_seeded_secret_is_redacted_with_the_pages_placeholder(built):
    model, out = built
    assert not [p for p in out.rglob("*") if p.is_file() and SECRET in p.read_text(encoding="utf-8")]
    step = next(s for s in model.entities.script_steps.values() if s.name == "Set Variable")
    placeholder = re.search(r"\[REDACTED:password#\d+\]", " ".join(c.text for c in step.calculations)).group()
    step_xml = fm_saxml.load(out).raw_xml(step.doc_id)
    assert placeholder in step_xml
    assert "hash=" not in step_xml.split(">", 1)[0]  # a digest of the original would confirm a guess


def test_reader_cuts_steps_and_objects_from_their_parents(built):
    model, out = built
    docs = fm_saxml.load(out)
    step = model.entities.script_steps["scriptStep:OneOfEverything:0003"]
    assert etree.fromstring(docs.raw_xml(step.doc_id)).get("name") == step.name
    obj = etree.fromstring(docs.raw_xml("layoutObject:EverythingBagel::2"))
    assert (obj.tag, obj.get("type")) == ("LayoutObject", "Edit Box")
    theme = etree.fromstring(docs.raw_xml(next(iter(model.entities.themes))))
    assert theme.find("CSS") is not None  # the theme CSS agentic-fm's extract_theme.py reads
    assert etree.fromstring(docs.raw_xml("customMenu:Custom Custom Menu")).tag == "CustomMenu"
    assert etree.fromstring(docs.raw_xml("customMenuSet:Custom Menu Set")).tag == "CustomMenuSet"
    layout = etree.fromstring(docs.raw_xml("layout:EverythingBagel"))
    assert layout.find(".//LocalCSS") is not None  # object CSS for layout_to_summary.py's visuals


def test_reader_errors_are_clear(built, tmp_path):
    _, out = built
    docs = fm_saxml.load(out)
    with pytest.raises(fm_saxml.RawXmlNotFoundError, match="only scripts, steps"):
        docs.raw_xml("table:EverythingBagel")
    with pytest.raises(fm_saxml.RawXmlNotFoundError, match="isn't in"):
        docs.raw_xml("script:No Such Script")
    bare = tmp_path / "bare"
    shutil.copytree(out, bare)
    shutil.rmtree(bare / RAW_DIR)
    with pytest.raises(fm_saxml.RawXmlNotFoundError, match="--no-raw-xml"):
        fm_saxml.load(bare).raw_xml("script:OneOfEverything")


@pytest.mark.skipif(not MULTI.exists(), reason="multi-file samples not present")
def test_batch_writes_raw_xml_per_file_and_no_raw_xml_skips_it(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(MULTI), "--out", str(out)])
    assert result.exit_code == 0, result.output
    batch = fm_saxml.load(out)
    for folder in ("FileA", "FileB"):
        assert {p.name for p in (out / folder / RAW_DIR).iterdir()} == set(RAW_FILES.values())
        assert etree.fromstring(batch[folder].raw_xml(f"layout:{folder}")).get("name") == folder

    out2 = tmp_path / "docs2"
    result = runner.invoke(app, ["build", str(MULTI), "--out", str(out2), "--no-raw-xml"])
    assert result.exit_code == 0, result.output
    assert not list(out2.rglob(RAW_DIR))


@pytest.mark.skipif(not MULTI.exists(), reason="multi-file samples not present")
def test_value_found_in_a_later_file_is_redacted_in_an_earlier_files_raw_xml(tmp_path):
    # FileA has the address only as a modifier's account name (not inspected); FileB has it in a comment.
    folder = tmp_path / "export"
    shutil.copytree(MULTI, folder)
    a = (folder / "FileA.xml").read_text(encoding="utf-8")
    (folder / "FileA.xml").write_text(a.replace('accountName="Admin"', 'accountName="jane.doe@example.com"'),
                                      encoding="utf-8")
    b = (folder / "FileB.xml").read_text(encoding="utf-8")
    (folder / "FileB.xml").write_text(b.replace('comment="Unique identifier of each record in this table"',
                                                'comment="Owner: jane.doe@example.com"', 1), encoding="utf-8")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(folder), "--out", str(out), "--scrub-level", "standard"])
    assert result.exit_code == 0, result.output
    raw_a = "".join(p.read_text(encoding="utf-8") for p in (out / "FileA" / RAW_DIR).glob("*.json"))
    assert "jane.doe@example.com" not in raw_a and "[EMAIL#" in raw_a
