"""Tests for the XML parser layer."""

from pathlib import Path
import pytest
from fm_saxml.parser.saxml_reader import parse_savexml

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


@pytest.fixture
def raw():
    return parse_savexml(FIXTURE)


def test_solution_name(raw):
    assert raw.solution_name == "SampleSolution"


def test_tables_extracted(raw):
    assert len(raw.tables) == 2
    names = {t["name"] for t in raw.tables}
    assert names == {"Customer", "Invoice"}


def test_fields_extracted(raw):
    assert len(raw.fields) == 9  # 5 Customer + 4 Invoice
    field_names = {f["name"] for f in raw.fields}
    assert "CustomerID" in field_names
    assert "FullName" in field_names
    assert "Amount" in field_names


def test_field_table_association(raw):
    customer_fields = [f for f in raw.fields if f["table_name"] == "Customer"]
    invoice_fields = [f for f in raw.fields if f["table_name"] == "Invoice"]
    assert len(customer_fields) == 5
    assert len(invoice_fields) == 4


def test_field_data_types(raw):
    fullname = next(f for f in raw.fields if f["name"] == "FullName")
    assert fullname["field_type"] == "Calculation"
    assert fullname["data_type"] == "Text"
    assert "FirstName" in (fullname["calculation"] or "")

    amount = next(f for f in raw.fields if f["name"] == "Amount")
    assert amount["data_type"] == "Number"


def test_field_storage(raw):
    amount = next(f for f in raw.fields if f["name"] == "Amount")
    assert amount["storage"]["indexed"] is False

    cid = next(f for f in raw.fields if f["name"] == "CustomerID")
    assert cid["storage"]["indexed"] is True


def test_field_auto_enter(raw):
    cid = next(f for f in raw.fields if f["name"] == "CustomerID")
    assert cid["auto_enter"]["type"] == "serial"

    status = next(f for f in raw.fields if f["name"] == "Status")
    assert status["auto_enter"]["type"] == "data"
    assert status["auto_enter"]["value"] == "Active"


def test_field_validation(raw):
    last_name = next(f for f in raw.fields if f["name"] == "LastName")
    assert last_name["validation"]["not_empty"] is True


def test_table_occurrences_extracted(raw):
    assert len(raw.table_occurrences) == 3
    names = {t["name"] for t in raw.table_occurrences}
    assert "Customer" in names
    assert "Invoice" in names
    assert "Invoice__Customer" in names


def test_relationships_extracted(raw):
    assert len(raw.relationships) == 1
    rel = raw.relationships[0]
    assert rel["name"] == "Customer_to_Invoice"
    assert rel["left_table_name"] == "Customer"
    assert rel["right_table_name"] == "Invoice"
    assert len(rel["predicates"]) == 1
    pred = rel["predicates"][0]
    assert pred["left_field_name"] == "CustomerID"
    assert pred["right_field_name"] == "CustomerFK"
    assert pred["operator"] == "="


def test_layouts_extracted(raw):
    assert len(raw.layouts) == 2
    names = {l["name"] for l in raw.layouts}
    assert "Customer List" in names
    assert "Invoice Detail" in names


def test_layout_field_references(raw):
    customer_list = next(l for l in raw.layouts if l["name"] == "Customer List")
    field_names = {ref["field_name"] for ref in customer_list["referenced_fields"]}
    assert "CustomerID" in field_names
    assert "FullName" in field_names
    assert "Status" in field_names


def test_scripts_extracted(raw):
    assert len(raw.scripts) == 3
    names = {s["name"] for s in raw.scripts}
    assert "Create Customer" in names
    assert "Post Invoice" in names


def test_script_folder_path(raw):
    create = next(s for s in raw.scripts if s["name"] == "Create Customer")
    assert create["folder_path"] == "Customer Scripts"

    post_invoice = next(s for s in raw.scripts if s["name"] == "Post Invoice")
    assert post_invoice["folder_path"] is None


def test_script_steps_extracted(raw):
    create = next(s for s in raw.scripts if s["name"] == "Create Customer")
    assert len(create["steps"]) == 3
    step0 = create["steps"][0]
    assert step0["name"] == "Go to Layout"
    assert step0["layout_ref"]["name"] == "Customer List"


def test_custom_functions_extracted(raw):
    assert len(raw.custom_functions) == 1
    cf = raw.custom_functions[0]
    assert cf["name"] == "FormatCurrency"
    assert cf["parameters"] == ["amount"]
    assert "Round" in cf["calculation"]


def test_value_lists_extracted(raw):
    assert len(raw.value_lists) == 1
    vl = raw.value_lists[0]
    assert vl["name"] == "CustomerStatus"
    assert vl["list_type"] == "customValues"
    assert "Active" in vl["values"]
    assert "Inactive" in vl["values"]


def test_no_parse_warnings(raw):
    assert raw.parse_warnings == []
