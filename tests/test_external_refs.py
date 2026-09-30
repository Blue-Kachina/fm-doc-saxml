"""References into other files of a multi-file solution are tagged 'external', not 'unresolved'."""

import pytest
from lxml import etree

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.parser.extractors.scripts import _parse_step
from fm_saxml.parser.extractors.table_occurrences import extract_table_occurrences
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.references import resolve_references
from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.analyze.warnings import generate_warnings


def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "129", "name": "Contrat"}]
    raw.fields = [{"table_name": "Contrat", "name": "Code_client", "id": "1"}]
    raw.table_occurrences = [
        {"id": "1", "name": "Contrat", "base_table_id": "129"},
        # external TO whose base table id (129) collides with the local table's id
        {"id": "2", "name": "idiClients", "base_table_id": "129", "external_data_source": "idiClients"},
    ]
    raw.scripts = [{
        "id": "1", "name": "S", "steps": [
            {"index": 0, "step_type_id": "1", "name": "Set Field",
             "field_refs": [{"name": "Code_client", "table": "idiClients"}]},
            {"index": 1, "step_type_id": "1", "name": "Perform Script",
             "script_ref": {"name": "Open Script", "data_source": "idiClients"}},
            {"index": 2, "step_type_id": "1", "name": "Go to Related Record",
             "layout_ref": {"name": "Coordonnees", "via_to": "idiClients"}},
            {"index": 3, "step_type_id": "1", "name": "Set Field",
             "field_refs": [{"name": "Code_client", "table": "Missing"}]},
            {"index": 4, "step_type_id": "1", "name": "Set Variable",
             "calculation": "idiClients::Nom"},
        ]}]
    return raw


@pytest.fixture
def model():
    return generate_warnings(generate_backlinks(resolve_references(normalize(_raw()))))


def _conf(model, step):
    return [r.confidence for r in model.references if r.source_doc_id == f"scriptStep:S:{step:04d}"]


def test_external_to_does_not_take_a_local_base_table(model):
    to = model.entities.table_occurrences["to:idiClients"]
    assert to.base_table_doc_id == ""
    assert to.external_data_source == "idiClients"
    assert "to:idiClients" not in model.entities.tables["table:Contrat"].table_occurrences


def test_field_via_external_to_is_external_not_linked_locally(model):
    assert _conf(model, 0) == ["external"]
    # must not steal the local Contrat::Code_client field
    assert not any(b["sourceDocId"].startswith("scriptStep") for b in model.backlinks.get("field:Contrat::Code_client", []))


def test_external_script_and_layout_are_external_and_namespaced(model):
    assert _conf(model, 1) == ["external"]
    assert _conf(model, 2) == ["external"]
    targets = {r.target_doc_id for r in model.references if r.confidence == "external"}
    assert "ds:idiClients/script:Open Script" in targets
    assert "ds:idiClients/layout:Coordonnees" in targets


def test_calculation_ref_via_external_to_is_external(model):
    assert _conf(model, 4) == ["external"]


def test_genuinely_missing_reference_stays_unresolved(model):
    assert _conf(model, 3) == ["unresolved"]
    assert len([w for w in model.warnings if w.code == "UNRESOLVED_REFERENCE"]) == 1


def test_extractor_reads_external_signals():
    step = _parse_step(etree.fromstring("""
    <Step index="1" id="1" name="Perform Script"><ParameterValues><Parameter type="List"><List>
      <DataSourceReference id="3" name="idiClients"/><ScriptReference id="9" name="Open Script"/>
    </List></Parameter></ParameterValues></Step>"""), 0)
    assert step["script_ref"]["data_source"] == "idiClients"

    local = _parse_step(etree.fromstring("""
    <Step index="1" id="1" name="Perform Script"><ParameterValues><Parameter type="List"><List>
      <DataSourceReference id="0" name="Current File"/><ScriptReference id="9" name="X"/>
    </List></Parameter></ParameterValues></Step>"""), 0)
    assert local["script_ref"]["data_source"] is None

    rel = _parse_step(etree.fromstring("""
    <Step index="1" id="74" name="Go to Related Record"><ParameterValues><Parameter type="Related">
      <TableOccurrenceReference id="2" name="idiClients"/>
      <LayoutReferenceContainer value="5"><LayoutReference id="4" name="Coordonnees"/></LayoutReferenceContainer>
    </Parameter></ParameterValues></Step>"""), 0)
    assert rel["layout_ref"]["via_to"] == "idiClients"


