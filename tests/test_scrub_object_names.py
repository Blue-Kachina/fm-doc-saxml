"""A literal that names an object in the solution is that name, not a secret.

<Function Missing> has lost its function's name, so every string argument may be the
secret. When one equals a custom function's, script's or layout object's name, it was
being redacted, the name itself stayed in the output (names are never rewritten) and the
guard stopped the build. Rules that only guess now leave such a value alone and flag it.
"""

import re
from pathlib import Path

from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.scrub import Scrubber
from fm_saxml.scrub.engine import NAME_DEFERRING_DETECTORS, _object_names

FIXTURES = Path(__file__).parent / "fixtures"
SRC = Path(__file__).parent.parent / "src" / "fm_saxml"
runner = CliRunner()

PASSWORD = "y8L9k7fp"


def _xml(path: Path, file_name: str = "SampleSolution", custom_functions: str = "", script: str = "") -> Path:
    xml = (FIXTURES / "small_sample_v2.xml").read_text(encoding="utf-8")
    xml = xml.replace('name="SampleSolution"', f'name="{file_name}"')
    xml = xml.replace("</CustomFunctionCatalog>", custom_functions + "</CustomFunctionCatalog>")
    if script:
        xml = xml.replace("</ScriptCatalog>",
                          f'<Script id="9" name="{script}" uuid="E1B2C3D4-0009-0009-0009-000000000009">'
                          "<StepList/></Script></ScriptCatalog>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return path


def _cf(name: str, calc: str, cf_id: int) -> str:
    return (f'<CustomFunction id="{cf_id}" name="{name}" pramaters="NewState">'
            f"<Calculation><![CDATA[{calc}]]></Calculation></CustomFunction>")


# The shape of the reported bug: a plugin call whose argument is its own custom function's name.
SIDE_DRAWER = _cf("SideDrawer", 'If ( $$CurrentState ≠ NewState ; Let ( $$CurrentState = NewState ; '
                                '<Function Missing> ( "SideDrawer" ) ) )', 2)
# The second case: the argument is a script's name, in a different custom function.
HOVER_TIP = _cf("HoverTip", '<Function Missing> ( "Flyout" ; NewState )', 3)
# A real secret in the same kind of call must still go.
MAILER = _cf("Mailer", f'<Function Missing> ( "smtp.example.com" ; 587 ; "svc@example.com" ; "{PASSWORD}" )', 4)


def _all_output(folder: Path) -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in folder.rglob("*") if f.is_file())


def _build(source: Path, out: Path, *extra: str):
    result = runner.invoke(app, ["build", str(source), "-o", str(out), *extra])
    assert result.exit_code == 0, result.output
    return result


def test_a_custom_functions_own_name_is_not_redacted(tmp_path):
    xml = _xml(tmp_path / "in" / "Plugin.xml", custom_functions=SIDE_DRAWER + MAILER)
    out = tmp_path / "docs"
    _build(xml, out, "--html")
    everything = _all_output(out)
    assert '<Function Missing> ( "SideDrawer" )' in everything
    assert PASSWORD not in everything
    report = (out / "Reports" / "redactions.md").read_text(encoding="utf-8")
    assert "## Needs review" in report and "custom function 'SideDrawer'" in report
    assert "Custom function '[REDACTED" not in report


def test_a_literal_naming_a_script_is_not_redacted(tmp_path):
    xml = _xml(tmp_path / "in" / "Plugin.xml", custom_functions=HOVER_TIP + MAILER, script="Flyout")
    out = tmp_path / "docs"
    _build(xml, out, "--html")
    everything = _all_output(out)
    assert '<Function Missing> ( "Flyout" ; NewState )' in everything
    assert PASSWORD not in everything
    assert "script 'Flyout'" in (out / "Reports" / "redactions.md").read_text(encoding="utf-8")


def test_a_name_from_another_file_is_known_before_any_file_is_scrubbed(tmp_path):
    # FileOne is scrubbed first; the script it names is only in FileTwo.
    folder = tmp_path / "export"
    _xml(folder / "FileOne.xml", "FileOne", custom_functions=HOVER_TIP + MAILER)
    _xml(folder / "FileTwo.xml", "FileTwo", script="Flyout")
    out = tmp_path / "docs"
    _build(folder, out, "--html")
    everything = _all_output(out)
    assert '<Function Missing> ( "Flyout" ; NewState )' in everything
    assert PASSWORD not in everything


def test_names_compare_without_case(tmp_path):
    cf = _cf("HoverTip", '<Function Missing> ( "FLYOUT" )', 3)
    out = tmp_path / "docs"
    _build(_xml(tmp_path / "in" / "Plugin.xml", custom_functions=cf, script="Flyout"), out)
    assert '<Function Missing> ( "FLYOUT" )' in _all_output(out)


def test_object_names_cover_raw_and_saved_models():
    raw = parse_savexml(FIXTURES / "small_sample_v2.xml")
    scrubber = Scrubber()
    scrubber.learn_names(raw)
    assert scrubber.object_kind("FormatCurrency") == "custom function"
    assert scrubber.object_kind(" create CUSTOMER ") == "script"
    assert scrubber.object_kind("Popover") is None

    saved = {"entities": {
        "customFunctions": {"cf:1": {"name": "SideDrawer"}},
        "layoutObjects": {"lo:1": {"name": "Flyout Panel"}},
        "accounts": {"acct:1": {"name": "jsmith"}},
    }}
    assert set(_object_names(saved)) == {("custom function", "SideDrawer"), ("layout object", "Flyout Panel")}


def test_named_layout_objects_inside_raw_layouts():
    roots = {"layouts": [{"name": "Home", "layout_objects": [{"name": "btnFlyout"}, {"name": ""}]}]}
    assert set(_object_names(roots)) == {("layout", "Home"), ("layout object", "btnFlyout")}


def test_every_name_deferring_detector_exists():
    # A typo here would quietly turn the rule off for that detector.
    source = "\n".join(p.read_text(encoding="utf-8") for p in (SRC / "scrub").rglob("*.py"))
    for detector in NAME_DEFERRING_DETECTORS:
        assert re.search(rf'"{detector}"', source), detector
