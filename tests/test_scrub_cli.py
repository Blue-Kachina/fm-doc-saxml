"""Scrubbing end to end: nothing secret reaches any output file unless scrubbing is disabled."""

from pathlib import Path

import orjson
from typer.testing import CliRunner

from fm_saxml.cli import app

from .fake_keys import OPENAI_LONG

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()

SECRETS = ("Hunter2Secret!", OPENAI_LONG, "jane.doe@example.com", "fms.corp.local")


def _secret_xml(tmp_path: Path, password: str = "Hunter2Secret!", script_name: str = "Login") -> Path:
    xml = (FIXTURES / "small_sample_v2.xml").read_text(encoding="utf-8")
    xml = xml.replace(
        "<Calculation>Active</Calculation>",
        '<Calculation><![CDATA[Let ( [ $password = "' + password + '" ; '
        f'$k = "{OPENAI_LONG}" ] ; "https://bob:" & $password & "@fms.corp.local/api" )]]></Calculation>',
    )
    xml = xml.replace(
        '<Step enable="True" id="70" index="2" name="New Record/Request"/>',
        '<Step enable="True" id="70" index="2" name="New Record/Request"/>'
        '<Step enable="True" id="141" index="4" name="Set Variable">'
        '<Calculation><![CDATA["Contact jane.doe@example.com, pw ' + password + '"]]></Calculation></Step>',
    )
    xml = xml.replace('name="Create Customer" uuid', f'name="{script_name}" uuid', 1)
    xml = xml.replace(
        'name="CustomerID" uuid="A1B2C3D4-0001-0001-0001-000000000101"',
        'name="CustomerID" comment="Owner: jane.doe@example.com" uuid="A1B2C3D4-0001-0001-0001-000000000101"',
    )
    path = tmp_path / "Secrets.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _all_output(*paths: Path) -> str:
    chunks = []
    for p in paths:
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        chunks += [f.read_text(encoding="utf-8", errors="replace") for f in files]
    return "\n".join(chunks)


def test_build_scrubs_every_output_file(tmp_path):
    xml = _secret_xml(tmp_path)
    out, model = tmp_path / "docs", tmp_path / "model.json"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "--model-out", str(model)])
    assert result.exit_code == 0, result.output

    everything = _all_output(out, model)
    for secret in SECRETS:
        assert secret not in everything, secret
    assert "[REDACTED:password#1]" in everything
    assert "Scrubbed" in result.output

    report = (out / "Reports" / "redactions.md").read_text(encoding="utf-8")
    assert "[REDACTED:api_key#1]" in report and "[HOST#1]" in report
    assert "redactions.md" in (out / "Reports" / "summary.md").read_text(encoding="utf-8")
    assert orjson.loads(model.read_bytes())["scrubbing"]["applied"] is True


def test_disable_scrubbing_writes_values_as_is(tmp_path):
    xml = _secret_xml(tmp_path)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    assert "Scrubbing disabled" in result.output

    everything = _all_output(out)
    assert "Hunter2Secret!" in everything
    assert "Scrubbing was disabled" in (out / "Reports" / "redactions.md").read_text(encoding="utf-8")


def test_scrub_level_secrets_keeps_hosts_and_emails(tmp_path):
    xml = _secret_xml(tmp_path)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "--scrub-level", "secrets"])
    assert result.exit_code == 0, result.output
    everything = _all_output(out)
    assert "jane.doe@example.com" in everything
    assert "Hunter2Secret!" not in everything


def test_guard_fails_when_a_value_survives_in_a_name(tmp_path):
    # The script is *named* after the password. Names are never rewritten, so
    # the value reaches the output and the guard must catch it.
    xml = _secret_xml(tmp_path, password="Xy7kL9mQ2z", script_name="Xy7kL9mQ2z")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out)])
    assert result.exit_code == 2, result.output
    assert "Scrubbing guard failed" in result.output
    assert "Xy7kL9mQ2z" not in result.output


def test_guard_respects_allow_list(tmp_path):
    xml = _secret_xml(tmp_path, password="Xy7kL9mQ2z", script_name="Xy7kL9mQ2z")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "--scrub-allow", "Xy7kL9mQ2z"])
    assert result.exit_code == 0, result.output


def test_render_scrubs_a_model_saved_unscrubbed(tmp_path):
    xml = _secret_xml(tmp_path)
    model = tmp_path / "model.json"
    assert runner.invoke(app, ["parse", str(xml), "-o", str(model), "--disable-scrubbing"]).exit_code == 0
    assert "Hunter2Secret!" in model.read_text(encoding="utf-8")

    out = tmp_path / "docs"
    result = runner.invoke(app, ["render", "markdown", "-m", str(model), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "scrubbing it now" in result.output
    everything = _all_output(out)
    for secret in SECRETS:
        assert secret not in everything, secret


def test_diff_report_is_scrubbed(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old = _secret_xml(old_dir, password="OldPassw0rd!")
    new = _secret_xml(new_dir, password="NewPassw0rd!")
    report = tmp_path / "diff.md"
    result = runner.invoke(app, ["diff", str(old), str(new), "-o", str(report)])
    assert result.exit_code == 0, result.output
    text = report.read_text(encoding="utf-8")
    assert "OldPassw0rd!" not in text and "NewPassw0rd!" not in text


def test_fail_on_secrets_exits_1_after_writing_output(tmp_path):
    xml = _secret_xml(tmp_path)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "--fail-on-secrets"])
    assert result.exit_code == 1, result.output
    assert "--fail-on-secrets" in result.output
    assert (out / "Reports" / "redactions.md").exists()  # the report explains the failure


def test_fail_on_secrets_passes_clean_export(tmp_path):
    xml = tmp_path / "Clean.xml"
    xml.write_bytes((FIXTURES / "small_sample_v2.xml").read_bytes())
    result = runner.invoke(app, ["build", str(xml), "-o", str(tmp_path / "docs"), "--fail-on-secrets"])
    assert result.exit_code == 0, result.output


def test_fail_on_secrets_warns_when_scrubbing_disabled(tmp_path):
    xml = _secret_xml(tmp_path)
    result = runner.invoke(app, ["build", str(xml), "-o", str(tmp_path / "docs"), "--fail-on-secrets",
                                 "--disable-scrubbing"])
    assert result.exit_code == 0
    assert "no effect" in result.output


def test_report_step_numbers_match_the_script_page(tmp_path):
    import re

    xml = _secret_xml(tmp_path)
    out = tmp_path / "docs"
    assert runner.invoke(app, ["build", str(xml), "-o", str(out)]).exit_code == 0
    report = (out / "Reports" / "redactions.md").read_text(encoding="utf-8")
    m = re.search(r"Script 'Login' › Step (\d+): Set Variable", report)
    assert m, report
    page = next(out.joinpath("Scripts").rglob("Login.md")).read_text(encoding="utf-8")
    row = next(line for line in page.splitlines() if line.startswith(f"| {m.group(1)} |"))
    assert "Set Variable" in row and "[EMAIL#" in row
