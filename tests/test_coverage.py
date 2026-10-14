"""The coverage report, and the gaps it found on the production export.

The report counts things in the XML independently of the extractors and sets them
against the finished docs. On the sample exports every check must pass and nothing may
be unrecognised: that is the non-regression floor. The rest pins the losses the report
uncovered: value list details inline in the catalog (FileMaker 26), two scripts or
layouts with one name, the CustomMenuSetCatalog name, validation by calculation
(<Calculated>), lookups, graph notes and layout parts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from fm_saxml.analyze.coverage import MEASURES, build_coverage
from fm_saxml.cli import _run_pipeline, app
from fm_saxml.model.step_text import step_text
from fm_saxml.parser.coverage import MEASURE_XPATHS, _FUNCS, xml_inventory
from fm_saxml.parser.extractors.fields import _parse_field
from fm_saxml.parser.extractors.value_lists import extract_value_lists

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
MULTI = ROOT / "samples" / "multi_file_export"
runner = CliRunner()


def test_every_measure_is_counted_on_both_sides():
    assert {m.key for m in MEASURES} == set(MEASURE_XPATHS) | set(_FUNCS)


@pytest.mark.parametrize("path", [
    ROOT / "EverythingBagel.xml",
    MULTI / "SaXML_no_separate_catalogue" / "FileA.xml",
    MULTI / "SaXML_no_separate_catalogue" / "FileB.xml",
    MULTI / "SaXML_separate_catalogue" / "FileA",
], ids=lambda p: p.name)
def test_sample_exports_have_complete_coverage(path):
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    report = build_coverage(_run_pipeline(path))
    assert report.available
    assert [(r.label, r.in_xml, r.in_docs) for r in report.problems] == []
    assert report.unrecognised == {}


def test_unrecognised_xml_is_reported(tmp_path):
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace('<Field id="1" name="ContactID"', '<Field newOption="x" id="1" name="ContactID"', 1)
    assert "newOption" in xml
    xml = xml.replace("</Relationship>", "<FutureThing/></Relationship>", 1)
    root = etree.fromstring(xml.encode())
    unrecognised = xml_inventory(root)["unrecognised"]
    assert unrecognised["Field"] == {"@newOption": 1}
    assert unrecognised["Relationship"] == {"FutureThing": 1}


def test_coverage_report_page_and_ci_flag(tmp_path):
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8").replace(
        "</Relationship>", "<FutureThing/></Relationship>", 1)
    src = tmp_path / "Export.xml"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "docs"
    assert runner.invoke(app, ["build", str(src), "-o", str(out), "-f"]).exit_code == 0
    page = (out / "Reports" / "coverage.md").read_text(encoding="utf-8")
    assert "## Unrecognised XML" in page and "`FutureThing`" in page
    assert "See [Coverage](Reports/coverage.md)" in (out / "index.md").read_text(encoding="utf-8")
    result = runner.invoke(app, ["build", str(src), "-o", str(out), "-f", "--fail-on-coverage-gap"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# What the report found
# ---------------------------------------------------------------------------

def test_value_list_details_inline_in_the_catalog():
    container = etree.fromstring("""
    <AddAction><ValueListCatalog>
      <ValueList id="2" name="Choices"><Source value="Custom"/><CustomValues><Text>A&#13;B</Text></CustomValues></ValueList>
      <ValueList id="3" name="Codes"><Source value="FromField"/><Field>
        <PrimaryField show="True" sort="True"><FieldReference id="9" name="code"><TableOccurrenceReference id="5" name="T"/></FieldReference></PrimaryField>
      </Field></ValueList>
    </ValueListCatalog></AddAction>""")
    vls = {v["name"]: v for v in extract_value_lists(container)}
    assert vls["Choices"]["values"] == ["A", "B"]
    assert vls["Codes"]["source_field"]["name"] == "code"


SCRIPT = '<Script id="{id}" name="Same"><Options hidden="False" runwithfullaccess="False"/></Script>'
STEPS = ('<Script><ScriptReference id="{id}" name="Same"/><ObjectList>'
         '<Step index="0" id="93" name="Beep" enable="True"><ParameterValues/></Step>'
         '<Step index="1" id="93" name="Beep" enable="True"><ParameterValues/></Step></ObjectList></Script>')


def _two_scripts_one_name(tmp_path: Path) -> Path:
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace("</ScriptCatalog>", SCRIPT.format(id=7) + SCRIPT.format(id=8) + "</ScriptCatalog>")
    xml = xml.replace("</StepsForScripts>", STEPS.format(id=7) + STEPS.format(id=8) + "</StepsForScripts>")
    path = tmp_path / "Export.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_two_scripts_with_one_name_are_both_kept(tmp_path):
    model = _run_pipeline(_two_scripts_one_name(tmp_path))
    same = [s for s in model.entities.scripts.values() if s.name == "Same"]
    assert len(same) == 2 and len({s.doc_id for s in same}) == 2
    assert all(len(s.steps) == 2 for s in same)
    assert not build_coverage(model).problems


def test_custom_menu_sets_use_filemakers_catalog_name(tmp_path):
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace("CustomMenuSetsCatalog", "CustomMenuSetCatalog")
    path = tmp_path / "Export.xml"
    path.write_text(xml, encoding="utf-8")
    model = _run_pipeline(path)
    assert model.entities.custom_menu_sets


def test_validation_by_calculation_lookups_and_max_size():
    field = _parse_field(etree.fromstring("""
    <Field id="1" name="sent" fieldtype="Normal" datatype="Date">
      <AutoEnter type="Looked_up" prohibitModification="False">
        <Looked_up dontCopyIfEmpty="True" noMatchCopyOption="DoNotCopy" enable="True">
          <FieldReference id="4" name="Zip"><TableOccurrenceReference id="2" name="CLIENTS"/></FieldReference>
          <Context><TableOccurrenceReference id="1" name="Invoices"/></Context>
        </Looked_up>
      </AutoEnter>
      <Validation alwaysValidate="False" type="OnlyDuringDataEntry" allowOverride="False" notEmpty="False" unique="False" existing="False">
        <Calculated enable="True"><Calculation><Text><![CDATA[IsEmpty ( sent )]]></Text></Calculation></Calculated>
        <MaximumSize>10</MaximumSize>
      </Validation>
    </Field>"""), "1", "Invoices")
    v = field["validation"]
    assert v["has_calculation"] and v["max_characters"] == 10 and v["always_validate"] is False
    assert any(c["role"] == "validation" and "IsEmpty" in c["text"] for c in field["calculations"])
    lookup = field["auto_enter"]["lookup"]
    assert (lookup["table_name"], lookup["field_name"], lookup["context"]) == ("CLIENTS", "Zip", "Invoices")


def test_filemaker_text_gets_the_parameters_it_leaves_out():
    step = {"name": "Go to Related Record", "enabled": True,
            "fm_text": "Go to Related Record [ From table: \"T\" ] [ New window ]",
            "params": [{"kind": "calc", "label": "Name", "calc": 0}],
            "calculations": [{"text": "$TASK_NAME"}]}
    assert step_text(step).endswith("{ also: Name: $TASK_NAME }")
    step["calculations"] = [{"text": "Get ( CurrentTimeStamp )"}]
    step["fm_text"] = "Set Variable [ $t; Value:Get ( CurrentTimestamp ) ]"  # FileMaker fixes the case
    assert "also" not in step_text(step)
