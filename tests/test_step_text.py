"""Full script step text (model/step_text.py), structured step params, and the variable index."""

from pathlib import Path

from lxml import etree
from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.model.step_text import code_fence, render_script_block, step_text
from fm_saxml.normalize.variables import calc_variables
from fm_saxml.parser.extractors.scripts import _parse_step

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _calc(text: str, position: int = 0) -> str:
    return (f'<Calculation datatype="1" position="{position}"><Calculation>'
            f"<Text><![CDATA[{text}]]></Text></Calculation></Calculation>")


def _step(name: str, params: str, index: int = 0, step_id: str = "1", enabled: str = "True") -> str:
    return (f'<Step index="{index}" id="{step_id}" name="{name}" enable="{enabled}">'
            f"<ParameterValues>{params}</ParameterValues></Step>")


COMMENT = _step("# (comment)", '<Parameter type="Comment"><Comment value="Line one&#13;Line two"/></Parameter>',
                step_id="89")
SET_VARIABLE = _step("Set Variable", (
    '<Parameter type="Variable"><value>' + _calc("Get ( ScriptName )", 1) + '</value>'
    '<Name value="$TASK_NAME"/><repetition>' + _calc("1", 2) + "</repetition></Parameter>"), step_id="141")
SET_VARIABLE_REP = SET_VARIABLE.replace("CDATA[1]", "CDATA[$i]")
LONG = "Let ( [\r  a = 1 ;\r  b = \"" + "x" * 120 + "\"\r] ;\r  a & b\r)"
SET_FIELD = _step("Set Field", (
    '<Parameter type="FieldReference"><FieldReference id="2" name="Notes">'
    '<repetition>' + _calc("1", 1) + '</repetition>'
    '<TableOccurrenceReference id="9" name="Contact"/></FieldReference></Parameter>'
    '<Parameter type="Calculation">' + _calc(LONG, 0) + "</Parameter>"), step_id="76")
PERFORM_SCRIPT = _step("Perform Script", (
    '<Parameter type="List"><List name="From list" value="1"><ScriptReference id="3" name="Do Thing"/></List></Parameter>'
    '<Parameter type="Parameter"><Parameter>' + _calc("$id", 0) + "</Parameter></Parameter>"))
DIALOG = _step("Show Custom Dialog", (
    '<Parameter type="Title">' + _calc('"Oops"', 0) + "</Parameter>"
    '<Parameter type="Message">' + _calc("$errorMsg", 1) + "</Parameter>"
    '<Parameter type="Button1" value="OK"><Boolean type="Commit" value="True"/></Parameter>'
    '<Parameter type="Button2"><Boolean type="Commit" value="False"/></Parameter>'))
INSERT_FROM_URL = _step("Insert from URL", (
    '<Parameter type="Boolean"><Boolean type="With dialog" id="128" value="False"/></Parameter>'
    '<Parameter type="Target"><Variable value="$response"><repetition>' + _calc("1", 3) + "</repetition></Variable></Parameter>"
    '<Parameter type="URL"><URL autoEncode="True">' + _calc("$url", 0) + "</URL></Parameter>"))
ON_TIMER = _step("Install OnTimer Script", (
    '<Parameter type="ScriptReference"><ScriptReference id="4" name="Tick"><repetition>'
    + _calc("$prm", 0) + "</repetition></ScriptReference></Parameter>"
    '<Parameter type="Calculation">' + _calc("5", 1) + "</Parameter>"))


def _parse(xml: str, index: int = 0) -> dict:
    return _parse_step(etree.fromstring(xml), index)


def test_comment_text_is_kept_and_shown():
    step = _parse(COMMENT)
    assert step["params"] == [{"kind": "comment", "text": "Line one\rLine two"}]
    assert step_text(step) == "# Line one\n# Line two"


def test_empty_comment_is_a_blank_line():
    step = _parse(_step("# (comment)", '<Parameter type="Comment"><Comment/></Parameter>', step_id="89"))
    assert step_text(step) == ""


def test_set_variable_shows_the_name_and_value_but_not_a_repetition_of_one():
    assert step_text(_parse(SET_VARIABLE)) == "Set Variable [ $TASK_NAME ; Value: Get ( ScriptName ) ]"
    assert step_text(_parse(SET_VARIABLE_REP)) == "Set Variable [ $TASK_NAME[$i] ; Value: Get ( ScriptName ) ]"


def test_set_field_shows_the_target_and_the_whole_calculation():
    text = step_text(_parse(SET_FIELD))
    assert text.startswith("Set Field [ Contact::Notes ; Let ( [")
    assert "x" * 120 in text  # nothing truncated
    assert text.count("\n") == 5  # FileMaker's line breaks kept


def test_perform_script_shows_its_parameter():
    assert step_text(_parse(PERFORM_SCRIPT)) == 'Perform Script [ "Do Thing" ; Parameter: $id ]'


def test_custom_dialog_and_targets():
    assert step_text(_parse(DIALOG)) == 'Show Custom Dialog [ Title: "Oops" ; Message: $errorMsg ; Button 1: OK ]'
    assert step_text(_parse(INSERT_FROM_URL)) == "Insert from URL [ With dialog: Off ; Target: $response ; URL: $url ]"


def test_on_timer_script_parameter_is_not_lost():
    assert step_text(_parse(ON_TIMER)) == 'Install OnTimer Script [ "Tick" ; Parameter: $prm ; 5 ]'