def test_extractor_flags_external_table_occurrence():
    db = etree.fromstring("""<Database><TableOccurrenceCatalog>
      <TableOccurrence id="2" name="idiClients" type="External"><BaseTableSourceReference type="ExternalDataSourceReference">
        <DataSourceReference id="3" name="idiClients"/><BaseTableReference id="129" name="idiClients"/>
      </BaseTableSourceReference></TableOccurrence>
      <TableOccurrence id="1" name="Contrat" type="Local"><BaseTableSourceReference>
        <BaseTableReference id="129" name="Contrat"/></BaseTableSourceReference></TableOccurrence>
    </TableOccurrenceCatalog></Database>""")
    got = {t["name"]: t["external_data_source"] for t in extract_table_occurrences(db)}
    assert got == {"idiClients": "idiClients", "Contrat": None}


# ---------------------------------------------------------------------------
# Keeping enough detail to resolve external references against a sister file
# ---------------------------------------------------------------------------

def _rich_raw() -> RawModel:
    raw = _raw()
    raw.fmp_file_name = "main.fmp12"
    raw.file_uuid = "FILE-UUID"
    raw.external_data_sources = [
        {"name": "idiClients", "id": "3", "uuid": "DS-UUID", "type": "FileMaker", "paths": ["file:idiClients"]},
    ]
    raw.table_occurrences[1].update({
        "external_data_source_id": "3", "external_data_source_uuid": "DS-UUID",
        "external_base_table": "Clients", "external_base_table_id": "129", "external_base_table_uuid": "BT-UUID",
    })
    raw.scripts[0]["steps"][0]["field_refs"] = [
        {"id": "155", "uuid": "F-UUID", "name": "Code_client", "table": "idiClients"}]
    raw.scripts[0]["steps"][1]["script_ref"] = {
        "id": "350", "uuid": "S-UUID", "name": "Open Script", "data_source": "idiClients"}
    raw.scripts[0]["steps"][2]["layout_ref"] = {
        "id": "36", "uuid": "L-UUID", "name": "Coordonnees", "via_to": "idiClients"}
    raw.layouts = [{"id": "20", "name": "Lay", "layout_objects": [
        {"id": "5", "type": "Field", "field": {
            "table_name": "idiClients", "field_name": "Nom", "field_id": "7", "field_uuid": "N-UUID"}}]}]
    raw.relationships = [{
        "id": "1", "left_table_name": "Contrat", "right_table_name": "idiClients",
        "predicates": [{"left_table_name": "Contrat", "left_field_name": "Code_client",
                        "right_table_name": "idiClients", "right_field_name": "Code_client",
                        "right_field_id": "155", "right_field_uuid": "RF-UUID", "operator": "="}]}]
    return raw


@pytest.fixture
def rich():
    return generate_backlinks(resolve_references(normalize(_rich_raw())))


def _ext_targets(model, source_prefix=None, target_type=None):
    return [
        r.external_target for r in model.references
        if r.confidence == "external"
        and (source_prefix is None or r.source_doc_id.startswith(source_prefix))
        and (target_type is None or r.external_target.target_type == target_type)
    ]


def test_file_identity_and_data_source_catalog_are_kept(rich):
    assert rich.source.file_uuid == "FILE-UUID"
    assert rich.source.fmp_file_name == "main.fmp12"
    ds = rich.external_data_sources[0]
    assert (ds.name, ds.fmp_id, ds.uuid, ds.paths) == ("idiClients", "3", "DS-UUID", ["file:idiClients"])


def test_external_to_keeps_its_base_table_in_the_other_file(rich):
    to = rich.entities.table_occurrences["to:idiClients"]
    assert (to.external_base_table, to.external_base_table_id, to.external_base_table_uuid) == ("Clients", "129", "BT-UUID")
    assert to.base_table_doc_id == ""


def test_script_step_targets_carry_ids_and_uuids(rich):
    field = _ext_targets(rich, "scriptStep:S:0000", "field")[0]
    assert (field.name, field.fmp_id, field.uuid) == ("Code_client", "155", "F-UUID")
    assert (field.table_occurrence, field.base_table, field.base_table_uuid) == ("idiClients", "Clients", "BT-UUID")
    assert (field.data_source, field.data_source_id, field.data_source_uuid) == ("idiClients", "3", "DS-UUID")

    script = _ext_targets(rich, "scriptStep:S:0001", "script")[0]
    assert (script.name, script.fmp_id, script.uuid, script.data_source_uuid) == ("Open Script", "350", "S-UUID", "DS-UUID")

    layout = _ext_targets(rich, "scriptStep:S:0002", "layout")[0]
    assert (layout.name, layout.uuid, layout.table_occurrence, layout.base_table) == ("Coordonnees", "L-UUID", "idiClients", "Clients")


def test_layout_object_field_from_other_file_is_an_external_reference(rich):
    (t,) = _ext_targets(rich, "layoutObject:")
    assert (t.name, t.fmp_id, t.uuid, t.base_table) == ("Nom", "7", "N-UUID", "Clients")


