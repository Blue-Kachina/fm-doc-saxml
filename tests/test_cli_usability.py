"""CLI usability: bare invocation, default output dir, friendly errors."""

from pathlib import Path

from typer.testing import CliRunner

from fm_saxml.cli import OUTPUT_MARKER, _default_out_dir, app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_default_out_dir_is_next_to_input():
    assert _default_out_dir(Path("/x/y/MyApp.xml")) == Path("/x/y/MyApp_docs")


def test_bare_invocation_runs_build(tmp_path):
    xml = tmp_path / "Sample.xml"
    xml.write_bytes((FIXTURES / "small_sample.xml").read_bytes())
    result = runner.invoke(app, [str(xml)])
    assert result.exit_code == 0, result.output
    out = tmp_path / "Sample_docs"
    assert (out / "index.md").exists()
    assert (out / OUTPUT_MARKER).exists()


def test_malformed_xml_gives_friendly_error(tmp_path):
    xml = tmp_path / "broken.xml"
    xml.write_text("<FMSaveAsXML><Oops", encoding="utf-8")
    result = runner.invoke(app, [str(xml)])
    assert result.exit_code == 1
    assert "not valid XML" in result.output
    assert not (tmp_path / "broken_docs").exists()


def test_non_filemaker_xml_rejected(tmp_path):
    xml = tmp_path / "other.xml"
    xml.write_text("<root><a/></root>", encoding="utf-8")
    result = runner.invoke(app, ["build", str(xml)])
    assert result.exit_code == 1
    assert "doesn't contain" in result.output


def test_doctor_runs():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_output_to_the_null_device_does_not_crash():
    # On Windows, NUL claims to be a cp1252 terminal, so Rich animates its spinner
    # with characters cp1252 can't encode. Run the real entry point, as CI would.
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["FM_SAXML_NO_UPDATE_CHECK"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "fm_saxml", "inspect", str(FIXTURES / "small_sample_v2.xml")],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