def test_every_calc_is_referenced_by_a_param():
    for xml in (SET_VARIABLE, SET_FIELD, PERFORM_SCRIPT, DIALOG, INSERT_FROM_URL, ON_TIMER):
        step = _parse(xml)
        used = {p.get("calc") for p in step["params"]} | {p.get("repetition") for p in step["params"]}
        assert set(range(len(step["calculations"]))) <= used, step["name"]


def test_steps_without_params_fall_back_to_the_preview():
    assert step_text({"name": "Beep", "params": [], "raw_text": "Beep"}) == "Beep"


def test_script_block_indents_blocks_and_marks_disabled_steps():
    steps = [
        {"name": "If", "index": 0, "params": [{"kind": "calc", "label": None, "calc": 0}],
         "calculations": [{"text": "$x"}]},
        {"name": "Beep", "index": 1, "params": []},
        {"name": "Else", "index": 2, "params": []},
        {"name": "Halt Script", "index": 3, "enabled": False, "params": []},
        {"name": "End If", "index": 4, "params": []},
    ]
    assert render_script_block(steps).splitlines() == [
        "1  If [ $x ]",
        "2      Beep",
        "3  Else",
        "4      // Halt Script",
        "5  End If",
    ]


def test_code_fence_outgrows_backticks_in_the_content():
    assert code_fence("plain") == "```"
    assert code_fence("a ```` b") == "`````"


# ---------------------------------------------------------------------------
# Variables in calculations
# ---------------------------------------------------------------------------

def test_calc_variables_reads_and_let_assignments():
    assert calc_variables('$a & $$B & "$notAVar" // $comment') == [("$a", False), ("$$B", False)]
    assert calc_variables("Let ( [ $x = 1 ; $y[2] = $x + $z ] ; $x & $y )") == [
        ("$x", True), ("$y", True), ("$x", False), ("$z", False), ("$x", False), ("$y", False)]
    assert calc_variables("Let ( $x = f ( $a ; $b ) ; $x )") == [
        ("$x", True), ("$a", False), ("$b", False), ("$x", False)]
    assert calc_variables("If ( $x = 1 ; $y )") == [("$x", False), ("$y", False)]  # a comparison, not a Let


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

STEPS = (
    COMMENT.replace('index="0"', 'index="1"').replace("Line one&#13;Line two", "temp password is swordfish99")
    + SET_VARIABLE.replace('index="0"', 'index="2"').replace("$TASK_NAME", "$$GLOBAL")
    + _step("Set Variable", '<Parameter type="Variable"><value>' + _calc("$$GLOBAL & $missing", 1)
            + '</value><Name value="$local"/></Parameter>', index=3, step_id="141")
    + SET_FIELD.replace('index="0"', 'index="4"').replace(
        "a & b", 'a & b & "Bearer sk-ant-api03-' + "Q" * 40 + '"')
)


def _export(tmp_path: Path) -> Path:
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace('<ObjectList membercount="2">\n            <Step hash="AAAA"',
                      '<ObjectList membercount="6">\n            <Step hash="AAAA"')
    xml = xml.replace("          </ObjectList>\n        </Script>\n      </StepsForScripts>",
                      STEPS + "          </ObjectList>\n        </Script>\n      </StepsForScripts>")
    path = tmp_path / "Export.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _build(tmp_path: Path) -> Path:
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(_export(tmp_path)), "-o", str(out), "-f"])
    assert result.exit_code == 0, result.output
    return out


def test_script_page_shows_full_steps_and_scrubs_them(tmp_path):
    out = _build(tmp_path)
    page = next((out / "Scripts").rglob("SendEmail.md")).read_text(encoding="utf-8")
    assert "# Send the email" in page
    assert "Set Variable [ $$GLOBAL ; Value: Get ( ScriptName ) ]" in page
    assert "Set Field [ Contact::Notes ; Let ( [" in page
    assert "x" * 120 in page
    everything = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    assert "swordfish99" not in everything and "Q" * 40 not in everything
    assert "temp password is [REDACTED:password#" in page


def test_variables_section_and_pages(tmp_path):
    out = _build(tmp_path)
    page = next((out / "Scripts").rglob("SendEmail.md")).read_text(encoding="utf-8")
    assert "## Variables" in page
    assert "| `$missing` | local |  | 4 | Never set in this script" in page
    assert "| `$local` | local | 4 |  |  |" in page
    index = (out / "Variables" / "index.md").read_text(encoding="utf-8")
    assert "$$GLOBAL" in index and "`$missing`" in index
    glob = (out / "Variables" / "$$GLOBAL.md").read_text(encoding="utf-8")
    assert "## Set By" in glob and "## Read By" in glob and "SendEmail" in glob
    assert "- [Variables](Variables/index.md)" in (out / "index.md").read_text(encoding="utf-8")


def test_diff_sees_changes_past_the_preview_width(tmp_path):
    old = _export(tmp_path)
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    new = new_dir / "Export.xml"
    new.write_text(old.read_text(encoding="utf-8").replace("a & b", "a & b & 1"), encoding="utf-8")
    from fm_saxml.analyze.diff import _step_signature
    from fm_saxml.cli import _run_pipeline
    m_old, m_new = _run_pipeline(old), _run_pipeline(new)
    sig = lambda m: [_step_signature(s) for s in m.entities.script_steps.values() if s.name == "Set Field"]
    assert sig(m_old) != sig(m_new)
