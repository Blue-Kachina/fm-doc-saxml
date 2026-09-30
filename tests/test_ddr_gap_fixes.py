"""Tests for gaps found by comparing FileMaker's own DDR export against what
fm-saxml-converter extracts from the SaveAsXML export of the same file:

- Field/table `comment` attributes were dropped entirely.
- `<Storage>`'s real max-repetitions attribute is `maxRepetitions`, not
  `maxRepeat`; `index` (None/Minimal/All) and `autoIndex` are two distinct
  attributes that must not be conflated into one boolean.
- A field's `<SummaryField>` source (the field it aggregates) was unparsed.
- A button's triggered script (`<Button><action><ScriptReference/></action>`)
  was completely unparsed — no linkage from button to script at all.
"""

from lxml import etree
import pytest

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.parser.extractors.fields import _parse_field, _parse_storage
from fm_saxml.parser.extractors.tables import _parse_table
from fm_saxml.parser.extractors.layouts import _parse_layout_object
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks


# ---------------------------------------------------------------------------
# Extractor-level: comment, storage
# ---------------------------------------------------------------------------

def test_field_comment_is_extracted():
    elem = etree.fromstring('<Field id="1" name="x" comment="Pour migration/import"/>')
    assert _parse_field(elem, "1", "T")["comment"] == "Pour migration/import"


def test_table_comment_is_extracted():
    elem = etree.fromstring('<BaseTable id="1" name="T" comment="A note"/>')
    assert _parse_table(elem)["comment"] == "A note"


def test_storage_reads_maxRepetitions_not_maxRepeat():
    elem = etree.fromstring('<Storage global="False" index="None" maxRepetitions="9999"/>')
    assert _parse_storage(elem)["maxRepeat"] == 9999


def test_storage_falls_back_to_maxRepeat_for_older_exports():
    elem = etree.fromstring('<Storage global="False" index="None" maxRepeat="5"/>')
    assert _parse_storage(elem)["maxRepeat"] == 5


def test_storage_index_and_autoindex_are_independent():
    elem = etree.fromstring('<Storage global="False" index="Minimal" autoIndex="True" maxRepetitions="1"/>')
    storage = _parse_storage(elem)
    assert storage["index"] == "Minimal"
    assert storage["autoIndex"] is True
    assert storage["indexed"] is True  # Minimal still counts as "indexed"


def test_storage_none_index_is_not_indexed_even_with_autoindex_present():
    elem = etree.fromstring('<Storage global="False" index="None" maxRepetitions="1"/>')
    storage = _parse_storage(elem)
    assert storage["index"] == "None"
    assert storage["autoIndex"] is False
    assert storage["indexed"] is False


# ---------------------------------------------------------------------------
# Extractor-level: button -> script
# ---------------------------------------------------------------------------

def test_button_script_reference_is_extracted():
    lo = etree.fromstring("""
    <LayoutObject id="230" type="Button" name="" kind="10">
      <Bounds top="0" left="0" bottom="10" right="10"/>
      <Button>
        <action>
          <ScriptReference id="134" name="Parametre - Open Manager" UUID="abc"/>
        </action>
      </Button>
    </LayoutObject>""")
    obj = _parse_layout_object(lo, "Body", 0)
    assert obj["button_script"] == {
        "id": "134", "uuid": "abc", "name": "Parametre - Open Manager", "data_source": None,
    }


def test_button_script_reference_detects_external_file():
    lo = etree.fromstring("""
    <LayoutObject id="230" type="Button" name="" kind="10">
      <Button>
        <action>
          <DataSourceReference id="3" name="idiDemandes"/>
          <ScriptReference id="11" name="CreerDevis[]" UUID="xyz"/>
        </action>
      </Button>
    </LayoutObject>""")
    obj = _parse_layout_object(lo, "Body", 0)
    assert obj["button_script"]["data_source"] == "idiDemandes"


def test_non_script_button_has_no_button_script():
    lo = etree.fromstring("""
    <LayoutObject id="1" type="Button" name="" kind="10">
      <Button><action><Options>1</Options></action></Button>
    </LayoutObject>""")
    obj = _parse_layout_object(lo, "Body", 0)
    assert obj["button_script"] is None


def test_non_button_object_has_no_button_script():
    lo = etree.fromstring('<LayoutObject id="1" type="Field" name=""/>')
    obj = _parse_layout_object(lo, "Body", 0)
    assert obj["button_script"] is None


# ---------------------------------------------------------------------------
# End-to-end: normalize + resolve_references + backlinks
# ---------------------------------------------------------------------------

def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "1", "name": "Customer"}]
    raw.fields = [
        {"table_name": "Customer", "name": "FirstName", "id": "1"},
        {"table_name": "Customer", "name": "LastName", "id": "2"},
        {
            "table_name": "Customer", "name": "Count", "id": "3",
            "field_type": "Summary",
            "summary_field": {"name": "FirstName", "table": "Customer"},
        },
        {"table_name": "Customer", "name": "comment_test", "id": "4", "comment": "Pour migration/import"},
    ]
    raw.table_occurrences = [{"id": "1", "name": "Customer", "base_table_id": "1"}]
    raw.scripts = [{"id": "1", "name": "Open Manager", "steps": []}]
    raw.layouts = [{
        "id": "1", "name": "Lic", "table_occurrence_name": "Customer",
        "layout_objects": [
            {
                "id": "10", "type": "Button", "name": "",
                "button_script": {"id": "1", "uuid": None, "name": "Open Manager", "data_source": None},
            },
            {
                "id": "11", "type": "Button", "name": "",
                "button_script": {"id": "2", "uuid": None, "name": "Other File Script", "data_source": "idiDemandes"},
            },
        ],
    }]
    return raw


@pytest.fixture
def model():
    m = normalize(_raw())
    m = resolve_references(m)
    return generate_backlinks(m)


def test_comment_survives_normalization(model):
    assert model.entities.fields["field:Customer::comment_test"].comment == "Pour migration/import"


def test_summary_field_resolves_to_real_field(model):
    count = model.entities.fields["field:Customer::Count"]
    assert count.summary_field_doc_id == "field:Customer::FirstName"


def test_summary_field_creates_backlink_on_summarized_field(model):
    sources = {b["sourceDocId"] for b in model.backlinks.get("field:Customer::FirstName", [])}
    assert "field:Customer::Count" in sources


def test_local_button_script_resolves_exactly(model):
    obj = model.entities.layout_objects["layoutObject:Lic::10"]
    assert obj.button_script_doc_id == "script:Open Manager"
    ref = next(r for r in model.references if r.source_doc_id == obj.doc_id and r.relationship_type == "triggersScript")
    assert ref.confidence == "exact"
    assert ref.target_doc_id == "script:Open Manager"


def test_button_triggered_script_shows_up_as_called_by(model):
    sources = {b["sourceDocId"] for b in model.backlinks.get("script:Open Manager", [])}
    assert "layoutObject:Lic::10" in sources


def test_external_button_script_is_tagged_external_not_unresolved(model):
    obj = model.entities.layout_objects["layoutObject:Lic::11"]
    ref = next(r for r in model.references if r.source_doc_id == obj.doc_id and r.relationship_type == "triggersScript")
    assert ref.confidence == "external"
    assert ref.external_target is not None
    assert ref.external_target.data_source == "idiDemandes"
