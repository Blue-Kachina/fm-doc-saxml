"""Tests for the structural diff engine (analyze/diff.py)."""

from pathlib import Path
import pytest

from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.analyze.diff import compute_diff

FIXTURES = Path(__file__).parent / "fixtures"


def _build_model(filename: str):
    raw = parse_savexml(FIXTURES / filename)
    m = normalize(raw)
    m = resolve_references(m)
    m = generate_backlinks(m)
    return m


@pytest.fixture(scope="module")
def old_model():
    return _build_model("small_sample.xml")


@pytest.fixture(scope="module")
def new_model():
    return _build_model("small_sample_v2.xml")


@pytest.fixture(scope="module")
def result(old_model, new_model):
    return compute_diff(old_model, new_model)


def _type_diff(result, entity_type: str):
    return next(t for t in result.types if t.entity_type == entity_type)


def test_identical_models_produce_no_diff(old_model):
    same = compute_diff(old_model, old_model)
    assert not same.has_changes
    assert same.total_added == same.total_removed == same.total_changed == 0
    assert same.script_step_diffs == []


def test_added_field_detected(result):
    fields = _type_diff(result, "field")
    added_names = {e.name for e in fields.added}
    assert "Invoice::Notes" in added_names


def test_removed_field_detected(result):
    fields = _type_diff(result, "field")
    removed_names = {e.name for e in fields.removed}
    assert "Invoice::InvoiceDate" in removed_names


def test_changed_field_detected(result):
    fields = _type_diff(result, "field")
    changed = {c.name: c for c in fields.changed}
    assert "Customer::LastName" in changed
    validation_change = next(
        fc for fc in changed["Customer::LastName"].changes if fc.field == "validation"
    )
    assert validation_change.old != validation_change.new


def test_same_size_list_field_shows_membership_delta_not_just_count(result):
    """Invoice's `fields` list is 4 items in both old and new (one removed,
    one added) — a naive count comparison would make that look unchanged."""
    tables = _type_diff(result, "table")
    invoice_change = next(c for c in tables.changed if c.name == "Invoice")
    fields_change = next(fc for fc in invoice_change.changes if fc.field == "fields")
    assert fields_change.old == "4 item(s)"
    assert "+1" in fields_change.new
    assert "-1" in fields_change.new


def test_removed_script_detected(result):
    scripts = _type_diff(result, "script")
    removed_names = {e.name for e in scripts.removed}
    assert "Delete Customer" in removed_names


def test_added_layout_object_detected(result):
    layout_objects = _type_diff(result, "layoutObject")
    assert len(layout_objects.added) >= 1


def test_value_list_values_change_is_a_change_not_add_remove(result):
    value_lists = _type_diff(result, "valueList")
    assert value_lists.added == []
    assert value_lists.removed == []
    changed_names = {c.name for c in value_lists.changed}
    assert "CustomerStatus" in changed_names


def test_script_step_diff_is_position_tolerant(result):
    """'Create Customer' gained one step in the middle of its list — a naive
    index-keyed diff would show every step from that point on as
    removed+added. The content-based diff should report just +1."""
    step_diff = next(d for d in result.script_step_diffs if d.script_name == "Create Customer")
    assert step_diff.old_count == 3
    assert step_diff.new_count == 4
    assert step_diff.added == 1
    assert step_diff.removed == 0


def test_deleted_script_has_no_step_diff_entry(result):
    """A script that no longer exists in `new` shouldn't appear in
    script_step_diffs — it's already reported as a removed script."""
    names = {d.script_name for d in result.script_step_diffs}
    assert "Delete Customer" not in names


def test_diff_is_direction_sensitive(old_model, new_model):
    """Comparing new -> old should invert added/removed."""
    forward = compute_diff(old_model, new_model)
    backward = compute_diff(new_model, old_model)
    assert forward.total_added == backward.total_removed
    assert forward.total_removed == backward.total_added
