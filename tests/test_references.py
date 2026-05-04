"""Tests for reference resolution and backlink generation."""

from pathlib import Path
import pytest

from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


@pytest.fixture
def model():
    raw = parse_savexml(FIXTURE)
    m = normalize(raw)
    m = resolve_references(m)
    m = generate_backlinks(m)
    return m


def test_field_to_table_references(model):
    """Table should contain fields via 'contains' references."""
    contains_refs = [
        r for r in model.references
        if r.relationship_type == "contains" and r.source_doc_id == "table:Customer"
    ]
    assert len(contains_refs) == 5  # 5 Customer fields


def test_to_base_table_reference(model):
    to_table_refs = [
        r for r in model.references
        if r.relationship_type == "basedOnBaseTable" and r.source_doc_id == "to:Customer"
    ]
    assert len(to_table_refs) == 1
    assert to_table_refs[0].target_doc_id == "table:Customer"


def test_relationship_joins_to_refs(model):
    rel_refs = [
        r for r in model.references
        if r.source_doc_id == "relationship:Customer_to_Invoice" and r.relationship_type == "joinsTo"
    ]
    to_doc_ids = {r.target_doc_id for r in rel_refs}
    assert "to:Customer" in to_doc_ids
    assert "to:Invoice" in to_doc_ids


def test_relationship_predicate_field_refs(model):
    field_refs = [
        r for r in model.references
        if r.source_doc_id == "relationship:Customer_to_Invoice" and r.relationship_type == "usesField"
    ]
    field_doc_ids = {r.target_doc_id for r in field_refs}
    assert "field:Customer::CustomerID" in field_doc_ids
    assert "field:Invoice::CustomerFK" in field_doc_ids


def test_layout_based_on_to(model):
    layout_to_refs = [
        r for r in model.references
        if r.source_doc_id == "layout:Customer List" and r.relationship_type == "basedOnTableOccurrence"
    ]
    assert len(layout_to_refs) == 1
    assert layout_to_refs[0].target_doc_id == "to:Customer"


def test_layout_field_refs(model):
    layout_field_refs = [
        r for r in model.references
        if r.source_doc_id == "layout:Customer List" and r.relationship_type == "usesField"
    ]
    field_doc_ids = {r.target_doc_id for r in layout_field_refs}
    assert "field:Customer::CustomerID" in field_doc_ids


def test_backlinks_generated(model):
    # Customer table should have backlinks from its table occurrences
    bl = model.backlinks.get("table:Customer", [])
    assert len(bl) > 0

    # Customer::CustomerID should have backlinks from the relationship
    bl_cid = model.backlinks.get("field:Customer::CustomerID", [])
    assert len(bl_cid) > 0


def test_backlinks_contain_relationship_ref(model):
    bl = model.backlinks.get("field:Customer::CustomerID", [])
    rel_refs = [b for b in bl if b["sourceDocId"] == "relationship:Customer_to_Invoice"]
    assert len(rel_refs) > 0


def test_backlinks_contain_layout_ref(model):
    bl = model.backlinks.get("field:Customer::CustomerID", [])
    layout_refs = [b for b in bl if b["sourceDocId"] == "layout:Customer List"]
    assert len(layout_refs) > 0
