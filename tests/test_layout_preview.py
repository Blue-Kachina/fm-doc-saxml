"""The HTML viewer's layout preview (layout_preview.md, phases P1 to P4).

The per-layout data files are checked here directly, on a hand-made layout with every
kind of nesting (portal, tab control, popover, parts) and on EverythingBagel. The preview
itself runs in a browser, so the last tests drive the viewer with Playwright (skipped when
Playwright or Chrome isn't installed): ``uv run --with playwright pytest tests/test_layout_preview.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.cli import _run_pipeline, app
from fm_saxml.model.document_model import DocumentModel
from fm_saxml.render.html import VIEWER_DIR
from fm_saxml.render.html.layout_preview import build_layout_preview

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
MAC_SAMPLE = ROOT / "samples" / "EverythingBagel_mac_run" / "saxml" / "EverythingBagel.xml"
MULTI = ROOT / "samples" / "multi_file_export" / "SaXML_no_separate_catalogue"
runner = CliRunner()

_FIELD = ('<Field><FieldReference id="{id}" name="{name}" repetition="1">'
          '<TableOccurrenceReference id="{to_id}" name="{to}"></TableOccurrenceReference></FieldReference></Field>')


def _field(name: str, fid: int, to: str = "Contact", to_id: int = 1048577) -> str:
    return _FIELD.format(id=fid, name=name, to=to, to_id=to_id)


def _obj(oid: int, otype: str, bounds: tuple, body: str = "", name: str = "", extra: str = "") -> str:
    t, l, b, r = bounds
    return (f'<LayoutObject id="{oid}" type="{otype}" name="{name}" kind="1"{extra}>'
            f'<Bounds top="{t}" left="{l}" bottom="{b}" right="{r}"></Bounds><Options>805306368</Options>{body}</LayoutObject>')


def _text(text: str) -> str:
    return f"<Text><StyledText><Data><![CDATA[{text}]]></Data></StyledText></Text>"


# A 400 x 370 pt layout: Header 0-40, Body 40-340, Footer 340-370. Nested bounds are relative
# to their container (the popover panel's own are absolute), as FileMaker writes them.
_LAYOUT = f"""<Layout id="1" name="ContactDetail" width="400">
  <TableOccurrenceReference id="1048577" name="Contact" UUID="00000000-0000-0000-0000-000000000021"></TableOccurrenceReference>
  <PartsList membercount="3">
    <Part type="Header" kind="1"><Definition kind="1" absolute="0" size="40" Options="0"></Definition><ObjectList membercount="2">
      {_obj(1, "Text", (5, 10, 25, 120), _text("Contact details"))}
      {_obj(2, "Button", (5, 300, 30, 390), '<Button><Label>' + _text("Send") + '</Label><action><ScriptReference id="1" name="SendEmail"></ScriptReference></action></Button>', name="SendBtn")}
    </ObjectList></Part>
    <Part type="Body" kind="4"><Definition kind="4" absolute="40" size="300" Options="0"></Definition><ObjectList membercount="11">
      {_obj(3, "Edit Box", (50, 10, 70, 150), _field("ContactID", 1))}
      {_obj(4, "Edit Box", (75, 10, 95, 150), _field("FullName", 2))}
      {_obj(5, "Edit Box", (75, 10, 95, 150), _field("FullName", 2))}
      {_obj(18, "Portal", (50, 170, 110, 370),
            '<Portal><TableOccurrenceReference id="1048578" name="Contact__selfJoin"></TableOccurrenceReference>'
            '<Options index="1" show="3">0</Options><ObjectList membercount="1">'
            + _obj(19, "Edit Box", (0, 0, 20, 200), _field("FullName", 2, "Contact__selfJoin", 1048578))
            + '</ObjectList></Portal>')}
      {_obj(14, "Rectangle", (50, 380, 80, 450), "<Rectangle></Rectangle>")}
      {_obj(15, "Line", (115, 10, 115, 200), "<Line></Line>")}
      {_obj(16, "Rectangle", (115, 300, 116, 301), "<Rectangle></Rectangle>")}
      {_obj(6, "Tab Control", (120, 10, 270, 390),
            '<TabControl default="1" visible="1" height="20" modifier="100" Location="0"><ObjectList membercount="2">'
            + _obj(7, "Panel", (0, 0, 150, 380), '<TabPanel size="100" absolute="0"><Calculation><Text><![CDATA["First"]]></Text></Calculation><ObjectList>'
                   + _obj(8, "Edit Box", (30, 10, 50, 150), _field("Status", 3)) + '</ObjectList></TabPanel>')
            + _obj(9, "Panel", (0, 0, 150, 380), '<TabPanel size="100" absolute="99"><Calculation><Text><![CDATA["Second"]]></Text></Calculation><ObjectList>'
                   + _obj(10, "Text", (30, 10, 50, 150), _text("On the second tab")) + '</ObjectList></TabPanel>')
            + '</ObjectList></TabControl>')}
      {_obj(11, "Popover Button", (275, 10, 295, 100),
            '<PopoverButton><Label>' + _text("More") + '</Label>'
            + _obj(12, "PopoverPanel", (300, 10, 360, 200), '<ObjectList>'
                   + _obj(13, "Edit Box", (10, 10, 30, 150), _field("Status", 3)) + '</ObjectList>', extra=' position="1" Options="0"')
            + '</PopoverButton>')}
      {_obj(17, "Edit Box", (275, 120, 295, 260), _field("Status", 3)
            + '<Conditions><Hide findMode="False"><Calculation><Text><![CDATA[IsEmpty ( Contact::Status )]]></Text></Calculation></Hide></Conditions>')}
    </ObjectList></Part>
    <Part type="Footer" kind="8"><Definition kind="8" absolute="340" size="30" Options="0"></Definition><ObjectList membercount="1">
      {_obj(20, "Text", (345, 10, 360, 100), _text("Footer text"))}
    </ObjectList></Part>
  </PartsList>
  <TagList></TagList>
