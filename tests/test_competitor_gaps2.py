"""Gaps found by the second, independent evaluation (v0.5.0 against a real solution).

Each test pins one thing that was missing or misleading: the access level of each
layout, script and value list row of a privilege set and of each field (the rows used
to show names only, so "No access" read like access), a coverage report that counted
rows without checking their level, scrubber false positives on a vendor's
Authorization scheme name and on parameter names such as ``refresh_token=``, an
on/off step missing its state, and data sources with several paths run together.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from fm_saxml.analyze.access import build_access
from fm_saxml.cli import app
from fm_saxml.model.step_text import step_text
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.parser.extractors.external_data_sources import extract_external_data_sources
from fm_saxml.parser.extractors.privileges import extract_privilege_sets
from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.scrub.engine import Scrubber
from fm_saxml.scrub.policy import ScrubPolicy

ROOT = Path(__file__).parent.parent
RESTRICTED_SAMPLE = ROOT / "samples" / "has_restricted_access_to_scripts" / "EverythingBagel.xml"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Privilege sets: per-row levels, field-level access, "allow creation"
# ---------------------------------------------------------------------------

# The shape of a real export (Save a Copy as XML, FileMaker 2024)
PRIVILEGES = """
<AddAction>
  <PrivilegeSetsCatalog>
    <ObjectList>
      <PrivilegeSet id="4" name="Calculated Access">
        <access>
          <Records Custom="True">
            <Custom><ObjectList membercount="1">
              <Table type="existing">
                <BaseTableReference id="129" name="Invoice"/>
                <View access="Calculation"><Calculation><Text><![CDATA[Owner = Get ( AccountName )]]></Text></Calculation></View>
                <Edit access="NoAccess"/><Create access="NoAccess"/><Delete access="NoAccess"/>
                <Fields access="Custom">
                  <Field type="existing" access="ReadWrite"><FieldReference id="6" name="Total"><BaseTableReference id="129" name="Invoice"/></FieldReference></Field>
                  <Field type="existing" access="ReadOnly"><FieldReference id="7" name="Status"><BaseTableReference id="129" name="Invoice"/></FieldReference></Field>
                  <Field type="New" access="NoAccess"/>
                </Fields>
              </Table>
            </ObjectList></Custom>
          </Records>
          <Layouts Custom="True">
            <Custom Create="False"><ObjectList membercount="2">
              <Layout type="existing" access="ReadOnly" records="ReadWrite"><LayoutReference id="1" name="Invoices"/></Layout>
              <Layout type="New" access="NoAccess" records="NoAccess"/>
            </ObjectList></Custom>
          </Layouts>
          <ValueLists Custom="True">
            <Custom Create="True"><ObjectList membercount="2">
              <ValueList type="existing" access="NoAccess"><ValueListReference id="2" name="Statuses"/></ValueList>
              <ValueList type="New" access="ReadWrite"/>
            </ObjectList></Custom>
          </ValueLists>
          <Scripts Custom="True">
            <Custom Create="True"><ObjectList membercount="3">
              <Script type="existing" access="ReadOnly"><ScriptReference id="1" name="Print Invoice"/></Script>
              <Script type="existing" access="NoAccess"><ScriptReference id="2" name="Void Invoice"/></Script>
              <Script type="New" access="ReadWrite"/>
            </ObjectList></Custom>
          </Scripts>
        </access>
      </PrivilegeSet>
    </ObjectList>
  </PrivilegeSetsCatalog>
