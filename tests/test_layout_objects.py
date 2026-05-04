"""Tests for layout-object extraction (v2 SaveAsXML format).

These tests cover the new ``LayoutObjectEntity`` and the field-discovery fix:
prior to the fix, an export with no v1-style ``<Object type="FieldObj">``
elements (which is the case for every modern SaveAsXML v2 file) produced
zero detected layout fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.normalize.normalize import normalize


V2_LAYOUT_FIXTURE = """<?xml version="1.0"?>
<FMSaveAsXML version="2.2.3.0" Source="22.0.6" File="LayoutObjectTest.fmp12">
  <Structure membercount="1">
    <AddAction membercount="1">
      <BaseTableCatalog membercount="1">
        <BaseTable id="129" name="Contacts">
          <UUID>00000000-0000-0000-0000-000000000001</UUID>
        </BaseTable>
      </BaseTableCatalog>
      <TableOccurrenceCatalog membercount="1">
        <TableOccurrence id="1065089" name="Contacts" type="Local">
          <UUID>00000000-0000-0000-0000-000000000002</UUID>
          <BaseTableSourceReference type="BaseTableReference">
            <BaseTableReference id="129" name="Contacts" UUID="00000000-0000-0000-0000-000000000001"/>
          </BaseTableSourceReference>
        </TableOccurrence>
      </TableOccurrenceCatalog>
      <FieldsForTables membercount="1">
        <FieldCatalog>
          <BaseTableReference id="129" name="Contacts" UUID="00000000-0000-0000-0000-000000000001"/>
          <ObjectList membercount="1">
            <Field id="6" name="firstName" fieldtype="Normal" datatype="Text">
              <UUID>00000000-0000-0000-0000-000000000003</UUID>
            </Field>
          </ObjectList>
        </FieldCatalog>
      </FieldsForTables>
      <LayoutCatalog membercount="1">
        <Layout id="1" name="ContactDetail" width="1024">
          <TableOccurrenceReference id="1065089" name="Contacts" UUID="00000000-0000-0000-0000-000000000002"/>
          <PartsList membercount="1">
            <Part type="Body" kind="4">
              <Definition type="Body" kind="4" size="500" absolute="0"/>
              <ObjectList membercount="2">
                <LayoutObject id="1" type="Text" name="" kind="2">
                  <UUID>AAAAAAAA-0000-0000-0000-000000000001</UUID>
                  <Bounds top="10" left="10" bottom="30" right="100"/>
                  <Text>
                    <StyledText>
                      <Data><![CDATA[First name]]></Data>
                    </StyledText>
                  </Text>
                </LayoutObject>
                <LayoutObject id="2" type="Edit Box" name="firstNameInput" kind="1">
                  <UUID>AAAAAAAA-0000-0000-0000-000000000002</UUID>
                  <Bounds top="10" left="120" bottom="30" right="320"/>
                  <Field>
                    <FieldReference id="6" name="firstName" repetition="1" UUID="00000000-0000-0000-0000-000000000003">
                      <TableOccurrenceReference id="1065089" name="Contacts" UUID="00000000-0000-0000-0000-000000000002"/>
                    </FieldReference>
                  </Field>
                </LayoutObject>
              </ObjectList>
            </Part>
          </PartsList>
        </Layout>
      </LayoutCatalog>
    </AddAction>
  </Structure>
</FMSaveAsXML>
"""


@pytest.fixture
def fixture_path(tmp_path):
    p = tmp_path / "layout_objects.xml"
    p.write_text(V2_LAYOUT_FIXTURE, encoding="utf-8")
    return p


@pytest.fixture
def raw(fixture_path):
    return parse_savexml(fixture_path)


@pytest.fixture
def model(raw, fixture_path):
    return normalize(raw, source_file=str(fixture_path), source_path=fixture_path)


# ---------------------------------------------------------------------------
# Raw-extractor level
# ---------------------------------------------------------------------------

def test_layout_extracted(raw):
    assert len(raw.layouts) == 1
    assert raw.layouts[0]["name"] == "ContactDetail"


def test_layout_objects_present_in_raw(raw):
    objects = raw.layouts[0]["layout_objects"]
    assert len(objects) == 2
    types = [o["type"] for o in objects]
    assert "Text" in types
    assert "Edit Box" in types


def test_layout_object_text_has_raw_text(raw):
    text_obj = next(o for o in raw.layouts[0]["layout_objects"] if o["type"] == "Text")
    assert text_obj["raw_text"] == "First name"


def test_layout_object_edit_box_has_field_reference(raw):
    edit_obj = next(o for o in raw.layouts[0]["layout_objects"] if o["type"] == "Edit Box")
    assert edit_obj["field"] is not None
    assert edit_obj["field"]["field_name"] == "firstName"
    assert edit_obj["field"]["table_name"] == "Contacts"
    assert edit_obj["field"]["to_id"] == "1065089"


def test_layout_object_bounds(raw):
    edit_obj = next(o for o in raw.layouts[0]["layout_objects"] if o["type"] == "Edit Box")
    assert edit_obj["bounds"] == {"top": 10.0, "left": 120.0, "bottom": 30.0, "right": 320.0}


def test_layout_object_part_label(raw):
    objs = raw.layouts[0]["layout_objects"]
    assert all(o["part"] == "Body" for o in objs)


def test_referenced_fields_derived_from_layout_objects(raw):
    """The referenced_fields shortcut list should still be populated for v2."""
    refs = raw.layouts[0]["referenced_fields"]
    assert any(r["field_name"] == "firstName" and r["table_name"] == "Contacts" for r in refs)


# ---------------------------------------------------------------------------
# Normalized model
# ---------------------------------------------------------------------------

def test_layout_objects_in_model(model):
    assert len(model.entities.layout_objects) == 2


def test_layout_carries_layout_object_doc_ids(model):
    layout = next(iter(model.entities.layouts.values()))
    assert len(layout.layout_objects) == 2


def test_layout_referenced_fields_resolved(model):
    """The 0-fields-detected bug: layout fields must resolve to docIds."""
    layout = next(iter(model.entities.layouts.values()))
    assert len(layout.referenced_fields) == 1
    fd = layout.referenced_fields[0]
    assert fd in model.entities.fields
    assert model.entities.fields[fd].name == "firstName"


def test_layout_object_field_doc_id_resolves(model):
    edit = next(
        o for o in model.entities.layout_objects.values() if o.object_type == "Edit Box"
    )
    assert edit.field_doc_id is not None
    assert edit.field_doc_id in model.entities.fields


def test_layout_object_table_occurrence_doc_id_resolves(model):
    edit = next(
        o for o in model.entities.layout_objects.values() if o.object_type == "Edit Box"
    )
    assert edit.table_occurrence_doc_id is not None
    assert edit.table_occurrence_doc_id in model.entities.table_occurrences


def test_layout_object_text_object_has_no_field(model):
    text = next(
        o for o in model.entities.layout_objects.values() if o.object_type == "Text"
    )
    assert text.field_doc_id is None
    assert text.raw_text == "First name"


# ---------------------------------------------------------------------------
# Source modified-at timestamp
# ---------------------------------------------------------------------------

def test_source_modified_at_populated(model):
    assert model.source.source_modified_at is not None
