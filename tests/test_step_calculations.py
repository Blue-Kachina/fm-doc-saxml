"""Script step calculations: kept per parameter, references taken from DDR_INFO ChunkLists."""

import pytest
from lxml import etree

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.parser.extractors.chunk_lists import extract_chunk_lists
from fm_saxml.parser.extractors.scripts import _parse_step
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references

DDR = """
<FMSaveAsXML><DDR_INFO><Calculation><ObjectList>
  <_S1_1 datatype="ChunkList">
    <TableOccurrenceReference id="10" name="LICENCE" UUID="t"/>
    <ChunkList>
      <Chunk type="CustomFunctionRef">Double</Chunk>
      <Chunk type="NoRef"> ( </Chunk>
      <Chunk type="FieldRef"><FieldReference id="1" name="total" repetition="1" UUID="f1">
        <TableOccurrenceReference id="10" name="LICENCE" UUID="t"/></FieldReference></Chunk>
      <Chunk type="NoRef"> ) </Chunk>
      <Chunk type="Comment">// LICENCE::unrelated</Chunk>
    </ChunkList>
  </_S1_1>
  <_S1_2 datatype="ChunkList"><ChunkList><Chunk type="NoRef">2</Chunk></ChunkList></_S1_2>
  <_S2_1 datatype="ChunkList"><ChunkList></ChunkList></_S2_1>
</ObjectList></Calculation></DDR_INFO></FMSaveAsXML>
"""

SET_VARIABLE = """
<Step index="0" id="141" name="Set Variable" enable="True">
  <ParameterValues membercount="1">
    <Parameter type="Variable">
      <value><Calculation datatype="1" position="1"><Calculation>
        <DDRREF kind="ChunkList">_S1_1</DDRREF>
        <Text><![CDATA[Double ( LICENCE::total ) // LICENCE::unrelated]]></Text>
      </Calculation></Calculation></value>
      <Name value="$x"/>
      <repetition><Calculation datatype="1" position="2"><Calculation>
        <DDRREF kind="ChunkList">_S1_2</DDRREF><Text><![CDATA[2]]></Text>
      </Calculation></Calculation></repetition>
    </Parameter>
  </ParameterValues>
</Step>
"""


def test_chunk_lists_keep_field_and_custom_function_refs_only():
    chunks = extract_chunk_lists(etree.fromstring(DDR))
    assert chunks["_S1_1"] == [
        {"type": "customFunction", "name": "Double"},
        {"type": "field", "id": "1", "uuid": "f1", "name": "total", "table": "LICENCE", "table_id": "10"},
    ]
    assert chunks["_S1_2"] == []  # tokenized, but uses nothing
    assert "_S2_1" not in chunks  # empty ChunkList = FileMaker could not tokenize it


def test_step_calculations_are_kept_per_parameter():
    chunks = extract_chunk_lists(etree.fromstring(DDR))
    step = _parse_step(etree.fromstring(SET_VARIABLE), 0, chunks)
    assert [(c["position"], c["parameter"], c["slot"], c["text"]) for c in step["calculations"]] == [
        (1, "Variable", "value", "Double ( LICENCE::total ) // LICENCE::unrelated"),
        (2, "Variable", "repetition", "2"),
    ]
    assert step["calculations"][0]["references"] == chunks["_S1_1"]
    assert step["calculation"] == "Double ( LICENCE::total ) // LICENCE::unrelated\n2"


def test_step_calculation_without_chunk_lists_has_no_references():
    step = _parse_step(etree.fromstring(SET_VARIABLE), 0)
    assert all(c["references"] is None for c in step["calculations"])


def _raw(calculations) -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "1", "name": "Licence"}]
    raw.fields = [
        {"table_name": "Licence", "name": "total", "id": "1"},
        {"table_name": "Licence", "name": "unrelated", "id": "2"},
    ]
    raw.table_occurrences = [{"id": "10", "name": "LICENCE", "base_table_id": "1"}]
    raw.custom_functions = [{"id": "50", "name": "Double", "parameters": ["n"], "calculation": "n * 2"}]
    raw.value_lists = [{"id": "40", "name": "Status", "list_type": "custom", "custom_values": ["A"]}]
    raw.scripts = [{"id": "30", "name": "Do", "steps": [
        {"index": 0, "step_type_id": "141", "name": "Set Variable", "calculations": calculations},
    ]}]
    return raw


def _step_refs(calculations):
    model = resolve_references(normalize(_raw(calculations)))
    step = model.entities.script_steps["scriptStep:Do:0000"]
    return model, step, {(r["kind"], r["targetDocId"]) for r in step.references}


def test_step_references_come_from_chunk_lists():
    text = 'Double ( LICENCE::total ) & ValueListItems ( "" ; "Status" ) // LICENCE::unrelated'
    chunks = extract_chunk_lists(etree.fromstring(DDR))
    model, step, refs = _step_refs([
        {"position": 1, "parameter": "Variable", "slot": "value", "text": text, "references": chunks["_S1_1"]},
        {"position": 2, "parameter": "Variable", "slot": "repetition", "text": "2", "references": []},
    ])
    assert refs == {
        ("field", "field:Licence::total"),
        ("customFunction", "customFunction:Double"),
        ("valueList", "valueList:Status"),  # ValueListItems() names are strings, so still parsed
    }  # the commented-out LICENCE::unrelated is not a reference
    assert [(c.position, c.slot, c.text) for c in step.calculations] == [(1, "value", text), (2, "repetition", "2")]
    assert all(r["calculationPosition"] == 1 for r in step.references)
    step_refs = [r for r in model.references if r.source_doc_id == "scriptStep:Do:0000"]
    assert {r.confidence for r in step_refs} == {"exact"}


def test_step_calc_without_chunk_list_falls_back_to_text():
    _, _, refs = _step_refs([{"text": "LICENCE::unrelated + 1", "references": None}])
    assert refs == {("field", "field:Licence::unrelated")}
