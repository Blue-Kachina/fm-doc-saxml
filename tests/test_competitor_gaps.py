"""Gaps found by comparing our output with fm-xml-export-exploder on a real solution.

Each test pins one thing an AI agent reading the docs needs and that used to be lost
or wrong: grouped-button actions, File Options (OnFirstWindowOpen), script options,
per-side relationship options, value list sources, privilege set access, field
options, portal setup, FileMaker's own step text, and a scrubber false positive on
wrapped base64 image data.
"""

from __future__ import annotations

import base64
import textwrap
from pathlib import Path

from lxml import etree
from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.model.step_text import step_text
from fm_saxml.parser.extractors.fields import _parse_field
from fm_saxml.parser.extractors.layouts import _parse_layout_object
from fm_saxml.parser.extractors.privileges import extract_privilege_sets
from fm_saxml.parser.extractors.relationships import _parse_relationship
from fm_saxml.parser.extractors.value_lists import extract_value_lists, split_custom_values
from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.scrub.engine import Scrubber
from fm_saxml.scrub.policy import ScrubPolicy

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Grouped buttons
# ---------------------------------------------------------------------------

GROUPED_BUTTON = """
<LayoutObject id="67" type="Group Button" name="" kind="22">
  <GroupedButton>
    <action>
      <ScriptReference id="5" name="Go Next" UUID="u5"/>
    </action>
    <ObjectList membercount="1">
      <LayoutObject id="68" type="Button" name="" kind="10">
        <Button><Options>0</Options></Button>
      </LayoutObject>
    </ObjectList>
  </GroupedButton>
</LayoutObject>"""


def test_grouped_button_action_is_extracted():
    obj = _parse_layout_object(etree.fromstring(GROUPED_BUTTON), "Body", 0)
    assert obj["button_script"]["name"] == "Go Next"


def test_grouped_button_single_step_keeps_its_full_text():
    lo = etree.fromstring("""
    <LayoutObject id="1" type="Group Button" name="" kind="22">
      <GroupedButton><action>
        <Step index="0" id="6" name="Go to Layout" enable="True">
          <ParameterValues>
            <Parameter type="LayoutReferenceContainer">
              <LayoutReferenceContainer value="1"><LayoutReference id="2" name="Invoices"/></LayoutReferenceContainer>
            </Parameter>
          </ParameterValues>
        </Step>
      </action></GroupedButton>
    </LayoutObject>""")
    obj = _parse_layout_object(lo, "Body", 0)
    assert step_text(obj["button_step"]).startswith('Go to Layout [ "Invoices"')


def test_children_of_a_grouped_button_do_not_inherit_its_action():
    obj = _parse_layout_object(etree.fromstring(GROUPED_BUTTON).find(".//ObjectList/LayoutObject"), "Body", 0)
    assert obj["button_script"] is None


# ---------------------------------------------------------------------------
# Relationships: options per side, operators
# ---------------------------------------------------------------------------

RELATIONSHIP = """
<Relationship id="28">
  <LeftTable cascadeCreate="False" cascadeDelete="True" type="Local">
    <TableOccurrenceReference id="1" name="Invoice"/>
  </LeftTable>
  <RightTable cascadeCreate="True" cascadeDelete="False" type="Local">
    <TableOccurrenceReference id="2" name="invoice__LINES"/>
    <SortSpecification value="True" maintain="True">
      <SortList membercount="2">
        <Sort type="Custom">
          <PrimaryField><FieldReference id="15" name="status"><TableOccurrenceReference id="2" name="invoice__LINES"/></FieldReference></PrimaryField>
          <ValueListReference id="23" name="Statuses"/>
        </Sort>
        <Sort type="Descending">
          <PrimaryField><FieldReference id="7" name="created"><TableOccurrenceReference id="2" name="invoice__LINES"/></FieldReference></PrimaryField>
        </Sort>
      </SortList>
    </SortSpecification>
  </RightTable>
  <JoinPredicateList membercount="1">
    <JoinPredicate type="GreaterOrEqual">
      <LeftField><FieldReference id="1" name="id"><TableOccurrenceReference id="1" name="Invoice"/></FieldReference></LeftField>
      <RightField><FieldReference id="2" name="invoiceId"><TableOccurrenceReference id="2" name="invoice__LINES"/></FieldReference></RightField>
    </JoinPredicate>
  </JoinPredicateList>
</Relationship>"""


