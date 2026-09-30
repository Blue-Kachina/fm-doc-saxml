"""UNRESOLVED_TO_TABLE must not fire for table occurrences whose base table
is legitimately external (type="External" in the raw XML) — only for ones
where the base table is genuinely missing/unresolvable.
"""

import pytest

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.normalize.normalize import normalize
from fm_saxml.model.validation import validate_model


def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "1", "name": "Local"}]
    raw.table_occurrences = [
        {"id": "10", "name": "Local", "base_table_id": "1"},
        {
            "id": "11", "name": "idiClients",
            "external_data_source": "idiClients",
            "external_base_table": "idiClients",
        },
        {"id": "12", "name": "Orphan", "base_table_id": "999"},
    ]
    return raw


@pytest.fixture
def model():
    m = normalize(_raw())
    return validate_model(m)


def test_external_to_is_not_flagged_unresolved(model):
    flagged = {w.entity_doc_id for w in model.warnings if w.code == "UNRESOLVED_TO_TABLE"}
    assert "to:idiClients" not in flagged


def test_external_to_has_no_local_base_table_doc_id(model):
    to = model.entities.table_occurrences["to:idiClients"]
    assert to.base_table_doc_id == ""
    assert to.external_data_source == "idiClients"


def test_genuinely_missing_base_table_is_still_flagged(model):
    flagged = {w.entity_doc_id for w in model.warnings if w.code == "UNRESOLVED_TO_TABLE"}
    assert "to:Orphan" in flagged


def test_resolved_local_to_is_not_flagged(model):
    flagged = {w.entity_doc_id for w in model.warnings if w.code == "UNRESOLVED_TO_TABLE"}
    assert "to:Local" not in flagged