</Layout>"""


# P4: a theme in FileMaker's CSS dialect, and the layout's own <LocalCSS>. Edit boxes are
# see-through (alpha .9), so nothing on the layout counts as covered.
_THEME_CSS = """/* Object Styles */
layout_background:normal .self
{
\tbackground-color: rgba(94.902%,94.902%,94.902%,1);
}
header:normal .self
{
\tbackground-color: rgba(65.4902%,82.3529%,90.9804%,1);
}
body:normal .self
{
\tbackground-color: rgba(100%,100%,100%,1);
}
edit_box:normal .self
{
\tbackground-color: rgba(100%,100%,100%,0.9);
\tborder-top-style: solid;
\tborder-top-width: 1pt;
\tborder-top-color: rgba(80%,80%,80%,1);
\tfont-family: -fm-font-family(Helvetica Neue,HelveticaNeue;sans-serif);
\tfont-size: 12pt;
\tcolor: rgba(20%,20%,20%,1);
\t-fm-text-vertical-align: center;
\tbox-shadow: 0pt 1pt 2pt rgba(0%,0%,0%,0.2);
}
edit_box:hover .self
{
\tbackground-color: rgba(0%,0%,100%,1);
}
button:normal .self
{
\tbackground-color: rgba(0%,56.8627%,80.7843%,1);
\tcolor: rgba(100%,100%,100%,1);
\ttext-align: center;
}
button:normal .inner_border
{
\tborder-top-left-radius: 4pt 4pt;
}
button.primary_button:normal .self
{
\tbackground-color: rgba(85.098%,4.31373%,0%,1);
\tfont-weight: bold;
}
text_box:normal .self
{
\tcolor: rgba(40%,40%,40%,1);
\tfont-size: 11pt;
}
header text_box:normal .self
{
\tcolor: rgba(0%,0%,50.1961%,1);
}
"""


def _layout_xml(dest: Path, styled: bool = False) -> Path:
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    layout = _LAYOUT
    if styled:
        layout = layout.replace("<PartsList", '<LayoutThemeReference id="1" name="com.filemaker.theme.minimalist_touch" '
                                'Display="Minimalist Touch"></LayoutThemeReference><PartsList', 1)
        for oid, css, name in ((2, "self.primary_button\n{\n}\n", "primary_button"),
                               (3, "self:normal .self\n{\n\tbackground-color: rgba(100%,98.8235%,67.0588%,0.5);\n}\n", "")):
            start = layout.index(f'<LayoutObject id="{oid}" ')
            end = layout.index("</LayoutObject>", start)
            local = f'<LocalCSS name="{name}" displayName="{name}"><![CDATA[{css}]]></LocalCSS>'
            layout = layout[:end] + local + layout[end:]
        xml = xml.replace('Group="FileMaker" defaultTheme="True">',
                          f'Group="FileMaker" defaultTheme="True"><CSS><![CDATA[{_THEME_CSS}]]></CSS>', 1)
    xml, n = re.subn(r'<Layout id="1" name="ContactDetail".*?</Layout>', lambda _m: layout, xml, flags=re.DOTALL)
    assert n == 1
    dest.write_text(xml, encoding="utf-8")
    return dest


def _call_args(js: str, fn: str) -> list:
    prefix = f"FMDocs.{fn}("
    assert js.startswith(prefix) and js.endswith(");\n"), js[:80]
    return json.loads("[" + js[len(prefix):-3] + "]")


def _manifest(out: Path) -> dict:
    return _call_args((out / VIEWER_DIR / "manifest.js").read_text(encoding="utf-8"), "manifest")[0]


def _layouts_dir(out: Path, key: str = "_") -> Path:
    return out / VIEWER_DIR / "data" / key / "layouts"


def _build(tmp_path: Path, *extra: str, xml: Path | None = None) -> Path:
    xml = xml or _layout_xml(tmp_path / "Preview.xml")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "-f", *extra])
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    model = _run_pipeline(_layout_xml(tmp_path_factory.mktemp("lp") / "Preview.xml"))
    data = build_layout_preview(model, "layout:ContactDetail")
    return model, data, {o["id"]: o for o in data["objects"]}


# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

def test_parts_and_size(preview):
    _, data, _ = preview
    assert data["width"] == 400 and data["height"] == 370
    assert data["parts"] == [{"type": "Header", "top": 0, "height": 40}, {"type": "Body", "top": 40, "height": 300},
                             {"type": "Footer", "top": 340, "height": 30}]
    assert data["objPrefix"] == "layoutObject:ContactDetail::"
    assert data["objDir"] == "LayoutObjects/ContactDetail/" and data["path"] == "Layouts/ContactDetail.md"


def test_objects_are_in_paint_order(preview):
    _, data, _ = preview
    # Document order, containers before their contents: FileMaker's back-to-front order, not id order.
    assert [o["id"] for o in data["objects"]] == [
        "1", "2", "3", "4", "5", "18", "19", "14", "15", "16", "6", "7", "8", "9", "10", "11", "12", "13", "17", "20"]


def test_nested_bounds_become_absolute(preview):
    _, data, objs = preview
    assert objs["19"]["b"] == [50, 170, 70, 370]      # portal row 1: + the portal's top left
    assert objs["7"]["b"] == [120, 10, 270, 390]      # a tab panel covers its control
    assert objs["8"]["b"] == [150, 20, 170, 160]      # + panel + control
    assert objs["12"]["b"] == [300, 10, 360, 200]     # a popover panel's own bounds are absolute
    assert objs["13"]["b"] == [310, 20, 330, 160]     # + the panel only, not its button
    assert objs["20"]["b"] == [345, 10, 360, 100] and objs["20"]["p"] == "Footer"  # top-level: absolute, not part-relative
    ids = [o["id"] for o in data["objects"]]
    assert objs["19"]["pa"] == ids.index("18") and objs["13"]["pa"] == ids.index("12")
    assert objs["12"]["pa"] == ids.index("11")


def test_labels_fields_scripts_and_links(preview):
    _, _, objs = preview
    assert objs["1"]["l"] == "Contact details"
    assert objs["2"] == {**objs["2"], "n": "SendBtn", "l": "Send", "s": "SendEmail", "sp": "Scripts/SendEmail.md"}
    assert objs["3"]["f"] == "Contact::ContactID" and objs["3"]["fp"] == "Fields/Contact/ContactID.md"
    assert objs["19"]["f"] == "Contact__selfJoin::FullName"  # the table occurrence it is shown through
    assert objs["3"]["pg"] == "3.md"
    assert objs["18"]["pr"] == {"rows": 3, "init": 1}
    assert objs["17"]["hc"] == "IsEmpty ( Contact::Status )"
    assert "hc" not in objs["8"]


def test_tab_controls_and_popovers(preview):
    _, _, objs = preview
    assert objs["6"]["tab"] == {"def": 1, "h": 20}
    assert objs["7"]["tab"] == {"w": 100, "x": 0, "l": "First"}
    assert objs["9"]["tab"] == {"w": 100, "x": 99, "l": "Second"}
    assert objs["12"]["pop"] == 1


def test_problem_flags(preview):
    _, data, objs = preview
    assert objs["14"]["x"] == ["out"]                       # right edge past the 400 pt layout
    assert objs["16"]["x"] == ["tiny"]
    assert objs["4"]["x"] == ["dup"] and objs["5"]["x"] == ["dup"]
    assert "x" not in objs["15"]                            # a line's thickness is its stroke
    assert "x" not in objs["12"] and "x" not in objs["13"]  # popovers float: not checked against the edges
    assert data["problems"] == {"outside": 1, "tiny": 1, "duplicate": 2}


def test_a_model_json_render_falls_back_without_the_tab_geometry(preview):
    model, _, _ = preview
    again = DocumentModel.model_validate(json.loads(model.model_dump_json(by_alias=True)))
    data = build_layout_preview(again, "layout:ContactDetail")
    objs = {o["id"]: o for o in data["objects"]}
    assert data["geometry"] is False
    assert objs["6"]["tab"] == {} and objs["7"]["tab"] == {"l": "First"} and "pop" not in objs["12"]
    assert objs["8"]["b"] == [150, 20, 170, 160]  # the bounds are in the model


def test_everything_bagel(tmp_path):
    model = _run_pipeline(ROOT / "EverythingBagel.xml")
    data = build_layout_preview(model, "layout:EverythingBagel")
    assert data["width"] == 1024 and data["height"] == 768
    assert [p["type"] for p in data["parts"]] == ["Top Navigation", "Body"]
    assert len(data["objects"]) == 16 and data["problems"] == {"outside": 0, "tiny": 0, "duplicate": 0}
    first = data["objects"][1]
    assert first == {"id": "2", "t": "Edit Box", "b": [114, 138, 146, 391], "p": "Body", "f": "EverythingBagel::textField",
                     "fp": "Fields/EverythingBagel/textField.md", "pg": "2.md"}


@pytest.mark.skipif(not MAC_SAMPLE.exists(), reason="Mac sample not present")
def test_everything_bagel_mac_run_nesting():
    model = _run_pipeline(MAC_SAMPLE)
    data = build_layout_preview(model, "layout:EverythingBagel")
    objs = {o["id"]: o for o in data["objects"]}
    assert len(objs) == 32 and data["geometry"] is True
    assert objs["17"]["t"] == "Portal" and objs["17"]["pr"] == {"rows": 6, "init": 1}
    assert objs["18"]["b"] == [154, 467, 174, 691]  # portal child, row 1
    assert [objs[i]["b"][0] for i in ("21", "22", "23")] == [329, 372, 415]  # button bar segments
    assert objs["25"]["t"] == "PopoverPanel" and objs["25"]["b"] == [149, 768, 549, 1058] and objs["25"]["pop"] == 0
    assert data["problems"]["outside"] == 0  # the popover sits past the 1024 pt edge on purpose


def test_build_writes_one_file_per_layout_and_an_index(tmp_path):
    out = _build(tmp_path, "--html")
    assert _manifest(out)["layoutPreview"] == {"files": [{"key": "_", "dir": ""}]}
    assert '<script src="_viewer/layout-preview.js"></script>' in (out / "index.html").read_text(encoding="utf-8")
    assert (out / VIEWER_DIR / "layout-preview.js").exists()
    key, index = _call_args((_layouts_dir(out) / "index.js").read_text(encoding="utf-8"), "layoutPreviewIndex")
    assert key == "_"
    assert index["layouts"] == [["layout:ContactDetail", 1, "ContactDetail", 20, "Layouts/ContactDetail.md", 4]]
    assert index["fields"]["field:Contact::Status"] == [[1, ["8", "13", "17"]]]
    assert index["fields"]["field:Contact::FullName"] == [[1, ["4", "5", "19"]]]
    key, doc_id, data = _call_args((_layouts_dir(out) / "1.js").read_text(encoding="utf-8"), "layoutPreview")
    assert (key, doc_id, len(data["objects"])) == ("_", "layout:ContactDetail", 20)
    assert not (out / VIEWER_DIR / "webmcp.js").exists()  # the preview doesn't need --webmcp
    # The Markdown stays plain.
    assert "layoutPreview" not in (out / "Layouts" / "ContactDetail.md").read_text(encoding="utf-8")


def test_no_layout_preview_leaves_it_out(tmp_path):
    out = _build(tmp_path, "--html", "--no-layout-preview")
    assert not (out / VIEWER_DIR / "data").exists()
    assert not (out / VIEWER_DIR / "layout-preview.js").exists()
    assert "layoutPreview" not in _manifest(out)
    assert "layout-preview.js" not in (out / "index.html").read_text(encoding="utf-8")


def test_markdown_only_build_writes_no_preview(tmp_path):
    out = _build(tmp_path)
    assert not (out / VIEWER_DIR).exists()


def test_batch_writes_previews_per_file(tmp_path):
    if not MULTI.exists():
        pytest.skip("multi-file sample not present")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(MULTI), "-o", str(out), "-f", "--html"])
    assert result.exit_code == 0, result.output
    files = _manifest(out)["layoutPreview"]["files"]
    assert sorted(f["key"] for f in files) == ["FileA", "FileB"]
    for f in files:
        assert f["dir"] == f["key"]
        _, index = _call_args((_layouts_dir(out, f["key"]) / "index.js").read_text(encoding="utf-8"), "layoutPreviewIndex")
        for doc_id, n, _name, _count, path, _problems in index["layouts"]:
            assert path.startswith(f["dir"] + "/") and (out / path).exists(), path
            _, _, data = _call_args((_layouts_dir(out, f["key"]) / f"{n}.js").read_text(encoding="utf-8"), "layoutPreview")
            assert data["docId"] == doc_id
            for o in data["objects"]:
                if "pg" in o:
                    assert (out / (data["objDir"] + o["pg"] if "/" not in o["pg"] else o["pg"])).exists()
    # FileB's layout "FileA" shows FileA's fields: listed under FileA's key and the docId there.
    _, index_b = _call_args((_layouts_dir(out, "FileB") / "index.js").read_text(encoding="utf-8"), "layoutPreviewIndex")
    assert "field:FileA::PrimaryKey" not in index_b["fields"]
    n_a = next(n for _d, n, name, *_ in index_b["layouts"] if name == "FileA")
    assert [n for n, _ids in index_b["xfields"]["FileA"]["field:FileA::PrimaryKey"]] == [n_a]


def test_preview_data_cannot_break_out_of_the_script(tmp_path):
    xml = _layout_xml(tmp_path / "Nasty.xml")
    text = xml.read_text(encoding="utf-8").replace("Contact details", "&lt;/script&gt;&lt;script&gt;alert(1)//")
    xml.write_text(text, encoding="utf-8")
    out = _build(tmp_path, "--html", xml=xml)
    for js in _layouts_dir(out).glob("*.js"):
        assert "<" not in js.read_text(encoding="utf-8"), js.name


# ---------------------------------------------------------------------------
# P4: theme styles
# ---------------------------------------------------------------------------

def _layout_data(out: Path, n: int = 1) -> dict:
    return _call_args((_layouts_dir(out) / f"{n}.js").read_text(encoding="utf-8"), "layoutPreview")[2]


@pytest.fixture(scope="module")
def styled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("lp_styled")
    out = _build(tmp, "--html", xml=_layout_xml(tmp / "Styled.xml", styled=True))
    data = _layout_data(out)
    return data, {o["id"]: o for o in data["objects"]}


def test_styles_are_resolved_into_a_table(styled):
    data, objs = styled
    st = data["styles"]
    assert st[data["bg"]] == {"background-color": "#f2f2f2"}
    header, body, footer = data["parts"]
    assert st[header["sy"]] == {"background-color": "#a7d2e8"} and st[body["sy"]] == {"background-color": "#ffffff"}
    assert "sy" not in footer  # the theme has no footer style
    # Text in the header: text_box, then "header text_box".
    assert st[objs["1"]["sy"]] == {"color": "#000080", "font-size": "11px"}
    # The named style: button, then button.primary_button (its inner border's radius too).
    assert st[objs["2"]["sy"]] == {"background-color": "#d90b00", "color": "#ffffff", "text-align": "center",
                                   "font-weight": "bold", "border-top-left-radius": "4px"}
    # Local CSS over the theme; hover rules and box-shadow are left out.
    edit = {"border-top-style": "solid", "border-top-width": "1px", "border-top-color": "#cccccc",
            "font-family": '"Helvetica Neue", sans-serif', "font-size": "12px", "color": "#333333",
            "vertical-align": "middle"}
    assert st[objs["3"]["sy"]] == {**edit, "background-color": "rgba(255,252,171,0.5)"}
    assert st[objs["4"]["sy"]] == {**edit, "background-color": "rgba(255,255,255,0.9)"}
    assert objs["4"]["sy"] == objs["5"]["sy"] == objs["8"]["sy"]  # one entry per distinct style
    assert len(st) == len({json.dumps(s, sort_keys=True) for s in st})
    assert "sy" not in objs["7"] and "sy" not in objs["16"]  # tab panels and rectangles: no theme style here
    assert data["problems"]["covered"] == 0  # see-through edit boxes hide nothing


def test_styles_need_the_raw_xml(tmp_path):
    out = _build(tmp_path, "--html", "--no-raw-xml", xml=_layout_xml(tmp_path / "Styled.xml", styled=True))
    data = _layout_data(out)
    assert "styles" not in data and "covered" not in data["problems"]
    assert all("sy" not in o for o in data["objects"])


def test_covered_objects(preview):
    from fm_saxml.analyze.layout_css import LayoutCss, ThemeStyles

    model, _, _ = preview
    opaque = "self:normal .self\n{\n\tbackground-color: rgba(100%,100%,100%,1);\n}\n"
    css = LayoutCss(theme=ThemeStyles("rectangle:normal .self { background-color: rgba(0%,0%,0%,0.5); }"),
                    objects={"5": [(None, opaque)], "10": [(None, opaque)], "19": [(None, opaque)]}, parts=[])
    data = build_layout_preview(model, "layout:ContactDetail", css=css)
    objs = {o["id"]: o for o in data["objects"]}
    ids = [o["id"] for o in data["objects"]]
    # 5 is drawn over 4 at the same spot: 4 can't be seen.
    assert objs["4"]["x"] == ["dup", "cov"] and objs["4"]["cv"] == ids.index("5")
    assert "cov" not in objs["5"].get("x", [])
    # 10 (second tab) sits where 8 (first tab) is, but they are never shown together.
    assert "cov" not in objs["8"].get("x", [])
    # A portal's own row content doesn't hide the portal; see-through rectangles hide nothing.
    assert "cov" not in objs["18"].get("x", [])
    assert data["problems"]["covered"] == 1


def test_everything_bagel_styles(tmp_path):
    out = _build(tmp_path, "--html", xml=ROOT / "EverythingBagel.xml")
    data = _layout_data(out)
    st = data["styles"]
    objs = {o["id"]: o for o in data["objects"]}
    assert st[data["bg"]] == {"background-color": "#f2f2f2"}  # Apex Blue's layout background
    assert [st[p["sy"]]["background-color"] for p in data["parts"]] == ["#a7d2e8", "#ffffff"]
    # Four equal sides are written as one shorthand.
    assert st[objs["2"]["sy"]] == {**st[objs["2"]["sy"]], "background-color": "#f9f9f9", "border-color": "#e6e6e6",
                                   "border-style": "solid", "border-width": "1px", "border-radius": "5px"}
    assert not any(k.startswith("border-top") for k in st[objs["2"]["sy"]])
    assert st[objs["1"]["sy"]]["text-align"] == "right"  # the label's local CSS over the theme's "left"
    assert data["problems"]["covered"] == 0


# ---------------------------------------------------------------------------
# In the browser
# ---------------------------------------------------------------------------

_STUB = """
window.__registered = [];
document.modelContext = {
    registerTool(t) { window.__registered.push(t.name); },
    unregisterTool(name) { window.__registered = window.__registered.filter((n) => n !== name); },
};
"""


@pytest.fixture(scope="module")
def viewer(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    tmp = tmp_path_factory.mktemp("lp_viewer")
    out = _build(tmp, "--webmcp", xml=_layout_xml(tmp / "Preview.xml", styled=True))
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(_STUB)
        page.goto((out / "index.html").as_uri())
        page.wait_for_selector("body[data-rendered]", state="attached", timeout=60000)
        yield page, out, errors
        browser.close()


def _open(page, hash_: str, wait: str = ".fm-lp[data-ready]") -> None:
    page.evaluate("h => { delete document.body.dataset.rendered; FMDocs.ui.go(h); }", hash_)
    page.wait_for_selector("body[data-rendered]", state="attached", timeout=30000)
    page.wait_for_selector(wait, state="attached", timeout=30000)


def _ids(page, selector: str) -> list[str]:
    return page.evaluate(f"[...document.querySelectorAll({json.dumps(selector)})].map(e => e.dataset.id)")


def _route(**params) -> str:
    from urllib.parse import urlencode
    return "#/layout?" + urlencode(params)


def test_layout_page_shows_the_preview_above_the_markdown(viewer):
    page, _, errors = viewer
    _open(page, "#/Layouts/ContactDetail.md")
    assert page.evaluate("document.querySelector('#page-extra details.fm-lp-block').open") is True
    assert len(_ids(page, ".fm-lp-o")) == 20
    # Default: tab "Second" (TabControl default=1) in front, popovers closed.
    visible = set(_ids(page, ".fm-lp-o:not(.off)"))
    assert {"10", "9"} <= visible and not {"7", "8", "12", "13"} & visible
    assert page.evaluate("document.querySelector('.fm-lp-tabs b.on').textContent") == "Second"
    assert page.evaluate("document.querySelector('.fm-lp-o[data-id=\"17\"]').classList.contains('hc')")
    assert errors == []


def test_search_highlights_and_steps_through_matches(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    page.fill(".fm-lp-q", "status")
    page.wait_for_function("document.querySelector('.fm-lp-count').textContent === '1 of 3'")
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["13", "17", "8"]
    assert page.evaluate("document.querySelector('.fm-lp-stage').classList.contains('focusing')")
    page.click(".fm-lp-next")
    assert page.evaluate("document.querySelector('.fm-lp-count').textContent") == "2 of 3"
    # Stepping onto an object in a closed popover opens it.
    page.click(".fm-lp-next")
    assert "13" in _ids(page, ".fm-lp-o:not(.off)")
    page.click(".fm-lp-clear")
    assert _ids(page, ".fm-lp-o.hit") == []


def test_deep_link_selects_and_reveals_the_object(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_", select="layoutObject:ContactDetail::8"))
    assert page.evaluate("document.body.dataset.rendered") == "layout"
    assert "8" in _ids(page, ".fm-lp-o:not(.off)")  # its tab ("First") was brought to the front
    assert page.evaluate("document.querySelector('.fm-lp-tabs b.on').textContent") == "First"
    side = page.inner_text(".fm-lp-side")
    assert "Contact::Status" in side and "top 150, left 20" in side
    assert page.evaluate("document.querySelector('.fm-lp-objlink').getAttribute('href')") == "#/LayoutObjects/ContactDetail/8.md"
    assert page.evaluate("FMDocs.preview.current.selected") == "layoutObject:ContactDetail::8"


def test_highlight_link_from_a_field_page(viewer):
    page, _, _ = viewer
    _open(page, "#/Fields/Contact/Status.md", wait="#page-extra a.fm-lp-show")
    href = page.get_attribute("#page-extra a.fm-lp-show", "href")
    assert href.startswith("#/layout?") and "highlight=8%2C13%2C17" in href
    _open(page, href)
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["13", "17", "8"]


def test_layout_object_page_links_to_the_preview(viewer):
    page, _, _ = viewer
    _open(page, "#/LayoutObjects/ContactDetail/13.md", wait="#page-extra a.fm-lp-show")
    href = page.get_attribute("#page-extra a.fm-lp-show", "href")
    _open(page, href)
    assert "13" in _ids(page, ".fm-lp-o:not(.off)")  # inside a popover: opened
    assert page.evaluate("document.querySelector('[data-popover]').checked") is True


def test_layers_panel_switches_tabs_popovers_and_hide_conditions(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    page.select_option("select[data-control]", label="First")
    visible = set(_ids(page, ".fm-lp-o:not(.off)"))
    assert "8" in visible and "10" not in visible
    page.click(".fm-lp-tabs b:nth-child(2)")  # the tab strip works too
    assert "10" in _ids(page, ".fm-lp-o:not(.off)")
    page.check("[data-popover]")
    assert {"12", "13"} <= set(_ids(page, ".fm-lp-o:not(.off)"))
    page.check("[data-hidehc]")
    assert "17" not in _ids(page, ".fm-lp-o:not(.off)")


def test_clicking_a_point_lists_the_stacked_objects(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    # Objects 4 and 5 are exact duplicates: both under the point, front first.
    assert page.evaluate("FMDocs.preview.current.objectsAt(80, 85)") == [
        "layoutObject:ContactDetail::5", "layoutObject:ContactDetail::4"]
    box = page.evaluate("""(() => { const r = document.querySelector('.fm-lp-o[data-id="5"]').getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2]; })()""")
    page.mouse.click(*box)
    stack = page.evaluate("[...document.querySelectorAll('.fm-lp-stack li')].map(li => li.textContent)")
    assert len(stack) == 2
    page.click(".fm-lp-stack li:nth-child(2) button")
    assert page.evaluate("FMDocs.preview.current.selected") == "layoutObject:ContactDetail::4"


def test_problem_badges_filter(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    badges = page.evaluate("[...document.querySelectorAll('[data-problem]')].map(b => b.dataset.problem + ':' + b.querySelector('.n').textContent)")
    assert badges == ["out:1", "tiny:1", "dup:2"]
    page.click("[data-problem=dup]")
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["4", "5"]
    page.click("[data-problem=out]")
    assert _ids(page, ".fm-lp-o.hit") == ["14"]
    page.click("[data-problem=out]")
    assert _ids(page, ".fm-lp-o.hit") == []


def test_zoom_and_phone_width(viewer):
    page, _, _ = viewer
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    page.click("[data-zoom='2']")
    assert page.evaluate("FMDocs.preview.current.zoom") == 2
    page.set_viewport_size({"width": 390, "height": 800})
    try:
        _open(page, "#/Layouts/ContactDetail.md", wait="#page-extra details.fm-lp-block")
        # Folded on a phone; opening it draws the preview inside its own scroll box.
        assert page.evaluate("document.querySelector('#page-extra details').open") is False
        page.click("#page-extra details > summary")
        page.wait_for_selector(".fm-lp[data-ready]", state="attached")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.evaluate("document.querySelector('main').scrollWidth <= document.querySelector('main').clientWidth")
    finally:
        page.set_viewport_size({"width": 1400, "height": 1000})


def test_styled_and_wireframe(viewer):
    page, _, errors = viewer
    page.evaluate("localStorage.removeItem('fm-saxml-layout-preview-mode')")
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    color = ("sel => { const e = document.querySelector(`.fm-lp-o[data-id='${sel}']`); const s = getComputedStyle(e);"
             " return [s.backgroundColor, s.color, s.fontWeight, s.borderTopLeftRadius]; }")
    # Styled by default: the theme's colours.
    assert page.evaluate("FMDocs.preview.current.mode") == "styled"
    assert page.evaluate("document.querySelector('.fm-lp-stage').classList.contains('styled')")
    assert page.evaluate(color, "2") == ["rgb(217, 11, 0)", "rgb(255, 255, 255)", "700", "4px"]
    assert page.evaluate(color, "3")[0] == "rgba(255, 252, 171, 0.5)"
    assert page.evaluate("getComputedStyle(document.querySelector('.fm-lp-layoutbox')).backgroundColor") == "rgb(242, 242, 242)"
    assert page.evaluate("getComputedStyle(document.querySelector('.fm-lp-part')).backgroundColor") == "rgb(167, 210, 232)"
    assert page.evaluate("getComputedStyle(document.querySelector(`.fm-lp-o[data-id='4']`)).justifyContent") == "center"
    # Closed popovers and other tabs stay hidden in the styled look too.
    hidden = "id => getComputedStyle(document.querySelector(`.fm-lp-o[data-id='${id}']`)).display"
    assert page.evaluate(hidden, "13") == "none" and page.evaluate(hidden, "8") == "none"
    assert page.evaluate(hidden, "10") == "flex"
    # Wireframe: the kind colours, and the choice is remembered.
    page.click("[data-mode='wireframe']")
    assert page.evaluate("FMDocs.preview.current.mode") == "wireframe"
    assert page.evaluate(color, "2")[0] != "rgb(217, 11, 0)"
    assert page.evaluate("localStorage.getItem('fm-saxml-layout-preview-mode')") == "wireframe"
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    assert page.evaluate("FMDocs.preview.current.mode") == "wireframe"
    page.click("[data-mode='styled']")
    assert page.evaluate("[...document.querySelectorAll('[data-mode]')].map(b => b.getAttribute('aria-pressed'))") == ["true", "false"]
    # Tools report the resolved style.
    body = _run(page, "locate_layout_object", {"layout": "ContactDetail", "text": "Send", "display": False})
    assert _by_id(body)["2"]["style"]["background-color"] == "#d90b00"
    assert not errors


def test_results_view_rows_link_to_the_preview(viewer):
    page, _, errors = viewer
    page.evaluate("FMDocs.tools.query_entities.execute({type: 'layoutObject', where: [{field: 'objectType', op: 'eq', value: 'Edit Box'}]})")
    page.wait_for_function("document.body.dataset.rendered === 'results'")
    links = page.evaluate("[...document.querySelectorAll('.fm-results a.fm-lp-show')].map(a => a.getAttribute('href'))")
    assert links and all(h.startswith("#/layout?doc=layout%3AContactDetail") and "select=" in h for h in links)
    assert errors == []


# ---------------------------------------------------------------------------
# P3: WebMCP tools and the FMDocs.preview API
# ---------------------------------------------------------------------------

_OBJ = "layoutObject:ContactDetail::"


def _run(page, name: str, args: dict, error: bool = False) -> dict:
    res = page.evaluate("([n, a]) => FMDocs.tools[n].execute(a)", [name, args])
    body = json.loads(res["content"][0]["text"])
    assert bool(res.get("isError")) == error, body
    return body


def _by_id(body: dict) -> dict:
    return {i["objectId"]: i for i in body["items"]}


def test_llms_txt_lists_the_layout_tools_only_with_the_preview(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    text = (_build(tmp_path / "a", "--webmcp") / "llms.txt").read_text(encoding="utf-8")
    assert all(n in text for n in ("locate_layout_object", "objects_at", "layout_problems"))
    assert "where objects are on layouts" in text and "#/layout?doc=" in text
    text = (_build(tmp_path / "b", "--webmcp", "--no-layout-preview") / "llms.txt").read_text(encoding="utf-8")
    assert "find_references" in text and "locate_layout_object" not in text and "#/layout?doc=" not in text


def test_locate_layout_object_by_field(viewer):
    page, _, errors = viewer
    body = _run(page, "locate_layout_object", {"field": "field:Contact::Status", "display": False})
    assert body["total"] == 3 and body["layoutsSearched"] == 1
    items = _by_id(body)
    assert set(items) == {"8", "13", "17"}
    on_tab = items["8"]
    assert on_tab["docId"] == _OBJ + "8" and on_tab["type"] == "layoutObject" and on_tab["part"] == "Body"
    # Absolute bounds (the model's are relative to the tab panel), the tab it is on, and words.
    assert on_tab["bounds"] == {"top": 150, "left": 20, "bottom": 170, "right": 160, "width": 140, "height": 20}
    assert on_tab["shownIn"] == [{"docId": _OBJ + "7", "kind": "tabPanel", "name": None, "label": "First"}]
    assert on_tab["visibleAtOpen"] is False  # the default tab is "Second"
    assert on_tab["position"] == "Body, middle left, inside the 'First' tab"
    assert on_tab["parent"] == {"docId": "layout:ContactDetail", "type": "layout", "name": "ContactDetail"}
    assert on_tab["path"] == "LayoutObjects/ContactDetail/8.md"
    assert on_tab["previewUrl"].endswith("#/layout?doc=layout%3AContactDetail&file=_&select=layoutObject%3AContactDetail%3A%3A8")
    assert items["13"]["shownIn"][0]["kind"] == "popover" and "inside the 'More' popover" in items["13"]["position"]
    assert items["17"]["visibleAtOpen"] is True and items["17"]["hideCondition"] == "IsEmpty ( Contact::Status )"
    assert items["17"]["position"].endswith("(has a hide condition)")
    assert body["layouts"][0]["count"] == 3 and "highlight=8%2C13%2C17" in body["layouts"][0]["previewUrl"]
    # By name, by text, by script, by type; and a layout given by name.
    assert {i["objectId"] for i in _run(page, "locate_layout_object", {"field": "status", "display": False})["items"]} == {"8", "13", "17"}
    assert [i["objectId"] for i in _run(page, "locate_layout_object", {"script": "script:SendEmail", "display": False})["items"]] == ["2"]
    assert [i["objectId"] for i in _run(page, "locate_layout_object", {"text": "second tab", "display": False})["items"]] == ["10"]
    portals = _run(page, "locate_layout_object", {"layout": "contactdetail", "objectType": "portal", "display": False})
    assert [i["objectId"] for i in portals["items"]] == ["18"]
    assert _run(page, "locate_layout_object", {"display": False}, error=True)["error"].startswith("Give field")
    assert "layouts" in _run(page, "locate_layout_object", {"layout": "Nope", "field": "x", "display": False}, error=True)
    assert errors == []


def test_locate_shows_results_with_links_to_the_preview(viewer):
    page, _, _ = viewer
    _run(page, "locate_layout_object", {"field": "Status"})
    page.wait_for_selector(".fm-results p.fm-lp-links a.fm-lp-show", state="attached", timeout=30000)
    summary = page.get_attribute(".fm-results p.fm-lp-links a.fm-lp-show", "href")
    assert summary.startswith("#/layout?doc=layout%3AContactDetail") and "highlight=8%2C13%2C17" in summary
    rows = page.evaluate("[...document.querySelectorAll('.fm-results li .fm-detail')].map(d => d.textContent)")
    assert any("inside the 'First' tab" in r for r in rows)
    _open(page, summary)
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["13", "17", "8"]


def test_objects_at_a_point_and_in_a_rect(viewer):
    page, _, _ = viewer
    body = _run(page, "objects_at", {"layout": "layout:ContactDetail", "x": 80, "y": 85, "display": False})
    assert [(i["objectId"], i["front"]) for i in body["items"]] == [("5", 1), ("4", 2)]  # front to back
    assert body["layoutDocId"] == "layout:ContactDetail" and body["at"] == {"x": 80, "y": 85}
    # Over the tab control: both tabs' objects and the control (not its panels) unless visibleAtOpen.
    on_tabs = _run(page, "objects_at", {"layout": "ContactDetail", "x": 30, "y": 160, "display": False})
    assert [i["objectId"] for i in on_tabs["items"]] == ["10", "8", "6"]
    seen = _run(page, "objects_at", {"layout": "ContactDetail", "x": 30, "y": 160, "visibleAtOpen": True, "display": False})
    assert [i["objectId"] for i in seen["items"]] == ["10", "6"]
    # Popover contents float above everything else.
    pop = _run(page, "objects_at", {"layout": "ContactDetail", "x": 50, "y": 320, "display": False})
    assert [i["objectId"] for i in pop["items"]][:2] == ["13", "12"]
    rect = _run(page, "objects_at", {"layout": "ContactDetail", "rect": {"top": 0, "left": 0, "bottom": 40, "right": 400},
                                     "within": True, "display": False})
    assert {i["objectId"] for i in rect["items"]} == {"1", "2"}
    assert "x and y" in _run(page, "objects_at", {"layout": "ContactDetail", "display": False}, error=True)["error"]


def test_layout_problems(viewer):
    page, _, _ = viewer
    body = _run(page, "layout_problems", {"display": False})
    assert body["counts"] == {"outside": 1, "tiny": 1, "duplicate": 2, "covered": 0} and body["total"] == 4
    items = _by_id(body)
    assert items["4"]["problems"] == ["duplicate"] and items["4"]["sameAs"] == [_OBJ + "5"]
    assert items["14"]["problems"] == ["outside"] and "50 pt past its right edge" in items["14"]["position"]
    assert body["layouts"] == [{**body["layouts"][0], "layout": "ContactDetail", "count": 4, "outside": 1, "tiny": 1, "duplicate": 2}]
    only = _run(page, "layout_problems", {"layout": "ContactDetail", "kinds": ["tiny"], "display": False})
    assert [i["objectId"] for i in only["items"]] == ["16"] and only["counts"]["tiny"] == 1
    assert "validKinds" in _run(page, "layout_problems", {"kinds": ["nope"], "display": False}, error=True)


def test_show_on_this_layout_highlights_on_the_page(viewer):
    page, _, errors = viewer
    _open(page, "#/Layouts/ContactDetail.md")
    assert "show_on_this_layout" in page.evaluate("window.__registered")
    body = _run(page, "show_on_this_layout", {"query": "status"})
    assert body["total"] == 3 and body["highlighted"] == 3 and body["items"][0]["bounds"]
    assert page.evaluate("document.body.dataset.rendered") == "Layouts/ContactDetail.md"  # stays on the page
    assert sorted(_ids(page, "#page-extra .fm-lp-o.hit")) == ["13", "17", "8"]
    one = _run(page, "show_on_this_layout", {"docIds": ["14"], "objectType": "Rectangle"})
    assert [i["objectId"] for i in one["items"]] == ["14"] and _ids(page, ".fm-lp-o.hit") == ["14"]
    none = _run(page, "show_on_this_layout", {"field": "Nope"})
    assert none["total"] == 0 and _ids(page, ".fm-lp-o.hit") == []
    # The full-page preview has it too; other pages don't.
    _open(page, _route(doc="layout:ContactDetail", file="_"))
    assert "show_on_this_layout" in page.evaluate("window.__registered")
    _run(page, "show_on_this_layout", {"field": "FullName"})
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["19", "4", "5"]
    _open(page, "#/Tables/Contact.md", wait="body")
    assert "show_on_this_layout" not in page.evaluate("window.__registered")
    assert errors == []


def test_show_on_this_layout_opens_a_folded_preview(viewer):
    page, _, _ = viewer
    page.set_viewport_size({"width": 390, "height": 800})
    try:
        _open(page, "#/Layouts/ContactDetail.md", wait="#page-extra details.fm-lp-block")
        assert page.evaluate("document.querySelector('#page-extra details').open") is False
        _run(page, "show_on_this_layout", {"docIds": [_OBJ + "2"]})
        assert page.evaluate("document.querySelector('#page-extra details').open") is True
        assert _ids(page, ".fm-lp-o.hit") == ["2"]
    finally:
        page.set_viewport_size({"width": 1400, "height": 1000})


def test_preview_js_api_open_highlight_clear(viewer):
    page, _, _ = viewer
    _open(page, "#/index.md", wait="body")
    res = page.evaluate("FMDocs.preview.open('ContactDetail', {highlight: ['14', 'nope']})")
    assert res["layout"] == "layout:ContactDetail" and res["highlighted"] == [_OBJ + "14"]
    assert "#/layout?doc=layout%3AContactDetail" in res["url"]
    page.wait_for_function("document.body.dataset.rendered === 'layout'")
    assert _ids(page, ".fm-lp-o.hit") == ["14"]
    # In place on the preview on screen: no navigation.
    assert page.evaluate("FMDocs.preview.highlight([`${'layoutObject:ContactDetail::'}4`, '5'])") == [_OBJ + "4", _OBJ + "5"]
    assert sorted(_ids(page, ".fm-lp-o.hit")) == ["4", "5"]
    res = page.evaluate("FMDocs.preview.open('layout:ContactDetail', {select: 'layoutObject:ContactDetail::8'})")
    assert page.evaluate("FMDocs.preview.current.selected") == _OBJ + "8"
    assert page.evaluate("FMDocs.preview.clear()") is True and _ids(page, ".fm-lp-o.hit") == []
    assert page.evaluate("FMDocs.preview.open('Nope').then(() => 'ok', (e) => e.message)") == "No layout preview for 'Nope'."
    # get_current_page says what the preview shows.
    cur = _run(page, "get_current_page", {})
    assert cur["path"].startswith("layout?") and cur["preview"] == {"layoutDocId": "layout:ContactDetail", "selected": None}


def test_layout_tools_by_url_and_in_the_agents_guide(viewer):
    page, out, _ = viewer
    from urllib.parse import quote
    context = page.context.browser.new_context()  # no WebMCP stub: an agent that only reads pages
    try:
        p = context.new_page()
        q = json.dumps({"tool": "locate_layout_object", "args": {"field": "Status"}})
        p.goto((out / "index.html").as_uri() + "#/results?q=" + quote(q) + "&format=json")
        p.wait_for_selector("#fm-result-json", timeout=60000)
        body = json.loads(p.inner_text("#fm-result-json"))
        assert body["total"] == 3 and all(i["previewUrl"].startswith("file:") for i in body["items"])
        p.goto((out / "index.html").as_uri() + "#/agents")
        p.wait_for_selector(".fm-agents h3", timeout=60000)
        names = p.evaluate("[...document.querySelectorAll('.fm-agents h3 code')].map(c => c.textContent)")
        assert {"locate_layout_object", "objects_at", "layout_problems"} <= set(names)
        assert "show_on_this_layout" not in names and "FMDocs.preview.open" in p.inner_text(".fm-agents")
        example = p.evaluate("[...document.querySelectorAll('.fm-agents a')].find(a => a.textContent === 'open as JSON'"
                             " && a.href.includes('objects_at')).href")
        p.goto(example)
        p.wait_for_selector("#fm-result-json")
        assert json.loads(p.inner_text("#fm-result-json"))["total"] >= 1
    finally:
        context.close()


def test_locate_tries_table_field_as_a_field_doc_id(viewer):
    page, _, _ = viewer
    # Object 19 shows Contact::FullName through the TO "Contact__selfJoin": a TO::field text match would miss it.
    body = _run(page, "locate_layout_object", {"field": "Contact::FullName", "display": False})
    assert {i["objectId"] for i in body["items"]} == {"4", "5", "19"} and body["fieldDocId"] == "field:Contact::FullName"
    assert {i["objectId"] for i in _run(page, "locate_layout_object", {"field": "contact::fullname", "display": False})["items"]} == {"4", "5", "19"}
    # No field by that docId: the TO::field text as shown on the layout.
    body = _run(page, "locate_layout_object", {"field": "Contact__selfJoin::FullName", "display": False})
    assert [i["objectId"] for i in body["items"]] == ["19"] and "fieldDocId" not in body


def _container_names_xml(dest: Path) -> Path:
    """The test layout with a named portal, a named popover panel and a popover button whose label is a merge."""
    xml = _layout_xml(dest, styled=True).read_text(encoding="utf-8")
    xml = xml.replace('<LayoutObject id="18" type="Portal" name=""', '<LayoutObject id="18" type="Portal" name="portal_rows"', 1)
    xml = xml.replace('<LayoutObject id="12" type="PopoverPanel" name=""', '<LayoutObject id="12" type="PopoverPanel" name="More.popover"', 1)
    xml = xml.replace("<![CDATA[More]]>", "<![CDATA[<<$$label>>]]>", 1)
    dest.write_text(xml, encoding="utf-8")
    return dest


def _other_page(viewer):
    """A fresh page in the viewer fixture's browser (one Playwright per process)."""
    context = viewer[0].context.browser.new_context(viewport={"width": 1400, "height": 1000})
    return context, context.new_page()


