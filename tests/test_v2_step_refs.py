"""v2 script steps nest references in <ParameterValues>/<Parameter>."""

from lxml import etree

from fm_saxml.parser.extractors.scripts import _parse_step

STEP = """
<Step index="3" id="39" name="Sort Records" enable="True">
  <ParameterValues membercount="2">
    <Parameter type="LayoutReferenceContainer">
      <LayoutReferenceContainer value="5">
        <LayoutReference id="92" name="Inv" UUID="x"></LayoutReference>
      </LayoutReferenceContainer>
    </Parameter>
    <Parameter type="List"><List><ScriptReference id="9" name="Other" UUID="y"/></List></Parameter>
    <Parameter type="SortSpecification"><SortSpecification><SortList><Sort type="Custom">
      <PrimaryField><FieldReference id="12" name="total" UUID="z">
        <TableOccurrenceReference id="1" name="LICENCE" UUID="q"/></FieldReference></PrimaryField>
      <ValueListReference id="2" name="VL" UUID="w"/></Sort></SortList></SortSpecification></Parameter>
    <Parameter type="Calculation"><Calculation datatype="1"><Calculation>
      <DDRREF kind="ChunkList">h</DDRREF><Text><![CDATA[LICENCE::expiry]]></Text>
    </Calculation></Calculation></Parameter>
  </ParameterValues>
</Step>
"""


def test_v2_step_references_are_extracted():
    step = _parse_step(etree.fromstring(STEP), 0)
    assert step["layout_ref"]["name"] == "Inv"
    assert step["script_ref"]["name"] == "Other"
    assert step["field_refs"] == [{"id": "12", "name": "total", "table": "LICENCE", "table_id": "1"}]
    assert step["value_list_refs"] == [{"id": "2", "name": "VL"}]
    assert step["calculation"] == "LICENCE::expiry"


def test_script_folders_and_dividers_are_not_scripts():
    from fm_saxml.parser.extractors.scripts import extract_scripts

    db = etree.fromstring("""
    <Database><ScriptCatalog>
      <Script id="1" name="Top"></Script>
      <Script id="2" name="Utils" isFolder="True"></Script>
      <Script id="3" name="-" isSeparatorItem="True"></Script>
      <Script id="4" name="Inner"></Script>
      <Script id="5" name="Sub" isFolder="True"></Script>
      <Script id="6" name="Deep"></Script>
      <Script id="7" name="--" isFolder="Marker"></Script>
      <Script id="8" name="After Sub"></Script>
      <Script id="9" name="--" isFolder="Marker"></Script>
      <Script id="10" name="Outside"></Script>
    </ScriptCatalog></Database>""")
    got = {s["name"]: s["folder_path"] for s in extract_scripts(db)}
    assert got == {
        "Top": None, "Inner": "Utils", "Deep": "Utils/Sub",
        "After Sub": "Utils", "Outside": None,
    }