def test_relationship_options_are_read_per_side():
    rel = _parse_relationship(etree.fromstring(RELATIONSHIP))
    assert rel["left"]["delete"] is True and rel["left"]["allow_create"] is False
    assert rel["right"]["allow_create"] is True and rel["right"]["delete"] is False
    assert [(s["field_name"], s["order"], s["value_list"]) for s in rel["right"]["sort"]] == [
        ("status", "Custom", "Statuses"), ("created", "Descending", None)]
    assert rel["left"]["sort"] == []
    assert rel["allow_create_related"] and rel["delete_related"] and rel["sort_related"]


def test_relationship_operator_names_become_symbols():
    rel = _parse_relationship(etree.fromstring(RELATIONSHIP))
    assert rel["predicates"][0]["operator"] == "≥"


# ---------------------------------------------------------------------------
# Value lists
# ---------------------------------------------------------------------------

VALUE_LISTS = """
<AddAction>
  <ValueListCatalog>
    <ValueList id="1" name="Remote"><Source value="External"/></ValueList>
    <ValueList id="2" name="Filtered"><Source value="FromField"/></ValueList>
    <ValueList id="3" name="Custom"><Source value="Custom"/></ValueList>
  </ValueListCatalog>
  <OptionsForValueLists>
    <ValueList>
      <ValueListReference id="1" name="Remote"/>
      <Source value="External"/>
      <External>
        <DataSourceReference id="3" name="idiClients" UUID="ds-uuid"><UniversalPathList>file:idiClients</UniversalPathList></DataSourceReference>
        <ValueListReference id="83" name="ChargeCompte_list" UUID="vl-uuid"/>
      </External>
    </ValueList>
    <ValueList>
      <ValueListReference id="2" name="Filtered"/>
      <Source value="FromField"/>
      <Field>
        <PrimaryField show="False" sort="False">
          <FieldReference id="9" name="code"><TableOccurrenceReference id="5" name="globals__LINE"/></FieldReference>
        </PrimaryField>
        <SecondaryField show="True" sort="True">
          <FieldReference id="10" name="description"><TableOccurrenceReference id="5" name="globals__LINE"/></FieldReference>
        </SecondaryField>
        <ShowRelated value="True"><TableOccurrenceReference id="6" name="GLOBALS"/></ShowRelated>
      </Field>
    </ValueList>
    <ValueList>
      <ValueListReference id="3" name="Custom"/>
      <Source value="Custom"/>
      <CustomValues><Text>  Yes&#13;No&#13;&#13;-&#13;Maybe  </Text></CustomValues>
    </ValueList>
  </OptionsForValueLists>
</AddAction>"""


def _value_lists() -> dict[str, dict]:
    container = etree.fromstring(VALUE_LISTS)
    return {vl["name"]: vl for vl in extract_value_lists(container, container.find("OptionsForValueLists"))}


def test_external_value_list_names_its_file_and_list():
    vl = _value_lists()["Remote"]
    assert vl["list_type"] == "external"
    assert vl["external"]["data_source"] == "idiClients"
    assert vl["external"]["name"] == "ChargeCompte_list"


def test_field_value_list_keeps_related_only_and_show_sort_flags():
    vl = _value_lists()["Filtered"]
    assert vl["related_from"] == "GLOBALS"
    assert vl["source_field"]["table"] == "globals__LINE"
    assert vl["source_field"]["show"] is False
    assert vl["second_field"]["sort"] is True


def test_custom_values_are_kept_exactly_as_typed():
    assert _value_lists()["Custom"]["values"] == ["  Yes", "No", "", "-", "Maybe  "]
    assert split_custom_values("a\r\nb\n") == ["a", "b"]


# ---------------------------------------------------------------------------
# Privilege sets
# ---------------------------------------------------------------------------