def test_container_names_are_not_drawn_as_labels(viewer, tmp_path):
    out = _build(tmp_path, "--html", xml=_container_names_xml(tmp_path / "Names.xml"))
    if True:
        context, page = _other_page(viewer)
        try:
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto((out / "index.html").as_uri())
            page.wait_for_selector("body[data-rendered]", state="attached", timeout=60000)
            page.evaluate("localStorage.removeItem('fm-saxml-layout-preview-mode')")
            _open(page, _route(doc="layout:ContactDetail", file="_", select="layoutObject:ContactDetail::19"))
            text = "id => { const e = document.querySelector(`.fm-lp-o[data-id='${id}'] > .t`);" \
                   " return e ? [e.className, e.textContent, getComputedStyle(e).display] : null; }"
            # Styled: no text at all on the portal or the popover panel; Wireframe: a corner caption.
            assert page.evaluate("FMDocs.preview.current.mode") == "styled"
            assert page.evaluate(text, "18") == ["t cap", "portal_rows", "none"]
            assert page.evaluate(text, "12")[:2] == ["t cap", "More.popover"]
            page.click("[data-mode='wireframe']")
            assert page.evaluate(text, "18")[2] != "none"
            # The details panel names the container; the layers panel names the popover.
            side = page.inner_text(".fm-lp-side")
            assert 'portal "portal_rows"' in side
            assert page.evaluate("document.querySelector('[data-popover]').parentElement.textContent.trim()") \
                == "<<$$label>> (More.popover)"
            assert errors == []
        finally:
            context.close()


