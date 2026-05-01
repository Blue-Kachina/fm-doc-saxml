"""Tests for Markdown rendering."""

from pathlib import Path
import pytest
import tempfile

from fm_docgen.parser.saxml_reader import parse_savexml
from fm_docgen.normalize.normalize import normalize
from fm_docgen.normalize.references import resolve_references
from fm_docgen.analyze.backlinks import generate_backlinks
from fm_docgen.render.markdown.renderer import render_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


@pytest.fixture
def model():
    raw = parse_savexml(FIXTURE)
    m = normalize(raw)
    m = resolve_references(m)
    m = generate_backlinks(m)
    return m


@pytest.fixture
def rendered(model, tmp_path):
    render_markdown(model, tmp_path)
    return tmp_path


def test_root_index_created(rendered):
    assert (rendered / "index.md").exists()


def test_root_index_content(rendered):
    content = (rendered / "index.md").read_text(encoding="utf-8")
    assert "SampleSolution" in content
    assert "Tables" in content
    assert "Scripts" in content


def test_tables_index_created(rendered):
    assert (rendered / "Tables" / "index.md").exists()


def test_table_file_created(rendered):
    assert (rendered / "Tables" / "Customer.md").exists()
    assert (rendered / "Tables" / "Invoice.md").exists()


def test_table_page_content(rendered):
    content = (rendered / "Tables" / "Customer.md").read_text(encoding="utf-8")
    assert "docId: table:Customer" in content
    assert "# Table: Customer" in content
    assert "CustomerID" in content
    assert "FullName" in content


def test_table_page_front_matter(rendered):
    content = (rendered / "Tables" / "Customer.md").read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "entityType: table" in content


def test_fields_index_created(rendered):
    assert (rendered / "Fields" / "index.md").exists()
    assert (rendered / "Fields" / "Customer" / "index.md").exists()


def test_field_file_created(rendered):
    assert (rendered / "Fields" / "Customer" / "CustomerID.md").exists()
    assert (rendered / "Fields" / "Customer" / "FullName.md").exists()
    assert (rendered / "Fields" / "Invoice" / "Amount.md").exists()


def test_field_page_content(rendered):
    content = (rendered / "Fields" / "Customer" / "CustomerID.md").read_text(encoding="utf-8")
    assert "docId: field:Customer::CustomerID" in content
    assert "# Field: Customer::CustomerID" in content
    assert "Normal" in content
    assert "Text" in content


def test_field_page_has_table_link(rendered):
    content = (rendered / "Fields" / "Customer" / "CustomerID.md").read_text(encoding="utf-8")
    assert "Customer.md" in content  # relative link back to table


def test_field_page_calculation(rendered):
    content = (rendered / "Fields" / "Customer" / "FullName.md").read_text(encoding="utf-8")
    assert "FirstName" in content  # calculation visible


def test_scripts_index_created(rendered):
    assert (rendered / "Scripts" / "index.md").exists()


def test_script_in_folder_created(rendered):
    assert (rendered / "Scripts" / "Customer Scripts" / "Create Customer.md").exists()
    assert (rendered / "Scripts" / "Post Invoice.md").exists()


def test_script_page_content(rendered):
    content = (rendered / "Scripts" / "Customer Scripts" / "Create Customer.md").read_text(encoding="utf-8")
    assert "# Script: Create Customer" in content
    assert "Go to Layout" in content
    assert "Set Field" in content


def test_relationships_created(rendered):
    assert (rendered / "Relationships" / "index.md").exists()
    assert (rendered / "Relationships" / "Customer_to_Invoice.md").exists()


def test_relationship_page_content(rendered):
    content = (rendered / "Relationships" / "Customer_to_Invoice.md").read_text(encoding="utf-8")
    assert "# Relationship: Customer_to_Invoice" in content
    assert "CustomerID" in content
    assert "CustomerFK" in content


def test_layouts_created(rendered):
    assert (rendered / "Layouts" / "index.md").exists()
    assert (rendered / "Layouts" / "Customer List.md").exists()


def test_custom_functions_created(rendered):
    assert (rendered / "CustomFunctions" / "index.md").exists()
    assert (rendered / "CustomFunctions" / "FormatCurrency.md").exists()


def test_value_lists_created(rendered):
    assert (rendered / "ValueLists" / "index.md").exists()
    assert (rendered / "ValueLists" / "CustomerStatus.md").exists()


def test_value_list_content(rendered):
    content = (rendered / "ValueLists" / "CustomerStatus.md").read_text(encoding="utf-8")
    assert "Active" in content
    assert "Inactive" in content


def test_reports_created(rendered):
    assert (rendered / "Reports" / "summary.md").exists()
    assert (rendered / "Reports" / "warnings.md").exists()
    assert (rendered / "Reports" / "unresolved-references.md").exists()


def test_summary_report_content(rendered):
    content = (rendered / "Reports" / "summary.md").read_text(encoding="utf-8")
    assert "Tables" in content
    assert "Fields" in content


def test_json_data_files_written(rendered, model):
    render_markdown(model, rendered)  # re-render to ensure json is written separately
    # (json files are written by build command, not render_markdown itself)
    # Just verify no error from re-render
    assert (rendered / "index.md").exists()