def test_relationship_predicate_into_other_file_is_an_external_reference(rich):
    (t,) = _ext_targets(rich, "relationship:")
    assert (t.name, t.fmp_id, t.uuid, t.base_table) == ("Code_client", "155", "RF-UUID", "Clients")


def test_external_references_json_is_self_contained(rich, tmp_path):
    import json
    from fm_saxml.render.json.writer import write_external_references_json

    write_external_references_json(rich, tmp_path)
    doc = json.loads((tmp_path / "external-references.json").read_text(encoding="utf-8"))
    assert doc["source"]["fileUuid"] == "FILE-UUID"
    assert doc["dataSources"][0]["uuid"] == "DS-UUID"
    assert doc["externalTableOccurrences"][0]["baseTableUuid"] == "BT-UUID"
    assert doc["references"] and all(r["target"] and r["target"]["dataSourceUuid"] == "DS-UUID" for r in doc["references"])
    kinds = {r["target"]["targetType"] for r in doc["references"]}
    assert kinds == {"field", "script", "layout"}


def test_extractor_reads_data_source_catalog():
    from fm_saxml.parser.extractors.external_data_sources import extract_external_data_sources

    container = etree.fromstring("""<AddAction><ExternalDataSourceCatalog>
      <ExternalDataSource name="idiClients" type="FileMaker" id="3">
        <File><UniversalPathList>file:idiClients</UniversalPathList></File>
        <UUID modifications="2">EEC9827D</UUID>
      </ExternalDataSource></ExternalDataSourceCatalog></AddAction>""")
    assert extract_external_data_sources(container) == [
        {"name": "idiClients", "id": "3", "uuid": "EEC9827D", "type": "FileMaker", "paths": ["file:idiClients"]}]


# ---------------------------------------------------------------------------
# File-scoped docIds:  <scope>/<docId>
# ---------------------------------------------------------------------------

def test_scope_helpers_round_trip_and_handle_slashes_in_names():
    from fm_saxml.normalize.ids import file_scope, provisional_scope, scoped_doc_id, split_scoped_doc_id

    uuid = "87139397-FED7-453D-A8E6-746F8DC6B771"
    assert file_scope(uuid, "a.fmp12") == uuid
    assert file_scope(None, "a.fmp12") == "file:a.fmp12"
    assert provisional_scope("EEC9827D-DC30", "idiClients") == "ds:EEC9827D-DC30"
    assert provisional_scope(None, "we/ird") == "ds:we%2Fird"

    # docIds may contain "/" (script names can): only the leading scope is split off
    for scope in (uuid, "file:a.fmp12", "ds:EEC9827D-DC30"):
        assert split_scoped_doc_id(scoped_doc_id(scope, "script:Open/Close")) == (scope, "script:Open/Close")
    # unscoped ids are left alone, even when the name contains "/"
    assert split_scoped_doc_id("script:Open/Close") == (None, "script:Open/Close")
    assert split_scoped_doc_id("field:T::f") == (None, "field:T::f")


def test_model_scope_prefers_file_uuid(rich):
    assert rich.source.scope == "FILE-UUID"
    assert rich.scoped("script:S") == "FILE-UUID/script:S"


def test_scope_falls_back_to_fmp_file_name():
    raw = _rich_raw()
    raw.file_uuid = ""
    m = normalize(raw)
    assert m.source.scope == "file:main.fmp12"


def test_external_targets_get_scoped_doc_ids_everywhere(rich):
    field = _ext_targets(rich, "scriptStep:S:0000", "field")[0]
    # target's own docId (base table in the OTHER file + field), and its provisional scoped form
    assert field.target_doc_id == "field:Clients::Code_client"
    assert field.scope == "ds:DS-UUID"
    assert field.scoped_doc_id == "ds:DS-UUID/field:Clients::Code_client"

    script = _ext_targets(rich, "scriptStep:S:0001", "script")[0]
    assert script.scoped_doc_id == "ds:DS-UUID/script:Open Script"

    # every external reference points at its scoped id, and backlinks are keyed by it
    for r in rich.references:
        if r.confidence == "external":
            assert r.target_doc_id == r.external_target.scoped_doc_id
            assert r.source_doc_id in {b["sourceDocId"] for b in rich.backlinks[r.target_doc_id]}

    # entity fields that name an external field use the same scoped id
    obj = next(iter(rich.entities.layout_objects.values()))
    assert obj.field_doc_id == "ds:DS-UUID/field:Clients::Nom"
    pred = next(iter(rich.entities.relationships.values())).predicates[0]
    assert pred.right_field_doc_id == "ds:DS-UUID/field:Clients::Code_client"
    assert pred.left_field_doc_id == "field:Contrat::Code_client"  # local side stays unscoped


