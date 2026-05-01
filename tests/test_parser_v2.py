"""Tests for the v2 FMSaveAsXML parser format."""

from pathlib import Path
import pytest
from fm_docgen.parser.saxml_reader import parse_savexml

FIXTURE = Path(__file__).parent / "fixtures" / "v2_sample.xml"


@pytest.fixture
def raw():
    return parse_savexml(FIXTURE)


# ---------------------------------------------------------------------------
# Top-level metadata
# ---------------------------------------------------------------------------

def test_solution_name(raw):
    assert raw.solution_name == "TestSolution"


def test_filemaker_version(raw):
    assert "22" in raw.filemaker_version


def test_no_parse_warnings(raw):
    assert raw.parse_warnings == []


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def test_table_count(raw):
    assert len(raw.tables) == 1


def test_table_name(raw):
    assert raw.tables[0]["name"] == "Contact"


def test_table_id(raw):
    assert raw.tables[0]["id"] == "1"


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def test_field_count(raw):
    assert len(raw.fields) == 3


def test_field_table_association(raw):
    for f in raw.fields:
        assert f["table_name"] == "Contact"
        assert f["table_id"] == "1"


def test_field_names(raw):
    names = {f["name"] for f in raw.fields}
    assert names == {"ContactID", "FullName", "Status"}


def test_field_types_lowercase_attrs(raw):
    contact_id = next(f for f in raw.fields if f["name"] == "ContactID")
    assert contact_id["field_type"] == "Normal"
    assert contact_id["data_type"] == "Number"


def test_calculated_field(raw):
    full_name = next(f for f in raw.fields if f["name"] == "FullName")
    assert full_name["field_type"] == "Calculated"
    assert full_name["data_type"] == "Text"
    assert 'Contact::FirstName' in (full_name["calculation"] or "")


def test_validation_inline_attrs(raw):
    contact_id = next(f for f in raw.fields if f["name"] == "ContactID")
    assert contact_id["validation"] is not None
    assert contact_id["validation"]["not_empty"] is True
    assert contact_id["validation"]["unique"] is True


def test_no_spurious_validation(raw):
    status = next(f for f in raw.fields if f["name"] == "Status")
    assert status["validation"] is None


# ---------------------------------------------------------------------------
# Table occurrences
# ---------------------------------------------------------------------------

def test_to_count(raw):
    assert len(raw.table_occurrences) == 2


def test_to_names(raw):
    names = {t["name"] for t in raw.table_occurrences}
    assert "Contact" in names
    assert "Contact__selfJoin" in names


def test_to_base_table_id_from_child_element(raw):
    for to in raw.table_occurrences:
        assert to["base_table_id"] == "1"


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def test_relationship_count(raw):
    assert len(raw.relationships) == 1


def test_relationship_has_no_name_attr_but_gets_table_names(raw):
    rel = raw.relationships[0]
    assert rel["left_table_name"] == "Contact__selfJoin"
    assert rel["right_table_name"] == "Contact"


def test_relationship_predicate(raw):
    pred = raw.relationships[0]["predicates"][0]
    assert pred["left_field_name"] == "ContactID"
    assert pred["right_field_name"] == "ContactID"
    assert pred["operator"] == "equal"


# ---------------------------------------------------------------------------
# Custom functions
# ---------------------------------------------------------------------------

def test_custom_function_count(raw):
    assert len(raw.custom_functions) == 1


def test_custom_function_name(raw):
    assert raw.custom_functions[0]["name"] == "DoubleIt"


def test_custom_function_parameters_from_child_elements(raw):
    assert raw.custom_functions[0]["parameters"] == ["n"]


def test_custom_function_calc_from_calcs_section(raw):
    assert raw.custom_functions[0]["calculation"] == "n * 2"


# ---------------------------------------------------------------------------
# Value lists
# ---------------------------------------------------------------------------

def test_value_list_count(raw):
    assert len(raw.value_lists) == 2


def test_custom_value_list_values_from_options_section(raw):
    status_list = next(vl for vl in raw.value_lists if vl["name"] == "StatusList")
    assert status_list["list_type"] == "customValues"
    assert set(status_list["values"]) == {"Active", "Inactive", "Prospect"}


def test_from_field_value_list(raw):
    name_list = next(vl for vl in raw.value_lists if vl["name"] == "NameFromField")
    assert name_list["list_type"] == "field"
    assert name_list["source_field"] is not None
    assert name_list["source_field"]["name"] == "Status"


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def test_script_count(raw):
    assert len(raw.scripts) == 1


def test_script_name(raw):
    assert raw.scripts[0]["name"] == "SendEmail"


def test_script_steps_from_steps_section(raw):
    assert len(raw.scripts[0]["steps"]) == 2


def test_script_step_names(raw):
    steps = raw.scripts[0]["steps"]
    assert steps[0]["name"] == "# (comment)"
    assert steps[1]["name"] == "Send Mail"


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------

def test_layout_count(raw):
    assert len(raw.layouts) == 1


def test_layout_name(raw):
    assert raw.layouts[0]["name"] == "ContactDetail"


def test_layout_to_id_from_child_element(raw):
    assert raw.layouts[0]["table_occurrence_id"] == "1048577"
    assert raw.layouts[0]["table_occurrence_name"] == "Contact"


# ---------------------------------------------------------------------------
# Privilege sets
# ---------------------------------------------------------------------------

def test_privilege_set_count(raw):
    assert len(raw.privilege_sets) == 2


def test_privilege_set_names(raw):
    names = {p["name"] for p in raw.privilege_sets}
    assert "[Full Access]" in names
    assert "[Read-Only Access]" in names


def test_privilege_set_description_from_child_element(raw):
    full_access = next(p for p in raw.privilege_sets if p["name"] == "[Full Access]")
    assert full_access["description"] == "access to everything"
