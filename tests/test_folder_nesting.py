"""Which folder(s) a layout or script sits in: parts list, nested forms, odd names."""

from lxml import etree

from fm_saxml.parser.extractors.layouts import extract_layouts
from fm_saxml.parser.extractors.scripts import extract_scripts


def _layouts(xml):
    return {l["name"]: l for l in extract_layouts(etree.fromstring(f"<Database><LayoutCatalog>{xml}</LayoutCatalog></Database>"))}


def _scripts(xml):
    return {s["name"]: s for s in extract_scripts(etree.fromstring(f"<Database><ScriptCatalog>{xml}</ScriptCatalog></Database>"))}


def test_flat_layout_folders_give_parts():
    got = _layouts("""
      <Layout id="1" name="Top"/>
      <Layout id="2" name="DEV" isFolder="True"/>
      <Layout id="3" name="Old" isFolder="True"/>
      <Layout id="4" name="Deep"/>
      <Layout id="5" name="--" isFolder="Marker"/>
      <Layout id="6" name="Mid"/>
      <Layout id="7" name="--" isFolder="Marker"/>
      <Layout id="8" name="After"/>""")
    assert {n: l["folder_parts"] for n, l in got.items()} == {
        "Top": [], "Deep": ["DEV", "Old"], "Mid": ["DEV"], "After": []}
    assert got["Deep"]["folder_path"] == "DEV/Old" and got["Top"]["folder_path"] is None


def test_nested_form_layout_folders_are_not_lost():
    got = _layouts("""
      <Layout id="1" name="Top"/>
      <Layout id="2" name="DEV" isFolder="True">
        <Layout id="3" name="Inner"/>
        <Layout id="4" name="Sub" isFolder="True"><Layout id="5" name="Deep"/></Layout>
      </Layout>""")
    assert {n: l["folder_parts"] for n, l in got.items()} == {
        "Top": [], "Inner": ["DEV"], "Deep": ["DEV", "Sub"]}


def test_layout_wrapper_folders():
    got = _layouts('<LayoutFolder name="Reports"><Layout id="1" name="R1"/></LayoutFolder><Layout id="2" name="Plain"/>')
    assert got["R1"]["folder_parts"] == ["Reports"] and got["Plain"]["folder_parts"] == []


def test_slash_in_a_folder_name_stays_one_part():
    got = _layouts('<Layout id="1" name="A/B" isFolder="True"/><Layout id="2" name="X"/>')
    nested = _layouts('<Layout id="1" name="A" isFolder="True"/><Layout id="2" name="B" isFolder="True"/><Layout id="3" name="X"/>')
    assert got["X"]["folder_parts"] == ["A/B"]
    assert nested["X"]["folder_parts"] == ["A", "B"]
    assert got["X"]["folder_path"] == nested["X"]["folder_path"]  # the joined string is the lossy one


def test_script_folder_parts_flat_nested_and_wrapped():
    got = _scripts("""
      <Script id="1" name="Utils" isFolder="True"/>
      <Script id="2" name="Sub" isFolder="True"/>
      <Script id="3" name="Deep"/>
      <Script id="4" name="--" isFolder="Marker"/>
      <Script id="5" name="--" isFolder="Marker"/>
      <Script id="6" name="Out"/>
      <Script id="7" name="N" isFolder="True"><Script id="8" name="InN"/></Script>
      <ScriptFolder name="W"><Script id="9" name="InW"/></ScriptFolder>""")
    assert {n: s["folder_parts"] for n, s in got.items()} == {
        "Deep": ["Utils", "Sub"], "Out": [], "InN": ["N"], "InW": ["W"]}


# ---------------------------------------------------------------------------
# Markdown: grouped indexes and breadcrumbs
# ---------------------------------------------------------------------------

def _foldered_model():
    from pathlib import Path
    from fm_saxml.analyze.backlinks import generate_backlinks
    from fm_saxml.normalize.normalize import normalize
    from fm_saxml.normalize.references import resolve_references
    from fm_saxml.parser.saxml_reader import parse_savexml

    m = generate_backlinks(resolve_references(normalize(parse_savexml(Path(__file__).parent / "fixtures" / "small_sample.xml"))))
    scripts = sorted(m.entities.scripts.values(), key=lambda s: s.name)
    layouts = sorted(m.entities.layouts.values(), key=lambda l: l.name)
    for e, parts in ((scripts[0], ["Utils"]), (scripts[1], ["Utils", "Deep Dive"])):
        e.folder_path_parts, e.folder_path = parts, "/".join(parts)
    layouts[0].folder_path_parts, layouts[0].folder_path = ["DEV"], "DEV"
    return m, scripts, layouts


def test_indexes_group_by_folder_and_pages_get_breadcrumbs(tmp_path):
    from fm_saxml.render.markdown.renderer import render_markdown

    m, scripts, layouts = _foldered_model()
    render_markdown(m, tmp_path)

    index = (tmp_path / "Scripts" / "index.md").read_text(encoding="utf-8")
    assert "\n## Utils\n" in index
    assert "\n### Utils › Deep Dive\n" in index
    assert "- [Utils](#utils) (2)\n  - [Deep Dive](#utils--deep-dive) (1)" in index

    deep = tmp_path / m_path(m, scripts[1].doc_id)
    page = deep.read_text(encoding="utf-8")
    assert f"[Scripts](../../index.md) › [Utils](../../index.md#utils) › [Deep Dive](../../index.md#utils--deep-dive) › {scripts[1].name}" in page

    lay = (tmp_path / "Layouts" / "index.md").read_text(encoding="utf-8")
    assert "\n## DEV\n" in lay
    lpage = (tmp_path / m_path(m, layouts[0].doc_id)).read_text(encoding="utf-8")
    assert f"[Layouts](index.md) › [DEV](index.md#dev) › {layouts[0].name}" in lpage


def test_unfiled_solutions_keep_a_flat_index_and_no_breadcrumb(tmp_path):
    from fm_saxml.render.markdown.renderer import render_markdown

    m, scripts, layouts = _foldered_model()
    for e in (*m.entities.scripts.values(), *m.entities.layouts.values()):
        e.folder_path_parts, e.folder_path = [], None
    render_markdown(m, tmp_path)
    assert "## Folders" not in (tmp_path / "Scripts" / "index.md").read_text(encoding="utf-8")
    assert "›" not in (tmp_path / m_path(m, scripts[0].doc_id)).read_text(encoding="utf-8")


def test_models_without_parts_fall_back_to_the_joined_path(tmp_path):
    from fm_saxml.render.markdown.renderer import render_markdown

    m, scripts, _ = _foldered_model()
    scripts[1].folder_path_parts = []  # a model.json saved before folderPathParts existed
    render_markdown(m, tmp_path)
    index = (tmp_path / "Scripts" / "index.md").read_text(encoding="utf-8")
    assert "### Utils › Deep Dive" in index


def m_path(m, doc_id):
    from fm_saxml.render.markdown.link_resolver import LinkResolver
    return LinkResolver(m).path_for(doc_id)