PRIVILEGES = """
<AddAction>
  <PrivilegeSetsCatalog>
    <ObjectList>
      <PrivilegeSet id="4" name="Sales">
        <Description></Description>
        <access>
          <Records Custom="True">
            <Custom><ObjectList>
              <Table type="existing">
                <BaseTableReference id="129" name="Invoice"/>
                <View access="ReadWrite"/><Edit access="Limited"><Calculation><Text><![CDATA[Owner = Get ( AccountName )]]></Text></Calculation></Edit>
                <Create access="ReadWrite"/><Delete access="NoAccess"/><Fields access="ReadWrite"/>
              </Table>
              <Table type="New">
                <View access="ReadWrite"/><Edit access="ReadWrite"/><Create access="ReadWrite"/>
                <Delete access="NoAccess"/><Fields access="ReadWrite"/>
              </Table>
            </ObjectList></Custom>
          </Records>
          <Layouts View="ReadOnly"/>
          <ValueLists View="ReadOnly"/>
          <Scripts Create="False" Edit="False" Delete="False"/>
          <Other Print="True" Export="False" disconnectIdle="True" commands="Editing">
            <Password prohibitModification="True"/>
          </Other>
        </access>
      </PrivilegeSet>
    </ObjectList>
  </PrivilegeSetsCatalog>
</AddAction>"""


def test_privilege_set_access_is_extracted():
    ps = extract_privilege_sets(etree.fromstring(PRIVILEGES))[0]
    access = ps["access"]
    rows = access["records"]["custom"]
    assert rows[0]["name"] == "Invoice" and rows[0]["access"]["Delete"] == "NoAccess"
    assert rows[0]["calculations"] == [{"column": "Edit", "calculation": "Owner = Get ( AccountName )"}]
    assert rows[1]["type"] == "New"
    assert access["layouts"]["settings"] == {"View": "ReadOnly"}
    assert access["other"]["Export"] == "False" and access["other"]["commands"] == "Editing"
    assert access["other"]["passwordChangeProhibited"] == "True"


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def test_validation_message_strict_type_and_override_are_kept():
    field = _parse_field(etree.fromstring("""
    <Field id="1" name="Code" fieldtype="Normal" datatype="Number">
      <Validation type="Always" allowOverride="False" notEmpty="False" unique="False" existing="False">
        <Strict>Numeric</Strict>
        <Message>Codes must be numeric.</Message>
      </Validation>
    </Field>"""), "1", "T")
    v = field["validation"]
    assert v["message"] == "Codes must be numeric."
    assert v["strict_type"] == "Numeric"
    assert v["validate"] == "Always" and v["allow_override"] is False


def test_validation_by_calculation_alone_is_not_reported_as_none():
    field = _parse_field(etree.fromstring("""
    <Field id="1" name="Msg" fieldtype="Normal" datatype="Text">
      <Validation type="OnlyDuringDataEntry" allowOverride="True" notEmpty="False" unique="False" existing="False">
        <Calculation><Text><![CDATA[WordCount ( Self ) <= 200]]></Text></Calculation>
      </Validation>
    </Field>"""), "1", "T")
    assert field["validation"]["has_calculation"] is True
    assert any(c["role"] == "validation" for c in field["calculations"])


def test_default_validation_element_is_no_rule():
    field = _parse_field(etree.fromstring("""
    <Field id="1" name="x" fieldtype="Normal" datatype="Text">
      <Validation type="OnlyDuringDataEntry" allowOverride="True" notEmpty="False" unique="False" existing="False"/>
    </Field>"""), "1", "T")
    assert field["validation"] is None


def test_summary_operation_and_source_are_read_from_summary_info():
    field = _parse_field(etree.fromstring("""
    <Field id="91" name="total" fieldtype="Summary" datatype="Number">
      <SummaryInfo restartEachGroup="True" summarizeRepetition="Together" operation="Total">
        <SummaryField><FieldReference id="25" name="amount"><BaseTableReference id="129" name="Invoice"/></FieldReference></SummaryField>
      </SummaryInfo>
    </Field>"""), "129", "Invoice")
    assert field["summary_field"] == {"name": "amount", "table": "Invoice"}
    assert field["summary"]["operation"] == "Total"
    assert field["summary"]["restart_each_group"] is True


