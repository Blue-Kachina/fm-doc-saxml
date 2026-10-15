"""Indirection: names of fields, scripts, layouts ... written in strings (handling_indirection.md).

A synthetic solution with one example of each shape found in real exports: hardcoded
``"TO::field"`` names, a field name captured with GetFieldName and passed through a script
trigger parameter into Set Field By Name, the callback convention (``"callbackScriptName" ;
Get ( ScriptName )``), SQL with and without helper functions, ID-based custom functions,
layout name patterns, names that only exist in data, a broken name, and lookalike literals
that must not be reported.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.analyze.warnings import generate_warnings
from fm_saxml.cli import app
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.parser.saxml_reader import parse_savexml

runner = CliRunner()


def _cdata(text: str) -> str:
    return f"<![CDATA[{text}]]>"


def _calc(text: str, position: int = 0) -> str:
    return f'<Calculation position="{position}"><Calculation><Text>{_cdata(text)}</Text></Calculation></Calculation>'


def _entity_calc(text: str) -> str:
    return f"<Calculation><Text>{_cdata(text)}</Text></Calculation>"


def _fref(id_, name, to_id, to):
    return f'<FieldReference id="{id_}" name="{name}" repetition="1"><TableOccurrenceReference id="{to_id}" name="{to}"/></FieldReference>'


def _to(id_, name, table_id, table):
    return (f'<TableOccurrence id="{id_}" name="{name}" type="Local"><BaseTableSourceReference type="BaseTableReference">'
            f'<BaseTableReference id="{table_id}" name="{table}"/></BaseTableSourceReference></TableOccurrence>')


def set_var(i, var, text, enable=True):
    return (f'<Step index="{i}" id="141" name="Set Variable" enable="{enable}"><ParameterValues><Parameter type="Variable">'
            f'<value>{_calc(text, 1)}</value><Name value="{var}"/><repetition>{_calc("1", 2)}</repetition>'
            f'</Parameter></ParameterValues></Step>')


def set_field_by_name(i, target, value):
    return (f'<Step index="{i}" id="147" name="Set Field By Name" enable="True"><ParameterValues>'
            f'<Parameter type="Boolean"><Boolean type="Specify target field" id="134217728" value="True"/></Parameter>'
            f'<Parameter type="Calculation">{_calc(target, 1)}</Parameter>'
            f'<Parameter type="Calculation">{_calc(value, 0)}</Parameter></ParameterValues></Step>')


def perform_script(i, script_id, script_name, param=None, server=False):
    name = "Perform Script on Server" if server else "Perform Script"
    p = f'<Parameter type="Parameter"><Parameter>{_calc(param, 0)}</Parameter></Parameter>' if param else ""
    return (f'<Step index="{i}" id="1" name="{name}" enable="True"><ParameterValues><Parameter type="List">'
            f'<List name="From list" value="1"><ScriptReference id="{script_id}" name="{script_name}"/></List></Parameter>'
            f'{p}</ParameterValues></Step>')


def perform_script_by_name(i, text, server=False):
    name = "Perform Script on Server" if server else "Perform Script"
    return (f'<Step index="{i}" id="1" name="{name}" enable="True"><ParameterValues><Parameter type="List">'
            f'<List name="By name" value="2">{_calc(text, 2)}</List></Parameter></ParameterValues></Step>')


def go_to_layout_calc(i, text, value="3"):
    return (f'<Step index="{i}" id="6" name="Go to Layout" enable="True"><ParameterValues>'
            f'<Parameter type="LayoutReferenceContainer"><LayoutReferenceContainer value="{value}">{_calc(text, 5)}'
            f'</LayoutReferenceContainer></Parameter></ParameterValues></Step>')


def go_to_object(i, text):
    return (f'<Step index="{i}" id="145" name="Go to Object" enable="True"><ParameterValues><Parameter type="Object">'
            f'<Name>{_calc(text, 0)}</Name><repetition>{_calc("1", 1)}</repetition></Parameter></ParameterValues></Step>')


def if_step(i, text):
    return (f'<Step index="{i}" id="68" name="If" enable="True"><ParameterValues>'
            f'<Parameter type="Calculation">{_calc(text, 0)}</Parameter></ParameterValues></Step>')


SCRIPTS = {
    1: ("Hardcoded", [
        set_var(0, "$x", 'GetField ( "INV::total" )'),
        set_field_by_name(1, '"Contact::email"', "1"),
        set_var(2, "$v", 'ValueListItems ( Get ( FileName ) ; "Statuses" )'),
        if_step(3, 'Get ( LayoutName ) = "Invoice Detail"'),
        go_to_object(4, '"btnSave"'),
        set_var(5, "$s", 'ExecuteSQL ( "SELECT \\"total\\" FROM INV WHERE id = ?" ; "" ; "" ; 1 )'),
        set_var(6, "$m", 'GetField ( "INV::missing" )'),
        set_var(7, "$e", 'Evaluate ( "INV::status & \\"!\\"" )'),
        set_var(8, "$lookalike", 'If ( $x = "Yes" ; "Find" ; "Statuses" )'),  # not a sink: no site
        set_var(9, "$w", 'ReadField ( "INV::status" )'),
        set_var(10, "$old", 'GetField ( "INV::total" )', enable=False),
    ]),
    2: ("Safe", [
        set_var(0, "$f", "GetFieldName ( INV::note )"),
        set_var(1, "$val", "GetField ( $f )"),
        perform_script_by_name(2, "Get ( ScriptName )", server=True),
        set_var(3, "$q", 'ExecuteSQL ( "SELECT " & SQLField ( INV::total ) & " FROM " & SQLTable ( INV::id ) ; "" ; "" )'),
        set_var(4, "$sys", 'ExecuteSQL ( "SELECT FieldName FROM FileMaker_Fields WHERE TableName=?" ; "" ; "" ; "INV" )'),
        perform_script_by_name(5, "getScriptName ( 6 )"),
        set_var(6, "$t", 'Substitute ( "SELECT ~f FROM ~t" ; [ "~f" ; SQLField ( INV::total ) ] ; [ "~t" ; SQLTable ( INV::id ) ] )'),
        set_var(7, "$r", 'ExecuteSQL ( $t ; "" ; "" )'),
    ]),
    3: ("Copy Into Target", [
        set_var(0, "$p", "Get ( ScriptParameter )"),
        set_var(1, "$target", 'JSONGetElement ( $p ; "targetField" )'),
        set_field_by_name(2, "$target", '"x"'),
    ]),
    4: ("Process", [
        set_var(0, "$p", "Get ( ScriptParameter )"),
        set_var(1, "$cb", 'JSONGetElement ( $p ; "callbackScriptName" )'),
        perform_script_by_name(2, "$cb"),
    ]),
    5: ("Caller", [
        perform_script(0, 4, "Process", 'JSONSetElement ( "" ; [ "callbackScriptName" ; Get ( ScriptName ) ; JSONString ] )'),
        perform_script(1, 7, "Mapper", 'JSONSetElement ( "{}" ; [ "field" ; "Contact::email" ; JSONString ] )'),
    ]),
    6: ("Dynamic", [
        set_var(0, "$type", "INV::status"),
        go_to_layout_calc(1, '$type & " tabs"'),
        set_var(2, "$name", '"Report A tabs"'),
        go_to_layout_calc(3, "$name"),
        go_to_layout_calc(4, "$n", value="4"),  # by number: a reorder risk, not a name
        set_field_by_name(5, 'Get ( LayoutTableName ) & "::" & INV::note', "1"),
        set_var(6, "$opaque", "GetField ( INV::note )"),
    ]),
    7: ("Mapper", [
        set_field_by_name(0, 'JSONGetElement ( Get ( ScriptParameter ) ; "field" )', "1"),
    ]),
}

CUSTOM_FUNCTIONS = {
    1: ("SQLField", ["field"], 'Let ( [ q = "\\"" ; fn = GetFieldName ( field ) ] ; q & Substitute ( fn ; "::" ; q & "." & q ) & q )'),
    2: ("SQLTable", ["field"], 'Let ( fn = GetFieldName ( field ) ; Quote ( GetValue ( Substitute ( fn ; "::" ; ¶ ) ; 1 ) ) )'),
    3: ("getScriptName", ["scriptID"], "GetValue ( ScriptNames ( Get ( FileName ) ) ; ValueCount ( Left ( ScriptIDs ( Get ( FileName ) ) ; Position ( ScriptIDs ( Get ( FileName ) ) ; scriptID ; 1 ; 1 ) ) ) )"),
    4: ("ReadField", ["name"], "GetField ( name )"),
}


def _steps_xml() -> str:
    out = []
    for sid, (name, steps) in SCRIPTS.items():
        out.append(f'<Script><ScriptReference id="{sid}" name="{name}"/><ObjectList>{"".join(steps)}</ObjectList></Script>')
    return "".join(out)


TRIGGER_PARAM = 'JSONSetElement ( "{}" ; [ "targetField" ; GetFieldName ( INV::note ) ; JSONString ] )'

XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<FMSaveAsXML version="2.2.3.0" Source="22.0.6" File="Ind.fmp12" UUID="F">
<Structure><AddAction>
  <BaseTableCatalog><BaseTable id="1" name="Invoice"/><BaseTable id="2" name="Contact"/></BaseTableCatalog>
  <TableOccurrenceCatalog>{_to(100, "INV", 1, "Invoice")}{_to(200, "Contact", 2, "Contact")}</TableOccurrenceCatalog>
  <CustomFunctionsCatalog><ObjectList>{"".join(
      f'<CustomFunction id="{i}" name="{n}"><ObjectList>{"".join(f'<Parameter name="{p}"/>' for p in ps)}</ObjectList></CustomFunction>'
      for i, (n, ps, _b) in CUSTOM_FUNCTIONS.items())}</ObjectList></CustomFunctionsCatalog>
  <ValueListCatalog><ValueList id="1" name="Statuses"><Source value="Custom"/></ValueList></ValueListCatalog>
  <FieldsForTables>
    <FieldCatalog><BaseTableReference id="1" name="Invoice"/><ObjectList>
      <Field id="1" name="id" fieldtype="Normal" datatype="Number"/>
      <Field id="2" name="total" fieldtype="Normal" datatype="Number"/>
      <Field id="3" name="status" fieldtype="Normal" datatype="Text"/>
      <Field id="4" name="note" fieldtype="Normal" datatype="Text"/>
      <Field id="5" name="label" fieldtype="Calculated" datatype="Text">{_entity_calc('GetField ( "INV::status" )')}</Field>
    </ObjectList></FieldCatalog>
    <FieldCatalog><BaseTableReference id="2" name="Contact"/><ObjectList>
      <Field id="1" name="email" fieldtype="Normal" datatype="Text"/>
    </ObjectList></FieldCatalog>
  </FieldsForTables>
  <CalcsForCustomFunctions><ObjectList>{"".join(
      f'<CustomFunctionCalc><CustomFunctionReference id="{i}" name="{n}"/>{_entity_calc(b)}</CustomFunctionCalc>'
      for i, (n, _ps, b) in CUSTOM_FUNCTIONS.items())}</ObjectList></CalcsForCustomFunctions>
  <ScriptCatalog>{"".join(f'<Script id="{sid}" name="{name}"/>' for sid, (name, _s) in SCRIPTS.items())}</ScriptCatalog>
  <StepsForScripts>{_steps_xml()}</StepsForScripts>
  <LayoutCatalog>
    <Layout id="1" name="Invoice Detail">
      <TableOccurrenceReference id="100" name="INV"/>
      <PartsList><Part type="Body"><ObjectList>
        <LayoutObject id="2" type="Button" name="btnSave"><Button><action><ScriptReference id="1" name="Hardcoded"/></action></Button></LayoutObject>
        <LayoutObject id="3" type="Edit Box" name="uploadTarget"><Field>{_fref(4, "note", 100, "INV")}</Field>
          <ScriptTriggers><ScriptTrigger action="OnObjectModify"><ScriptReference id="3" name="Copy Into Target">{_entity_calc(TRIGGER_PARAM)}</ScriptReference></ScriptTrigger></ScriptTriggers>
        </LayoutObject>
      </ObjectList></Part></PartsList>
    </Layout>
    <Layout id="2" name="Report A tabs"><TableOccurrenceReference id="100" name="INV"/></Layout>
    <Layout id="3" name="Report B tabs"><TableOccurrenceReference id="100" name="INV"/></Layout>
  </LayoutCatalog>
</AddAction></Structure>
</FMSaveAsXML>"""


