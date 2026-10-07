"""Calculations everywhere — fields, custom functions, layouts, layout objects, custom
menus — are linked through their DDR_INFO ChunkLists, along with the structure that
holds them: nested layout objects, script triggers, single-step buttons and portals."""

import pytest
from lxml import etree

from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.parser.extractors.fields import _parse_auto_enter
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references


def _to(id_, name, table_id, table):
    return f"""<TableOccurrence id="{id_}" name="{name}" type="Local"><BaseTableSourceReference type="BaseTableReference">
      <BaseTableReference id="{table_id}" name="{table}"/></BaseTableSourceReference></TableOccurrence>"""


def _fref(id_, name, to_id, to):
    return f'<FieldReference id="{id_}" name="{name}" repetition="1"><TableOccurrenceReference id="{to_id}" name="{to}"/></FieldReference>'


def _calc(key, text):
    return f'<Calculation><DDRREF kind="ChunkList">{key}</DDRREF><Text><![CDATA[{text}]]></Text></Calculation>'


TOTAL = _fref(1, "total", 100, "INV")
NOTE = _fref(2, "note", 100, "INV")
QTY = _fref(1, "qty", 200, "inv__LINE")


def _chunks(key, *chunks):
    return f"<{key}><ChunkList>{''.join(chunks)}</ChunkList></{key}>"


def _field_chunk(ref):
    return f'<Chunk type="FieldRef">{ref}</Chunk>'


TWICE = '<Chunk type="CustomFunctionRef">Twice</Chunk>'
NOREF = '<Chunk type="NoRef"> + 1 </Chunk>'

XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<FMSaveAsXML version="2.2.3.0" Source="22.0.6" File="T.fmp12" UUID="F">
<Structure><AddAction>
  <BaseTableCatalog><BaseTable id="1" name="Inv"/><BaseTable id="2" name="Line"/></BaseTableCatalog>
  <TableOccurrenceCatalog>{_to(100, "INV", 1, "Inv")}{_to(200, "inv__LINE", 2, "Line")}</TableOccurrenceCatalog>
  <CustomFunctionsCatalog><ObjectList><CustomFunction id="1" name="Twice"><ObjectList><Parameter name="n"/></ObjectList></CustomFunction></ObjectList></CustomFunctionsCatalog>
  <FieldsForTables>
    <FieldCatalog><BaseTableReference id="1" name="Inv"/><ObjectList>
      <Field id="1" name="total" fieldtype="Normal" datatype="Number"/>
      <Field id="2" name="note" fieldtype="Normal" datatype="Text"/>
      <Field id="3" name="stamp" fieldtype="Normal" datatype="Number">
        <AutoEnter type="Calculated"><Calculated>{_calc("_ae", "Twice ( INV::total )")}</Calculated></AutoEnter>
      </Field>
      <Field id="4" name="calc" fieldtype="Calculated" datatype="Number">
        {_calc("_fc", "INV::total + 1 // INV::note")}
      </Field>
    </ObjectList></FieldCatalog>
    <FieldCatalog><BaseTableReference id="2" name="Line"/><ObjectList>
      <Field id="1" name="qty" fieldtype="Normal" datatype="Number"/>
    </ObjectList></FieldCatalog>
  </FieldsForTables>
  <CalcsForCustomFunctions><ObjectList><CustomFunctionCalc>
    <CustomFunctionReference id="1" name="Twice"/>{_calc("_cf", "// Twice ( n )&#13;n * 2")}
  </CustomFunctionCalc></ObjectList></CalcsForCustomFunctions>
  <ScriptCatalog><Script id="1" name="Go"/></ScriptCatalog>
  <LayoutCatalog>
    <Layout id="1" name="Inv Detail">
      <TableOccurrenceReference id="100" name="INV"/>
      <ScriptTriggers><ScriptTrigger action="OnLayoutEnter"><ScriptReference id="1" name="Go">{_calc("_lt", "INV::note")}</ScriptReference></ScriptTrigger></ScriptTriggers>
      <PartsList><Part type="Body"><ObjectList>
        <LayoutObject id="5" type="Button">
          <Button><action><ScriptReference id="1" name="Go"/>{_calc("_bp", "INV::total")}</action></Button>
          <Conditions><Hide>{_calc("_hide", "Twice ( 1 ) = 2")}</Hide></Conditions>
          <ScriptTriggers><ScriptTrigger action="OnObjectEnter"><ScriptReference id="1" name="Go"/></ScriptTrigger></ScriptTriggers>
        </LayoutObject>
        <LayoutObject id="6" type="Portal">
          <Portal><TableOccurrenceReference id="200" name="inv__LINE"/>
            <SortSpecification><SortList><Sort><PrimaryField>{QTY}</PrimaryField></Sort></SortList></SortSpecification>
            <ObjectList>
              <LayoutObject id="7" type="Edit Box"><Field>{QTY}</Field><Tooltip>{_calc("_tip", "INV::note")}</Tooltip></LayoutObject>
            </ObjectList>
          </Portal>
        </LayoutObject>
        <LayoutObject id="8" type="Button"><Button><action>
          <Step index="0" id="6" name="Go to Layout"><ParameterValues><Parameter type="LayoutReferenceContainer">
            <LayoutReferenceContainer><LayoutReference id="1" name="Inv Detail"/></LayoutReferenceContainer>
          </Parameter></ParameterValues></Step>
        </action></Button></LayoutObject>
      </ObjectList></Part></PartsList>
    </Layout>
  </LayoutCatalog>
  <CustomMenuCatalog><CustomMenu id="1" name="Main"><Conditions><Install>{_calc("_menu", "INV::note")}</Install></Conditions></CustomMenu></CustomMenuCatalog>