def test_unstored_calculation_and_auto_enter_flags():
    calc = _parse_field(etree.fromstring("""
    <Field id="17" name="c" fieldtype="Calculated" datatype="Date">
      <AutoEnter alwaysEvaluate="True"/>
      <Storage storeCalculationResults="False" global="False" maxRepetitions="1"/>
    </Field>"""), "1", "T")
    assert calc["storage"]["stored"] is False
    assert calc["always_evaluate"] is True
    serial = _parse_field(etree.fromstring("""
    <Field id="1" name="id" fieldtype="Normal" datatype="Number">
      <AutoEnter type="SerialNumber" prohibitModification="True">
        <SerialNumber increment="1" nextvalue="1074" generate="OnCreation"/>
      </AutoEnter>
    </Field>"""), "1", "T")
    ae = serial["auto_enter"]
    assert ae["no_modify_auto_enter"] is True
    assert ae["serial"] == {"increment": "1", "generate": "OnCreation"}


# ---------------------------------------------------------------------------
# Portals
# ---------------------------------------------------------------------------

def test_portal_rows_and_sort_order():
    obj = _parse_layout_object(etree.fromstring("""
    <LayoutObject id="40" type="Portal" name="" kind="5">
      <Portal>
        <TableOccurrenceReference id="2" name="invoice__LINES"/>
        <Options index="1" show="3">281</Options>
        <SortSpecification value="True" maintain="True">
          <SortList membercount="1">
            <Sort type="Descending">
              <PrimaryField><FieldReference id="7" name="created"><TableOccurrenceReference id="2" name="invoice__LINES"/></FieldReference></PrimaryField>
            </Sort>
          </SortList>
        </SortSpecification>
      </Portal>
    </LayoutObject>"""), "Body", 0)
    portal = obj["portal"]
    assert portal["rows"] == "3" and portal["initial_row"] == "1"
    assert [(s["field_name"], s["order"]) for s in portal["sort"]] == [("created", "Descending")]


# ---------------------------------------------------------------------------
# Scrubbing: wrapped base64 image data is not a password
# ---------------------------------------------------------------------------

SVG = ('<?xml version="1.0" encoding="UTF-8" standalone="no"?><svg width="10px" height="10px" '
       'viewBox="0 0 10 10" version="1.1" xmlns="http://www.w3.org/2000/svg" '
       'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:sketch="http://www.bohemiancoding.com/sketch/ns">'
       '<g class="fm_fill"><title>16</title><desc>Created with Sketch.</desc></g></svg>')


def test_wrapped_base64_svg_is_not_redacted():
    for width in (64, 76):
        lines = textwrap.wrap(base64.b64encode(SVG.encode()).decode(), width)
        calc = 'Base64Decode ( "' + "¶".join(lines) + '" ; "icon.svg" )'
        assert Scrubber(ScrubPolicy()).scrub_calc(calc, "test") == calc


def test_base64_basic_auth_credential_is_still_redacted():
    token = base64.b64encode(b"admin:S3cr3t!pw").decode()
    calc = '"Authorization: Basic ' + token + '"'
    assert token not in Scrubber(ScrubPolicy()).scrub_calc(calc, "test")


# ---------------------------------------------------------------------------
# End to end: File Options, script options, FileMaker's own step text
# ---------------------------------------------------------------------------

FAKE_KEY = "sk-ant-api03-" + "Q" * 40  # built here: a whole key shape in the source trips secret scanning

METADATA = """
  <Metadata membercount="1">
    <AddAction membercount="5">
      <Minimum version="19.6" value="1906"></Minimum>
      <Login type="-1"></Login>
      <Defaults><LayoutReference id="1" name="ContactDetail"></LayoutReference></Defaults>
      <IconData type="999"><BinaryData><StreamList><Stream name="PNGf" type="Base64">iVBORw0KGgo=</Stream></StreamList></BinaryData></IconData>
      <ScriptTriggers membercount="1">
        <ScriptTrigger id="201" action="OnFirstWindowOpen" browseMode="True">
          <ScriptReference id="1" name="SendEmail"></ScriptReference>
        </ScriptTrigger>
      </ScriptTriggers>
    </AddAction>
  </Metadata>
  <DDR_INFO>
    <Script>
      <ObjectList>
        <_00000000-0000-0000-AAAA-000000000001 hash="H1" datatype="StepText">#Send the email</_00000000-0000-0000-AAAA-000000000001>
        <_00000000-0000-0000-BBBB-000000000001 hash="H2" datatype="StepText">Send Mail [ Send via E-mail Client; With dialog: Off; To: "a@b.c" ]</_00000000-0000-0000-BBBB-000000000001>
        <_00000000-0000-0000-CCCC-000000000001 hash="H3" datatype="StepText">Set Variable [ $password; Value:"swordfish99" &amp; " Bearer {FAKE_KEY}" ]</_00000000-0000-0000-CCCC-000000000001>
      </ObjectList>
    </Script>
  </DDR_INFO>
</FMSaveAsXML>"""