@pytest.fixture(scope="module")
def xml_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("ind") / "Ind.xml"
    path.write_text(XML, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def model(xml_path):
    m = resolve_references(normalize(parse_savexml(xml_path), "Ind.xml"))
    return generate_warnings(generate_backlinks(m))


def _sites(model, script=None, sink=None):
    out = model.indirection
    if script:
        out = [s for s in out if s.script_doc_id == f"script:{script}"]
    if sink:
        out = [s for s in out if s.sink.startswith(sink)]
    return out


def _step_site(model, script, step):
    hits = [s for s in model.indirection if s.script_doc_id == f"script:{script}" and s.step == step]
    assert hits, f"no site at {script} step {step}: {[(s.step, s.sink) for s in _sites(model, script)]}"
    return hits


def _targets(site):
    return {c.target_doc_id for c in site.candidates}


# ---------------------------------------------------------------------------
# Class B: hardcoded names
# ---------------------------------------------------------------------------

def test_getfield_literal_is_hardcoded(model):
    site, = _step_site(model, "Hardcoded", 1)
    assert (site.sink, site.name_kind, site.klass) == ("GetField", "field", "B")
    assert _targets(site) == {"field:Invoice::total"}
    cand = site.candidates[0]
    assert (cand.origin, cand.confidence, cand.breaks_on_rename) == ("literal", "parsed", True)


def test_set_field_by_name_literal(model):
    site, = _step_site(model, "Hardcoded", 2)
    assert (site.sink, site.klass) == ("Set Field By Name", "B")
    assert _targets(site) == {"field:Contact::email"}


def test_value_list_items_reuses_the_existing_reference(model):
    site, = _step_site(model, "Hardcoded", 3)
    assert (site.klass, _targets(site)) == ("B", {"valueList:Statuses"})
    refs = [r for r in model.references if r.source_doc_id == site.source_doc_id and r.target_doc_id == "valueList:Statuses"]
    assert len(refs) == 1 and refs[0].via == "byName" and refs[0].site_doc_id == site.doc_id


def test_layout_name_comparison(model):
    site, = _step_site(model, "Hardcoded", 4)
    assert (site.sink, site.name_kind, site.klass) == ("Get ( LayoutName ) =", "layout", "B")
    assert _targets(site) == {"layout:Invoice Detail"}


def test_go_to_object_literal(model):
    site, = _step_site(model, "Hardcoded", 5)
    assert (site.name_kind, site.klass) == ("layoutObject", "B")
    assert _targets(site) == {"layoutObject:Invoice Detail::2"}


def test_sql_literal_names_table_occurrence_and_column(model):
    site, = _step_site(model, "Hardcoded", 6)
    assert (site.sink, site.klass) == ("ExecuteSQL", "B")
    assert _targets(site) == {"to:INV", "field:Invoice::total", "field:Invoice::id"}  # WHERE id = ?


def test_missing_field_is_broken_and_warned(model):
    site, = _step_site(model, "Hardcoded", 7)
    assert site.klass == "E" and "INV::missing" in site.note
    assert any(w.code == "BYNAME_TARGET_MISSING" and w.entity_doc_id == site.source_doc_id for w in model.warnings)


def test_evaluate_literal_names_its_fields(model):
    site, = _step_site(model, "Hardcoded", 8)
    assert (site.sink, site.klass, _targets(site)) == ("Evaluate", "B", {"field:Invoice::status"})


def test_lookalike_literals_are_not_reported(model):
    assert not [s for s in _sites(model, "Hardcoded") if s.step == 9]


def test_wrapper_custom_function_is_a_sink_at_its_call_site(model):
    site, = _step_site(model, "Hardcoded", 10)
    assert site.sink == "ReadField() → GetField"
    assert (site.klass, _targets(site)) == ("B", {"field:Invoice::status"})
    # the GetField inside the CF itself depends on its parameter: no site there
    assert not [s for s in model.indirection if s.source_doc_id == "customFunction:ReadField"]


def test_disabled_step_is_noted(model):
    site, = _step_site(model, "Hardcoded", 11)
    assert "disabled" in site.note


def test_field_calculation_is_a_site_too(model):
    site, = [s for s in model.indirection if s.source_doc_id == "field:Invoice::label"]
    assert (site.source_entity_type, site.role, site.klass) == ("field", "calculation", "B")


# ---------------------------------------------------------------------------
# Class A / A': names that follow a rename
# ---------------------------------------------------------------------------

def test_getfieldname_through_a_variable_is_safe(model):
    site, = _step_site(model, "Safe", 2)
    assert site.klass == "A"
    cand, = site.candidates
    assert (cand.target_doc_id, cand.origin, cand.breaks_on_rename) == ("field:Invoice::note", "capture", False)
    assert any("$f set at step 1" in e for e in cand.evidence)


def test_perform_script_on_server_self(model):
    site, = _step_site(model, "Safe", 3)
    assert (site.sink, site.klass, _targets(site)) == ("Perform Script on Server [ By name ]", "A", {"script:Safe"})


def test_sql_helper_functions_are_safe_captures(model):
    site, = _step_site(model, "Safe", 4)
    assert site.klass == "A"
    assert _targets(site) == {"field:Invoice::total", "field:Invoice::id"}


def test_sql_on_system_tables_is_id_based(model):
    site, = _step_site(model, "Safe", 5)
    assert site.klass == "A'"


def test_id_resolver_custom_function(model):
    site, = _step_site(model, "Safe", 6)
    assert (site.klass, _targets(site)) == ("A'", {"script:Dynamic"})


def test_substitute_sql_template(model):
    site, = _step_site(model, "Safe", 8)
    assert site.klass == "A"
    assert _targets(site) == {"field:Invoice::total", "field:Invoice::id"}


# ---------------------------------------------------------------------------
# Script parameters
# ---------------------------------------------------------------------------

def test_trigger_parameter_capture_reaches_set_field_by_name(model):
    site, = _step_site(model, "Copy Into Target", 3)
    assert (site.klass, _targets(site)) == ("A", {"field:Invoice::note"})
    evidence = site.candidates[0].evidence
    assert any("OnObjectModify trigger" in e for e in evidence)


def test_callback_script_name_resolves_to_the_caller(model):
    site, = _step_site(model, "Process", 3)
    assert (site.klass, _targets(site)) == ("A", {"script:Caller"})
    assert site.candidates[0].origin == "self"


def test_literal_in_a_callers_parameter_is_dynamic_and_breaks(model):
    site, = _step_site(model, "Mapper", 1)
    assert (site.klass, _targets(site)) == ("C", {"field:Contact::email"})
    cand = site.candidates[0]
    assert (cand.origin, cand.confidence) == ("literal", "inferred")
    assert any("step 2 of script \"Caller\"" in e for e in cand.evidence)


# ---------------------------------------------------------------------------
# Class C / D
# ---------------------------------------------------------------------------

def test_layout_name_pattern(model):
    site, = _step_site(model, "Dynamic", 2)
    assert site.klass == "C" and site.names == ["* tabs"]
    assert _targets(site) == {"layout:Report A tabs", "layout:Report B tabs"}
    assert {c.origin for c in site.candidates} == {"pattern"}


def test_layout_name_through_a_variable(model):
    site, = _step_site(model, "Dynamic", 4)
    assert (site.klass, _targets(site)) == ("C", {"layout:Report A tabs"})


def test_go_to_layout_by_number_is_not_a_name(model):
    assert not [s for s in _sites(model, "Dynamic") if s.step == 5]


def test_names_from_data_are_opaque(model):
    by_step = {s.step: s for s in _sites(model, "Dynamic")}
    assert by_step[6].klass == "D" and by_step[6].sink == "Set Field By Name"
    assert by_step[7].klass == "D"
    assert any(w.code == "BYNAME_OPAQUE" for w in model.warnings)


# ---------------------------------------------------------------------------
# References, backlinks, warnings
# ---------------------------------------------------------------------------

def test_by_name_references_and_backlinks(model):
    refs = [r for r in model.references if r.via == "byName"]
    assert refs and all(r.site_doc_id for r in refs)
    backs = model.backlinks["field:Contact::email"]
    assert any(b.get("via") == "byName" for b in backs)


def test_unused_field_warning_counts_by_name_use(model):
    unused = {w.entity_doc_id for w in model.warnings if w.code == "UNUSED_FIELD_CANDIDATE"}
    assert "field:Contact::email" not in unused  # only ever used by name


def test_model_json_round_trip(model, tmp_path):
    from fm_saxml.model.document_model import DocumentModel
    data = json.loads(model.model_dump_json(by_alias=True))
    assert data["indirectionSites"][0]["class"]
    again = DocumentModel.model_validate(data)
    assert len(again.indirection) == len(model.indirection)


# ---------------------------------------------------------------------------
# Output: Markdown pages, report, WebMCP data and tools
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docs(xml_path, tmp_path_factory):
    out = tmp_path_factory.mktemp("docs") / "out"
    result = runner.invoke(app, ["build", str(xml_path), "-o", str(out), "-f", "--webmcp"])
    assert result.exit_code == 0, result.output
    return out


def test_indirection_report(docs):
    text = (docs / "Reports" / "indirection.md").read_text(encoding="utf-8")
    assert "## Rename Risk" in text and "## Broken (E)" in text and "INV::missing" in text
    assert "| B | Hardcoded name |" in text
    assert "ReadField" in text  # the wrapper custom function is listed with its role
    summary = (docs / "Reports" / "summary.md").read_text(encoding="utf-8")
    assert "## Names Written in Text" in summary and "indirection.md" in summary


def test_field_page_lists_what_breaks_and_what_is_safe(docs):
    email = (docs / "Fields" / "Contact" / "email.md").read_text(encoding="utf-8")
    assert "## Referenced by Name" in email and "### Breaks on Rename" in email
    assert "Hardcoded · step 2" in email and "Mapper · step 1" in email
    note = (docs / "Fields" / "Invoice" / "note.md").read_text(encoding="utf-8")
    assert "### Name Captured Safely" in note and "OnObjectModify trigger" in note
    # The by-name uses are not repeated in the direct "Used By" tables
    used_by = email.split("## Used By", 1)[1] if "## Used By" in email else ""
    assert "Set Field By Name" not in used_by


def test_script_page_lists_its_names_in_text(docs):
    page = next((docs / "Scripts").rglob("Hardcoded.md")).read_text(encoding="utf-8")
    assert "## Names Used in Text" in page
    assert "B (Hardcoded name)" in page and "E (Broken)" in page


def test_custom_function_page_says_what_it_does_with_names(docs):
    page = next((docs / "CustomFunctions").rglob("ReadField.md")).read_text(encoding="utf-8")
    assert "Passes `name` to GetField" in page
    sql_field = next((docs / "CustomFunctions").rglob("SQLField.md")).read_text(encoding="utf-8")
    assert "Captures the name of the field" in sql_field


def _js_call(path, fn):
    text = path.read_text(encoding="utf-8")
    prefix = f"FMDocs.{fn}("
    return json.loads("[" + text[len(prefix):-3] + "]")


def test_webmcp_data_has_the_sites_and_by_name_edges(docs):
    data = docs / "_viewer" / "data" / "_"
    _key, kind, sites = _js_call(data / "indirectionSite.js", "shard")
    assert kind == "indirectionSite" and len(sites) == len([1 for _ in sites])
    missing = next(s for s in sites if "INV::missing" in s["expression"])
    assert missing["class"] == "E" and missing["where"] == "Hardcoded · step 7" and missing["path"]
    _key, refs = _js_call(data / "refs.js", "refs")
    cols = refs["cols"]
    assert cols[-2:] == ["via", "site"]
    assert any(row[cols.index("via")] == "byName" for row in refs["rows"])
    _key, catalog = _js_call(data / "catalog.js", "catalog")
    assert catalog["counts"]["indirectionSite"] == len(sites)


@pytest.fixture(scope="module")
def viewer(docs):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((docs / "index.html").as_uri())
        try:
            page.wait_for_selector("body[data-rendered]", timeout=60000)
        except Exception as exc:  # the renderer comes from a CDN
            pytest.skip(f"viewer didn't render (offline?): {exc}")
        yield page, errors
        browser.close()


def _run(page, name, args):
    res = page.evaluate("([n, a]) => FMDocs.tools[n].execute(a)", [name, {**args, "display": False}])
    body = json.loads(res["content"][0]["text"])
    assert not res.get("isError"), body
    return body


def test_find_indirection_tool(viewer):
    page, errors = viewer
    broken = _run(page, "find_indirection", {"class": ["E"]})
    assert broken["total"] == 1 and "INV::missing" in broken["items"][0]["expression"]
    sql = _run(page, "find_indirection", {"sink": "executesql"})
    assert {i["class"] for i in sql["items"]} == {"A", "A'", "B"}
    by_target = _run(page, "find_indirection", {"targetDocId": "field:Contact::email"})
    assert by_target["total"] == 2
    assert errors == []


def test_rename_impact_tool(viewer):
    page, _ = viewer
    impact = _run(page, "rename_impact", {"docId": "field:Contact::email"})
    assert impact["counts"]["breaks"] == 2 and "would break" in impact["summary"]
    groups = {i["groupLabel"] for i in impact["items"]}
    assert "Breaks on rename: edit these" in groups
    note = _run(page, "rename_impact", {"docId": "field:Invoice::note"})
    assert note["counts"]["breaks"] == 0 and note["counts"]["safe"] >= 2
    assert note["counts"]["opaque"] >= 1  # Set Field By Name [ Get ( LayoutTableName ) & "::" & ... ]


def test_find_references_marks_and_can_skip_by_name(viewer):
    page, _ = viewer
    every = _run(page, "find_references", {"docId": "field:Contact::email"})
    assert any(i.get("byName") for i in every["items"])
    direct = _run(page, "find_references", {"docId": "field:Contact::email", "includeByName": False})
    assert not any(i.get("byName") for i in direct["items"])


# ---------------------------------------------------------------------------
# rename-check and diff
# ---------------------------------------------------------------------------

def test_rename_impact_api(model):
    from fm_saxml.analyze.rename import find_entities, rename_impact

    assert find_entities(model, "inv::NOTE") == ["field:Invoice::note"]  # TO name, any case
    impact = rename_impact(model, "field:Contact::email", "email_address")
    assert len(impact.breaks) == 2 and impact.clashes == []
    assert {s.sink for s, _c in impact.breaks} == {"Set Field By Name"}
    # Renaming status to "total" clashes with the existing field
    assert rename_impact(model, "field:Invoice::status", "total").clashes == ["field:Invoice::total"]
    # Renaming note to "missing" makes the broken GetField ( "INV::missing" ) point at it
    taken = rename_impact(model, "field:Invoice::note", "missing")
    assert [s.step for s in taken.captured_by_new_name] == [7]


def test_rename_check_cli(xml_path, tmp_path):
    out = tmp_path / "check.md"
    plan = tmp_path / "plan.csv"
    plan.write_text("old,new,kind\nContact::email,email_address,field\nProcess,Process Invoice,script\n", encoding="utf-8")
    result = runner.invoke(app, ["rename-check", str(xml_path), "btnSave", "--plan", str(plan),
                                 "--out", str(out), "--strict", "--disable-scrubbing"])
    assert result.exit_code == 1, result.output  # --strict: something is named in text
    assert "would break" in result.output
    report = out.read_text(encoding="utf-8")
    assert "## Contact::email (field) → email_address" in report
    assert "| Hardcoded · step 2 | Set Field By Name | `Contact::email` | parsed | written here |" in report
    assert "## Invoice Detail · btnSave (layoutObject)" in report

    missing = runner.invoke(app, ["rename-check", str(xml_path), "Nope", "--disable-scrubbing"])
    assert missing.exit_code == 1 and "Not found: Nope" in missing.output


def test_diff_reports_names_still_using_an_old_name(xml_path, tmp_path):
    renamed = tmp_path / "renamed.xml"
    xml = XML.replace('<Field id="1" name="email"', '<Field id="1" name="email_address"')
    xml = xml.replace('name="btnSave"', 'name="btn_save"')
    renamed.write_text(xml, encoding="utf-8")
    out = tmp_path / "diff.md"
    result = runner.invoke(app, ["diff", str(xml_path), str(renamed), "-o", str(out), "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    assert "still use an old name" in result.output
    report = out.read_text(encoding="utf-8")
    assert "## Names Still Using an Old Name" in report
    stale = report.split("## Names Still Using an Old Name", 1)[1].split("\n## ", 1)[0]
    assert "email → email_address (field) | Hardcoded · step 2 | Set Field By Name" in stale
    assert "Mapper · step 1" in stale  # the literal reaches Mapper through Caller's parameter
    assert "btnSave → btn_save (layoutObject) | Hardcoded · step 5 | Go to Object" in stale
    assert "| field | email | email_address |" in report