</AddAction></Structure>
<DDR_INFO><Calculation><ObjectList>
  {_chunks("_ae", TWICE, _field_chunk(TOTAL))}
  {_chunks("_fc", _field_chunk(TOTAL), NOREF, '<Chunk type="Comment">// INV::note</Chunk>')}
  {_chunks("_cf", '<Chunk type="Comment">// Twice ( n )</Chunk>', '<Chunk type="VariableReference">n</Chunk>')}
  {_chunks("_lt", _field_chunk(NOTE))}
  {_chunks("_bp", _field_chunk(TOTAL))}
  {_chunks("_hide", TWICE, NOREF)}
  {_chunks("_tip", _field_chunk(NOTE))}
  {_chunks("_menu", _field_chunk(NOTE))}
</ObjectList></Calculation></DDR_INFO>
</FMSaveAsXML>"""


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    path = tmp_path_factory.mktemp("x") / "t.xml"
    path.write_text(XML, encoding="utf-8")
    return resolve_references(normalize(parse_savexml(path), "t.xml"))


def _refs(model, source):
    return {(r.target_doc_id, r.role, r.confidence) for r in model.references if r.source_doc_id == source}


def test_field_formula_and_v2_auto_enter_link_through_chunk_lists(model):
    stamp = model.entities.fields["field:Inv::stamp"]
    assert stamp.auto_enter.type == "calculation"
    assert stamp.auto_enter.calculation == "Twice ( INV::total )"
    assert _refs(model, "field:Inv::stamp") == {
        ("customFunction:Twice", "autoEnter", "exact"),
        ("field:Inv::total", "autoEnter", "exact"),
    }
    # The commented-out INV::note is a Comment chunk, not a reference
    assert _refs(model, "field:Inv::calc") == {("field:Inv::total", "calculation", "exact")}


def test_custom_function_doc_comment_is_not_a_self_call(model):
    assert _refs(model, "customFunction:Twice") == set()


def test_layout_script_trigger_and_its_parameter(model):
    assert _refs(model, "layout:Inv Detail") >= {
        ("script:Go", "OnLayoutEnter", "exact"),
        ("field:Inv::note", "scriptTriggerParameter", "exact"),
    }


def test_layout_object_calcs_triggers_and_button_script(model):
    obj = "layoutObject:Inv Detail::5"
    assert [c.role for c in model.entities.layout_objects[obj].calculations] == ["buttonParameter", "hideCondition"]
    assert _refs(model, obj) == {
        ("script:Go", "button", "exact"),
        ("script:Go", "OnObjectEnter", "exact"),
        ("field:Inv::total", "buttonParameter", "exact"),
        ("customFunction:Twice", "hideCondition", "exact"),
    }
    # ...and rolled up to the layout
    assert ("customFunction:Twice", "hideCondition", "exact") in _refs(model, "layout:Inv Detail")


def test_portal_contents_are_collected_and_linked(model):
    portal = model.entities.layout_objects["layoutObject:Inv Detail::6"]
    inner = model.entities.layout_objects["layoutObject:Inv Detail::7"]
    assert portal.table_occurrence_doc_id == "to:inv__LINE"
    assert inner.parent_object_doc_id == portal.doc_id
    assert inner.field_doc_id == "field:Line::qty"
    assert ("field:Line::qty", "portalSort", "exact") in _refs(model, portal.doc_id)
    assert ("field:Inv::note", "tooltip", "exact") in _refs(model, inner.doc_id)
    assert "field:Line::qty" in model.entities.layouts["layout:Inv Detail"].referenced_fields


def test_single_step_button_links_its_target(model):
    obj = model.entities.layout_objects["layoutObject:Inv Detail::8"]
    assert obj.button_step == "Go to Layout [ Inv Detail ]"
    assert _refs(model, obj.doc_id) == {("layout:Inv Detail", "buttonAction", "exact")}


def test_custom_menu_install_condition(model):
    assert _refs(model, "customMenu:Main") == {("field:Inv::note", "installCondition", "exact")}


def test_no_unresolved_references(model):
    assert [r for r in model.references if r.confidence == "unresolved"] == []


@pytest.mark.parametrize("xml, expected", [
    ('<AutoEnter type="ConstantData"><ConstantData>1</ConstantData></AutoEnter>', ("data", "1")),
    ('<AutoEnter type="SerialNumber"><SerialNumber increment="1"/></AutoEnter>', ("serial", None)),
    ('<AutoEnter type="CreationTimestamp"/>', ("creation", "Timestamp")),
    ('<AutoEnter type="ModificationAccountName"/>', ("modification", "AccountName")),
])
def test_v2_auto_enter_types(xml, expected):
    ae = _parse_auto_enter(etree.fromstring(xml))
    assert (ae["type"], ae["value"]) == expected
