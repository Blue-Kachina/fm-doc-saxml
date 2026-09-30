"""Tests for analysis-phase warnings."""

from pathlib import Path
import pytest

from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.analyze.warnings import generate_warnings

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


@pytest.fixture
def model():
    raw = parse_savexml(FIXTURE)
    m = normalize(raw)
    m = resolve_references(m)
    m = generate_backlinks(m)
    m = generate_warnings(m)
    return m


def _unused_field_doc_ids(model) -> set[str]:
    return {
        w.entity_doc_id
        for w in model.warnings
        if w.code == "UNUSED_FIELD_CANDIDATE"
    }


def test_every_field_has_a_structural_contains_backlink(model):
    """Sanity check on the fixture: every field is 'contains'-linked from its
    table regardless of usage — this is what made the old (pre-fix) check a
    no-op, since it treated any backlink at all as evidence of use."""
    for field in model.entities.fields.values():
        bl = model.backlinks.get(field.doc_id, [])
        assert any(b["relationshipType"] == "contains" for b in bl)


def test_field_used_only_via_relationship_and_layout_is_not_flagged(model):
    assert "field:Customer::CustomerID" not in _unused_field_doc_ids(model)


def test_field_used_only_via_script_step_is_not_flagged(model):
    # Customer::Status is set by a "Set Field" step in the "Create Customer" script.
    assert "field:Customer::Status" not in _unused_field_doc_ids(model)


def test_field_used_only_via_layout_is_not_flagged(model):
    assert "field:Customer::FullName" not in _unused_field_doc_ids(model)
    assert "field:Invoice::InvoiceID" not in _unused_field_doc_ids(model)
    assert "field:Invoice::Amount" not in _unused_field_doc_ids(model)


def test_field_used_only_via_relationship_predicate_is_not_flagged(model):
    assert "field:Invoice::CustomerFK" not in _unused_field_doc_ids(model)


def test_genuinely_unreferenced_field_is_flagged(model):
    # Invoice::InvoiceDate never appears on a layout, in a script, or in a
    # relationship predicate anywhere in the fixture.
    unused = _unused_field_doc_ids(model)
    assert "field:Invoice::InvoiceDate" in unused


def test_unused_field_warning_message_names_the_field(model):
    msg = next(
        w.message for w in model.warnings
        if w.code == "UNUSED_FIELD_CANDIDATE" and w.entity_doc_id == "field:Invoice::InvoiceDate"
    )
    assert "Invoice::InvoiceDate" in msg