</AddAction>"""


def _access() -> dict:
    return extract_privilege_sets(etree.fromstring(PRIVILEGES))[0]["access"]


def test_row_level_of_layouts_scripts_and_value_lists_is_kept():
    access = _access()
    layout = access["layouts"]["custom"][0]
    assert layout["name"] == "Invoices"
    assert layout["attributes"] == {"access": "ReadOnly", "records": "ReadWrite"}
    assert [s["attributes"]["access"] for s in access["scripts"]["custom"]] == ["ReadOnly", "NoAccess", "ReadWrite"]
    assert access["value_lists"]["custom"][0]["attributes"]["access"] == "NoAccess"


def test_allow_creation_is_read_from_the_custom_element():
    access = _access()
    assert access["layouts"]["allow_create"] is False
    assert access["scripts"]["allow_create"] is True
    assert access["records"]["allow_create"] is None


def test_field_level_access_is_extracted():
    table = _access()["records"]["custom"][0]
    assert table["access"]["Fields"] == "Custom"
    assert [(f["name"], f["table"], f["access"]) for f in table["field_access"]] == [
        ("Total", "Invoice", "ReadWrite"), ("Status", "Invoice", "ReadOnly"), ("", "", "NoAccess")]
    assert table["field_access"][2]["type"] == "New"
    # The table's own "limited" calc is kept; field entries add none
    assert table["calculations"] == [{"column": "View", "calculation": "Owner = Get ( AccountName )"}]


# ---------------------------------------------------------------------------
# The restricted-access sample, end to end
# ---------------------------------------------------------------------------

needs_sample = pytest.mark.skipif(not RESTRICTED_SAMPLE.exists(), reason="restricted-access sample not present")


@pytest.fixture(scope="module")
def restricted_docs(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("restricted") / "docs"
    result = runner.invoke(app, ["build", str(RESTRICTED_SAMPLE), "-o", str(out), "-f", "-y",
                                 "--disable-scrubbing", "--coverage"])
    assert result.exit_code == 0, result.output
    return out


@needs_sample
def test_privilege_set_page_shows_each_rows_level(restricted_docs):
    page = (restricted_docs / "Privileges" / "Calculated Access.md").read_text(encoding="utf-8")
    assert "| Layout | Layout | Records |" in page
    assert "| [EverythingBagel](../Layouts/EverythingBagel.md) | View only | Modifiable |" in page
    assert "| [Any new layout] | No access | No access |" in page
    assert "| [OneOfEverything](../Scripts/OneOfEverything.md) | Executable only |" in page
    assert "| [ValuesFromField](../ValueLists/ValuesFromField.md) | No access |" in page
    assert "| [Any new value list] | Modifiable |" in page
    assert "Allow creation of new layouts: No" in page
    assert "Allow creation of new scripts: Yes" in page


@needs_sample
def test_privilege_set_page_lists_field_level_access(restricted_docs):
    page = (restricted_docs / "Privileges" / "Calculated Access.md").read_text(encoding="utf-8")
    assert "| Limited | No | No | Limited | Custom (below) |" in page
    assert "#### Field access: [EverythingBagel](../Tables/EverythingBagel.md)" in page
    assert "| [textField](../Fields/EverythingBagel/textField.md) | Modifiable |" in page
    assert "| [numberField](../Fields/EverythingBagel/numberField.md) | View only |" in page
    assert "| [dateField](../Fields/EverythingBagel/dateField.md) | No access |" in page
    assert "| [Any new field] | No access |" in page


@needs_sample
def test_object_pages_show_access_by_privilege_set(restricted_docs):
    script = (restricted_docs / "Scripts" / "OneOfEverything.md").read_text(encoding="utf-8")
    assert "## Access by Privilege Set" in script
    assert "| [Calculated Access](../Privileges/Calculated%20Access.md) | Executable only | Own row |" in script
    layout = (restricted_docs / "Layouts" / "EverythingBagel.md").read_text(encoding="utf-8")
    assert "| View only (records: modifiable) | Own row |" in layout
    field = (restricted_docs / "Fields" / "EverythingBagel" / "dateField.md").read_text(encoding="utf-8")
    assert "| [Calculated Access](../../Privileges/Calculated%20Access.md) | No access | Own entry |" in field


@needs_sample
def test_coverage_checks_privilege_levels(restricted_docs):
    report = (restricted_docs / "Reports" / "coverage.md").read_text(encoding="utf-8")
    for label, n in (("Custom layout privileges (rows with access level)", 2),
                     ("Custom layout privileges (records access level)", 2),
                     ("Custom script privileges (rows with access level)", 2),
                     ("Custom value list privileges (rows with access level)", 3),
                     ("Field-level privileges (fields with access level)", 9)):
        assert f"| {label} | {n} | {n} | complete |" in report


@needs_sample
def test_access_matrix_has_field_levels():
    model = resolve_references(normalize(parse_savexml(RESTRICTED_SAMPLE), "EverythingBagel.xml"))
    fields = build_access(model)["objects"]["field"]
    by_set = {row[0]: row[1:] for row in fields["field:EverythingBagel::numberField"]}
    assert by_set["privilegeSet:Calculated Access"] == ["view", "fieldRow"]
    assert by_set["privilegeSet:[Full Access]"] == ["modifiable", "fullAccess"]
    assert by_set["privilegeSet:[Read-Only Access]"] == ["view", "blanket"]


def test_no_access_table_without_custom_privileges(tmp_path):
    # Built-in sets only: the same table on every page would add nothing
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(ROOT / "tests" / "fixtures" / "v2_sample.xml"), "-o", str(out), "-f"])
    assert result.exit_code == 0, result.output
    assert not any("## Access by Privilege Set" in p.read_text(encoding="utf-8") for p in out.rglob("*.md"))


# ---------------------------------------------------------------------------
# Scrubber false positives
# ---------------------------------------------------------------------------

# Known-safe code: none of it may change, at any level.
NOT_SECRETS = [
    '"Authorization: DeepL-Auth-Key " & $key',
    '" -H \\"Authorization: DeepL-Auth-Key " & $apiKey & "\\""',
    'token = "refresh_token=" & $refreshToken',
    'Let ( [ token = "refresh_token=" ] ; token )',
    '$$refreshToken = "refresh_token="',
    '# token: "refresh_token="',
    'JSONSetElement ( "{}" ; "token" ; "refresh_token=" ; JSONString )',
    '"grant_type=refresh_token&refresh_token=" & $refreshToken',
    '$secretName = "client_secret"',
]

# Real secrets next to the same names: all must still be redacted.
SECRETS = [
    ('"Authorization: DeepL-Auth-Key 3f9a8b7c-1d2e-4f5a-9b8c-7d6e5f4a3b2c:fx"', "3f9a8b7c-1d2e-4f5a-9b8c-7d6e5f4a3b2c:fx"),
    ('"Authorization: SSWS 00aBcDeFgHiJkLmNoP123"', "00aBcDeFgHiJkLmNoP123"),
    ('"Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"', "eyJhbGciOiJIUzI1NiJ9.abc.def"),
    ('"?refresh_token=1//0gAbCdEf123"', "1//0gAbCdEf123"),
    ('$password = "password"', '"password"'),
    ('MBS ( "CURL.SetOptionPassword" ; $curl ; "sftpPass" )', "sftpPass"),
]


@pytest.mark.parametrize("level", ["secrets", "standard", "strict"])
@pytest.mark.parametrize("source", NOT_SECRETS)
def test_names_and_schemes_are_not_redacted(source, level):
    assert Scrubber(ScrubPolicy(level=level)).scrub_calc(source, "test") == source


@pytest.mark.parametrize("source,secret", SECRETS)
def test_secrets_beside_those_names_are_still_redacted(source, secret):
    out = Scrubber(ScrubPolicy()).scrub_calc(source, "test")
    assert secret not in out and "[REDACTED:" in out


def test_parameter_name_rule():
    policy = ScrubPolicy()
    for name in ("refresh_token", "refresh_token=", "&access-token=", "client_secret", "apiKey", "auth.token"):
        assert policy.is_parameter_name(name), name
    for value in ("password", "Sw0rdf1sh!", "sk_live_51HxYzAbCdEf", "grant_type", "hello_world"):
        assert not policy.is_parameter_name(value), value


# ---------------------------------------------------------------------------
# Small rendering gaps
# ---------------------------------------------------------------------------

def test_on_off_step_keeps_its_state_when_filemakers_text_leaves_it_out():
    step = {"name": "Allow User Abort", "enabled": True, "fm_text": "Allow User Abort",
            "params": [{"kind": "option", "label": None, "value": "Off"}]}
    assert step_text(step) == "Allow User Abort [ Off ]"
    step["fm_text"] = "Allow User Abort [ Off ]"
    assert step_text(step) == "Allow User Abort [ Off ]"


@pytest.mark.parametrize("path_list,expected", [
    ("<UniversalPathList>file:disRecrutement\rfile:idiRecrutement</UniversalPathList>",
     ["file:disRecrutement", "file:idiRecrutement"]),
    ('<UniversalPathList membercount="2"><ObjectList><Location><![CDATA[$file]]></Location>'
     "<Location>file:Backup</Location></ObjectList></UniversalPathList>", ["$file", "file:Backup"]),
    ("<UniversalPathList>file:idiClients</UniversalPathList>", ["file:idiClients"]),
])
def test_data_source_paths_are_split(path_list, expected):
    xml = (f'<AddAction><ExternalDataSourceCatalog><ExternalDataSource id="1" name="Other" type="FileMaker">'
           f"{path_list}</ExternalDataSource></ExternalDataSourceCatalog></AddAction>")
    assert extract_external_data_sources(etree.fromstring(xml))[0]["paths"] == expected


def test_script_without_callers_says_why_that_is_not_proof(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(ROOT / "tests" / "fixtures" / "v2_sample.xml"), "-o", str(out), "-f"])
    assert result.exit_code == 0, result.output
    pages = [p.read_text(encoding="utf-8") for p in (out / "Scripts").rglob("*.md") if p.name != "index.md"]
    uncalled = [p for p in pages if "No callers found in this export" in p]
    assert uncalled and all("server schedule" in p for p in uncalled)


def test_home_page_says_whether_output_was_scrubbed(tmp_path):
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(ROOT / "tests" / "fixtures" / "v2_sample.xml"), "-o", str(out), "-f",
                                 "--disable-scrubbing", "-y"])
    assert result.exit_code == 0, result.output
    home = (out / "index.md").read_text(encoding="utf-8")
    assert "**Not scrubbed.**" in home and "## Reading These Docs" in home