def test_multi_file_field_shown_on_another_files_layout(viewer, tmp_path):
    if not MULTI.exists():
        pytest.skip("multi-file sample not present")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(MULTI), "-o", str(out), "-f", "--html", "--webmcp"])
    assert result.exit_code == 0, result.output
    if True:
        context, page = _other_page(viewer)
        try:
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(_STUB)
            page.goto((out / "index.html").as_uri())
            page.wait_for_selector("body[data-rendered]", state="attached", timeout=60000)
            # FileB's layout "FileA" shows FileA::PrimaryKey: found by its docId and as Table::Field.
            for field in ("field:FileA::PrimaryKey", "FileA::PrimaryKey"):
                body = _run(page, "locate_layout_object", {"field": field, "display": False})
                where = {(i["file"], i["parent"]["name"]) for i in body["items"]}
                assert ("FileB", "FileA") in where, (field, where)
            # The field's page (in FileA) links to the layout in FileB.
            _open(page, "#/FileA/Fields/FileA/PrimaryKey.md", wait="#page-extra a.fm-lp-show")
            hrefs = page.evaluate("[...document.querySelectorAll('#page-extra a.fm-lp-show')].map(a => a.getAttribute('href'))")
            assert any("file=FileB" in h for h in hrefs), hrefs
            _open(page, next(h for h in hrefs if "file=FileB" in h))
            assert _ids(page, ".fm-lp-o.hit")
            assert errors == []
        finally:
            context.close()
