"""Tests for the normalization layer."""

from pathlib import Path
import pytest

from fm_docgen.parser.saxml_reader import parse_savexml
from fm_docgen.normalize.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


@pytest.fixture
def model():
    raw = parse_savexml(FIXTURE)
    return normalize(raw)


def test_tables_normalized(model):
    assert "table:Customer" in model.entities.tables
    assert "table:Invoice" in model.entities.tables


def test_table_entity_shape(model):
    customer = model.entities.tables["table:Customer"]
    assert customer.name == "Customer"
    assert customer.entity_type == "table"
    assert customer.doc_id == "table:Customer"
    assert customer.fmp_id == "1"


def test_fields_normalized(model):
    assert "field:Customer::CustomerID" in model.entities.fields
    assert "field:Customer::FullName" in model.entities.fields
    assert "field:Invoice::Amount" in model.entities.fields


def test_field_entity_shape(model):
    cid = model.entities.fields["field:Customer::CustomerID"]
    assert cid.name == "CustomerID"
    assert cid.qualified_name == "Customer::CustomerID"
    assert cid.base_table_doc_id == "table:Customer"
    assert cid.data_type == "Text"
    assert cid.field_type == "Normal"
    assert cid.storage.indexed is True


def test_field_calculation(model):
    fullname = model.entities.fields["field:Customer::FullName"]
    assert fullname.field_type == "Calculation"
    assert fullname.calculation is not None
    assert "FirstName" in fullname.calculation


def test_fields_linked_to_table(model):
    customer = model.entities.tables["table:Customer"]
    assert "field:Customer::CustomerID" in customer.fields
    assert "field:Customer::FullName" in customer.fields
    assert len(customer.fields) == 5


def test_table_occurrences_normalized(model):
    assert "to:Customer" in model.entities.table_occurrences
    assert "to:Invoice" in model.entities.table_occurrences
    assert "to:Invoice__Customer" in model.entities.table_occurrences


def test_to_base_table_resolved(model):
    customer_to = model.entities.table_occurrences["to:Customer"]
    assert customer_to.base_table_doc_id == "table:Customer"


def test_relationship_normalized(model):
    assert "relationship:Customer_to_Invoice" in model.entities.relationships
    rel = model.entities.relationships["relationship:Customer_to_Invoice"]
    assert rel.name == "Customer_to_Invoice"
    assert rel.left_table_occurrence_doc_id == "to:Customer"
    assert rel.right_table_occurrence_doc_id == "to:Invoice"
    assert len(rel.predicates) == 1
    pred = rel.predicates[0]
    assert pred.left_field_doc_id == "field:Customer::CustomerID"
    assert pred.right_field_doc_id == "field:Invoice::CustomerFK"
    assert pred.operator == "="


def test_layouts_normalized(model):
    assert "layout:Customer List" in model.entities.layouts
    assert "layout:Invoice Detail" in model.entities.layouts


def test_layout_to_resolved(model):
    customer_list = model.entities.layouts["layout:Customer List"]
    assert customer_list.base_table_occurrence_doc_id == "to:Customer"


def test_layout_field_refs(model):
    customer_list = model.entities.layouts["layout:Customer List"]
    assert "field:Customer::CustomerID" in customer_list.referenced_fields
    assert "field:Customer::FullName" in customer_list.referenced_fields


def test_scripts_normalized(model):
    assert "script:Create Customer" in model.entities.scripts
    assert "script:Post Invoice" in model.entities.scripts


def test_script_steps_normalized(model):
    create = model.entities.scripts["script:Create Customer"]
    assert len(create.steps) == 3
    step0 = model.entities.script_steps[create.steps[0]]
    assert step0.name == "Go to Layout"


def test_script_folder_path(model):
    create = model.entities.scripts["script:Create Customer"]
    assert create.folder_path == "Customer Scripts"

    post = model.entities.scripts["script:Post Invoice"]
    assert post.folder_path is None


def test_custom_functions_normalized(model):
    assert "customFunction:FormatCurrency" in model.entities.custom_functions
    cf = model.entities.custom_functions["customFunction:FormatCurrency"]
    assert cf.parameters == ["amount"]
    assert "Round" in cf.calculation


def test_value_lists_normalized(model):
    assert "valueList:CustomerStatus" in model.entities.value_lists
    vl = model.entities.value_lists["valueList:CustomerStatus"]
    assert "Active" in vl.values
    assert len(vl.values) == 3


def test_no_critical_parse_warnings(model):
    critical = [w for w in model.warnings if w.code == "PARSE_WARNING"]
    assert critical == []
