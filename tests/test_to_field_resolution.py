"""Field references made through a renamed table occurrence must still link.

In FileMaker XML the table half of ``Table::Field`` is a *table occurrence*
name, which can differ from the base table's name (here: LICENCE vs Licence).
"""

import pytest

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.analyze.warnings import generate_warnings

FIELD = "field:Licence::total"
FIELD2 = "field:Licence::expiry"
FIELD3 = "field:Licence::unrelated"


def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "1", "name": "Licence"}]
    raw.fields = [
        {"table_name": "Licence", "name": "total", "id": "1"},
        {"table_name": "Licence", "name": "expiry", "id": "2"},
        {"table_name": "Licence", "name": "unrelated", "id": "3"},
        {"table_name": "Licence", "name": "calcd", "id": "4", "field_type": "Calculation",
         "calculation": "LICENCE::unrelated + 1"},
    ]
    raw.table_occurrences = [{"id": "10", "name": "LICENCE", "base_table_id": "1"}]
    raw.layouts = [{
        "id": "20", "name": "Lic", "table_occurrence_name": "LICENCE",
        "referenced_fields": [{"table_name": "LICENCE", "field_name": "total"}],
        "layout_objects": [{
            "id": "5", "type": "Field",
            "field": {"table_name": "LICENCE", "field_name": "total"},
        }],
    }]
    raw.scripts = [{
        "id": "30", "name": "Do",
        "steps": [{
            "index": 0, "step_type_id": "1", "name": "Set Field",
            "field_refs": [{"name": "expiry", "table": "LICENCE"}],
            "calculation": "Get ( CurrentDate ) - LICENCE::total",
        }],
    }]
    raw.value_lists = [{
        "id": "40", "name": "VL", "list_type": "field",
        "source_field": {"name": "total", "table": "LICENCE"},
        "second_field": {"name": "expiry", "table": "LICENCE"},
    }]
    return raw


@pytest.fixture
def model():
    m = normalize(_raw())
    m = resolve_references(m)
    m = generate_backlinks(m)
    return generate_warnings(m)


def test_layout_and_layout_object_resolve_to_real_field(model):
    assert model.entities.layouts["layout:Lic"].referenced_fields == [FIELD]
    assert model.entities.layout_objects["layoutObject:Lic::5"].field_doc_id == FIELD


def test_script_step_field_ref_and_calc_ref_resolve(model):
    script = model.entities.scripts["script:Do"]
    assert FIELD2 in script.referenced_fields
    assert FIELD in script.referenced_fields
    assert all(r["confidence"] != "unresolved" for r in
               (r.model_dump() for r in model.references if r.source_doc_id.startswith("scriptStep")))


def test_value_list_resolves_and_creates_references(model):
    vl = model.entities.value_lists["valueList:VL"]
    assert vl.source_field_doc_id == FIELD
    assert vl.second_field_doc_id == FIELD2
    sources = {b["sourceDocId"] for b in model.backlinks[FIELD]}
    assert "valueList:VL" in sources


def test_field_calculation_creates_reference(model):
    assert any(b["sourceDocId"] == "field:Licence::calcd" for b in model.backlinks[FIELD3])


def test_used_fields_not_flagged_unused(model):
    unused = {w.entity_doc_id for w in model.warnings if w.code == "UNUSED_FIELD_CANDIDATE"}
    assert FIELD not in unused
    assert FIELD2 not in unused
    assert FIELD3 not in unused
    assert not any(w.code == "UNRESOLVED_REFERENCE" for w in model.warnings)


def test_case_insensitive_table_name_match():
    raw = _raw()
    raw.layouts[0]["layout_objects"][0]["field"] = {"table_name": "licence", "field_name": "TOTAL"}
    m = normalize(raw)
    assert m.entities.layout_objects["layoutObject:Lic::5"].field_doc_id == FIELD


# ---------------------------------------------------------------------------
# Value list linkage
# ---------------------------------------------------------------------------

@pytest.fixture
def vl_model():
    raw = _raw()
    raw.layouts[0]["layout_objects"][0]["value_list"] = {"id": "40", "name": "VL"}
    raw.fields[2]["validation"] = {"value_list": "VL"}
    raw.scripts[0]["steps"][0]["value_list_refs"] = [{"id": "40", "name": "VL"}]
    raw.scripts[0]["steps"].append({
        "index": 1, "step_type_id": "2", "name": "Set Variable", "field_refs": [],
        "calculation": 'ValueListItems ( Get ( FileName ) ; "VL" )',
    })
    m = normalize(raw)
    m = resolve_references(m)
    return generate_backlinks(m)


def _sources(model, target):
    return {(b["sourceEntityType"], b["sourceDocId"], b["relationshipType"]) for b in model.backlinks.get(target, [])}


def test_value_list_referenced_by_layout_object_and_layout(vl_model):
    src = _sources(vl_model, "valueList:VL")
    assert ("layoutObject", "layoutObject:Lic::5", "usesValueList") in src
    assert ("layout", "layout:Lic", "usesValueList") in src


def test_value_list_referenced_by_field_validation(vl_model):
    assert ("field", FIELD3, "usesValueList") in _sources(vl_model, "valueList:VL")


def test_value_list_referenced_by_script_steps(vl_model):
    steps = {s for (t, s, r) in _sources(vl_model, "valueList:VL") if t == "scriptStep"}
    assert len(steps) == 2  # one via a step parameter, one via ValueListItems() in a calc
