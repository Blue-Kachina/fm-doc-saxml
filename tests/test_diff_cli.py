"""End-to-end tests for the `fm-saxml diff` CLI command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from fm_saxml.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_diff_no_changes_exits_zero():
    result = runner.invoke(app, ["diff", str(FIXTURES / "small_sample.xml"), str(FIXTURES / "small_sample.xml")])
    assert result.exit_code == 0
    assert "No differences detected" in result.stdout


def test_diff_with_changes_exits_zero_without_strict():
    result = runner.invoke(app, ["diff", str(FIXTURES / "small_sample.xml"), str(FIXTURES / "small_sample_v2.xml")])
    assert result.exit_code == 0


def test_diff_with_changes_and_strict_exits_nonzero():
    result = runner.invoke(app, [
        "diff", str(FIXTURES / "small_sample.xml"), str(FIXTURES / "small_sample_v2.xml"), "--strict",
    ])
    assert result.exit_code == 1


def test_diff_no_changes_and_strict_exits_zero():
    result = runner.invoke(app, [
        "diff", str(FIXTURES / "small_sample.xml"), str(FIXTURES / "small_sample.xml"), "--strict",
    ])
    assert result.exit_code == 0


def test_diff_writes_markdown_report(tmp_path):
    out_path = tmp_path / "diff-report.md"
    result = runner.invoke(app, [
        "diff", str(FIXTURES / "small_sample.xml"), str(FIXTURES / "small_sample_v2.xml"),
        "--out", str(out_path),
    ])
    assert result.exit_code == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Diff Report" in content
    assert "Invoice::Notes" in content  # added field
    assert "Invoice::InvoiceDate" in content  # removed field
    assert "Delete Customer" in content  # removed script
    assert "Script Step Changes" in content


def test_diff_accepts_model_json_input(tmp_path):
    model_path = tmp_path / "model.json"
    parse_result = runner.invoke(app, ["parse", str(FIXTURES / "small_sample.xml"), "--out", str(model_path)])
    assert parse_result.exit_code == 0
    assert model_path.exists()

    diff_result = runner.invoke(app, ["diff", str(model_path), str(FIXTURES / "small_sample_v2.xml")])
    assert diff_result.exit_code == 0


def test_diff_rejects_missing_input():
    result = runner.invoke(app, ["diff", str(FIXTURES / "does_not_exist.xml"), str(FIXTURES / "small_sample.xml")])
    assert result.exit_code == 1