SECRET_STEP = """            <Step hash="CCCC" index="2" id="141" name="Set Variable" enable="True">
              <UUID>00000000-0000-0000-CCCC-000000000001</UUID>
              <DDRREF kind="StepText" hash="H3">_00000000-0000-0000-CCCC-000000000001</DDRREF>
              <ParameterValues membercount="1">
                <Parameter type="Variable">
                  <value><Calculation datatype="1" position="1"><Calculation><Text><![CDATA["swordfish99" & " Bearer {FAKE_KEY}"]]></Text></Calculation></Calculation></value>
                  <Name value="$password"/>
                </Parameter>
              </ParameterValues>
            </Step>
"""


def _export(tmp_path: Path) -> Path:
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace("</FMSaveAsXML>", METADATA.lstrip("\n").replace("{FAKE_KEY}", FAKE_KEY))
    xml = xml.replace('runwithfullaccess="False"', 'runwithfullaccess="True"').replace(
        '<Options hidden="False"', '<Options hidden="True"')
    # Point the fixture's steps at their DDR text, and add a step holding a secret
    for uuid, h in (("00000000-0000-0000-AAAA-000000000001", "H1"), ("00000000-0000-0000-BBBB-000000000001", "H2")):
        xml = xml.replace(f"<UUID>{uuid}</UUID>",
                          f'<UUID>{uuid}</UUID>\n              <DDRREF kind="StepText" hash="{h}">_{uuid}</DDRREF>')
    xml = xml.replace("          </ObjectList>\n        </Script>\n      </StepsForScripts>",
                      SECRET_STEP.replace("{FAKE_KEY}", FAKE_KEY) + "          </ObjectList>\n        </Script>\n      </StepsForScripts>")
    path = tmp_path / "Export.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_file_options_are_parsed(tmp_path):
    fo = parse_savexml(_export(tmp_path)).file_options
    assert fo["default_layout"]["name"] == "ContactDetail"
    assert fo["minimum_version"] == "19.6"
    assert [(t["event"], t["script"]["name"]) for t in fo["script_triggers"]] == [("OnFirstWindowOpen", "SendEmail")]


def _build(tmp_path: Path) -> Path:
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(_export(tmp_path)), "-o", str(out), "-f"])
    assert result.exit_code == 0, result.output
    return out


def test_file_options_on_home_page_and_as_called_by(tmp_path):
    out = _build(tmp_path)
    home = (out / "index.md").read_text(encoding="utf-8")
    assert "## File Options" in home
    assert "| OnFirstWindowOpen | [SendEmail](Scripts/" in home
    assert "| Switch to layout (on open) | [ContactDetail](Layouts/ContactDetail.md) |" in home
    script = next((out / "Scripts").rglob("SendEmail.md")).read_text(encoding="utf-8")
    assert "| [File Options](../index.md) | fileOptions | OnFirstWindowOpen |" in script.replace("../../", "../")


def test_script_options_are_shown(tmp_path):
    script = next((_build(tmp_path) / "Scripts").rglob("SendEmail.md")).read_text(encoding="utf-8")
    assert "| Run with full access privileges | Yes |" in script
    assert "| Include in menu | No |" in script


def test_filemaker_step_text_is_used_and_scrubbed(tmp_path):
    out = _build(tmp_path)
    script = next((out / "Scripts").rglob("SendEmail.md")).read_text(encoding="utf-8")
    assert 'Send Mail [ Send via E-mail Client; With dialog: Off; To: "a@b.c" ]' in script
    assert "Set Variable [ $password; Value:" in script
    everything = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    everything += "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.json"))
    assert "swordfish99" not in everything
    assert "Q" * 40 not in everything