def test_external_references_json_carries_scopes(rich, tmp_path):
    import json
    from fm_saxml.render.json.writer import write_external_references_json

    write_external_references_json(rich, tmp_path)
    doc = json.loads((tmp_path / "external-references.json").read_text(encoding="utf-8"))
    assert doc["source"]["scope"] == "FILE-UUID"
    row = next(r for r in doc["references"] if r["sourceDocId"].startswith("scriptStep:S:0001"))
    assert row["sourceScopedDocId"] == "FILE-UUID/scriptStep:S:0001"
    assert row["target"]["scopedDocId"] == "ds:DS-UUID/script:Open Script"


def test_markdown_shows_external_targets_readably(rich):
    from fm_saxml.render.markdown.link_resolver import LinkResolver

    links = LinkResolver(rich)
    assert links.title_for("ds:DS-UUID/script:Open Script") == "Open Script (idiClients)"
    assert links.title_for("ds:DS-UUID/field:Clients::Code_client") == "Clients::Code_client (idiClients)"


# ---------------------------------------------------------------------------
# Folders/dividers in the layout catalog; custom menu items
# ---------------------------------------------------------------------------

def test_layout_folders_and_dividers_are_not_layouts():
    from fm_saxml.parser.extractors.layouts import extract_layouts

    db = etree.fromstring("""<Database><LayoutCatalog>
      <Layout id="1" name="Top"></Layout>
      <Layout id="2" name="DEV" isFolder="True"></Layout>
      <Layout id="3" name="-" isSeparatorItem="True"></Layout>
      <Layout id="4" name="Inner"></Layout>
      <Layout id="5" name="--" isFolder="Marker"></Layout>
      <Layout id="6" name="After"></Layout>
    </LayoutCatalog></Database>""")
    got = {l["name"]: l["folder_path"] for l in extract_layouts(db)}
    assert got == {"Top": None, "Inner": "DEV", "After": None}


MENU_XML = """<Container><CustomMenuCatalog><CustomMenu name="Main" id="1"><MenuItemList membercount="4">
  <CustomMenuItem index="0" isSubMenuItem="False" isSeparatorItem="False"><Command name="Add New Request" id="50209"/></CustomMenuItem>
  <CustomMenuItem index="1" isSubMenuItem="False" isSeparatorItem="True"></CustomMenuItem>
  <CustomMenuItem index="2" isSubMenuItem="True" isSeparatorItem="False"><CustomMenuReference id="14" name="Sub"/></CustomMenuItem>
  <CustomMenuItem index="3" isSubMenuItem="False" isSeparatorItem="False"><action><Step index="0" id="1" name="Perform Script"><ParameterValues>
    <Parameter type="List"><List><ScriptReference id="84" name="Show All" UUID="U"/></List></Parameter></ParameterValues></Step></action></CustomMenuItem>
</MenuItemList></CustomMenu></CustomMenuCatalog></Container>"""


def test_custom_menu_items_are_extracted():
    from fm_saxml.parser.extractors.custom_menus import extract_custom_menus

    (menu,) = extract_custom_menus(etree.fromstring(MENU_XML))
    kinds = [(i["action_type"], i["name"]) for i in menu["items"]]
    assert kinds == [("command", "Add New Request"), ("separator", "-"), ("submenu", "Sub"),
                     ("script", "Perform Script [ Show All ]")]
    assert menu["items"][3]["script_ref"]["name"] == "Show All"
    assert menu["items"][2]["submenu_name"] == "Sub"


def test_custom_menu_links_to_scripts_and_submenus():
    raw = _raw()
    raw.scripts = [{"id": "1", "name": "Show All", "steps": []}]
    raw.custom_menus = [
        {"id": "1", "name": "Main", "items": [
            {"name": "Show", "action_type": "script", "script_ref": {"name": "Show All", "id": "84"}},
            {"name": "Ext", "action_type": "script",
             "script_ref": {"name": "Open Script", "id": "9", "data_source": "idiClients"}},
            {"name": "Sub", "action_type": "submenu", "submenu_name": "Sub"}]},
        {"id": "2", "name": "Sub", "items": []},
    ]
    m = generate_backlinks(resolve_references(normalize(raw)))
    got = {(r.target_doc_id, r.confidence) for r in m.references if r.source_doc_id == "customMenu:Main"}
    assert ("script:Show All", "exact") in got
    assert ("customMenu:Sub", "exact") in got
    assert ("ds:idiClients/script:Open Script", "external") in got
    assert any(b["sourceDocId"] == "customMenu:Main" for b in m.backlinks["script:Show All"])
