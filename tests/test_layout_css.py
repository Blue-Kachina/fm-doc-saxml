"""FileMaker theme CSS → plain CSS for the layout preview (analyze/layout_css.py, layout_preview.md P4).

One test per dialect function, then the cascade, on hand-made rules and on the Apex Blue
theme of the tracked EverythingBagel.xml.
"""

from __future__ import annotations

from pathlib import Path

import orjson
import pytest
from lxml import etree

from fm_saxml.analyze.layout_css import (
    StyleSource,
    ThemeStyles,
    clean_declarations,
    compact_style,
    element_for,
    is_opaque,
    parse_color,
    parse_declarations,
    parse_font_family,
    parse_length,
    parse_radius,
    parse_rules,
    parse_vertical_align,
    part_element,
    resolve_style,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def apex_blue() -> ThemeStyles:
    root = etree.parse(str(ROOT / "EverythingBagel.xml"), etree.XMLParser(huge_tree=True, resolve_entities=False)).getroot()
    themes = [el for el in root.iter() if isinstance(el.tag, str) and etree.QName(el).localname == "Theme"]
    assert [t.get("name") for t in themes] == ["com.filemaker.theme.apex_blue"]
    css = next(c.text for c in themes[0] if isinstance(c.tag, str) and etree.QName(c).localname == "CSS")
    return ThemeStyles(css)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("rgba(100%,100%,100%,1)", "#ffffff"),
    ("rgba(52.549%,80.3922%,30.1961%,1)", "#86cd4d"),
    ("rgba(86.2745%,86.2745%,86.2745%,0.6)", "rgba(220,220,220,0.6)"),
    ("rgba(100%,100%,100%,0)", "rgba(255,255,255,0)"),
    ("rgba( 0% , 0% , 0% , 50% )", "rgba(0,0,0,0.5)"),
    ("rgb(255,128,0)", "#ff8000"),
    ("rgba(300,-5,0,2)", "#ff0000"),  # clamped
    ("#ABCDEF", "#abcdef"),
    ("transparent", "rgba(0,0,0,0)"),
    ("red", None),
    ("rgba(1,2)", None),
    ("url(javascript:alert(1))", None),
])
def test_parse_color(value, expected):
    assert parse_color(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("5pt", "5px"), ("0.25pt", "0.25px"), ("0pt", "0"), ("0", "0"), ("12px", "12px"),
    ("0.67em", "0.67em"), ("50%", "50%"), ("1line", None), ("5", None), ("calc(1pt)", None), ("99999pt", None),
])
def test_parse_length(value, expected):
    assert parse_length(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("5pt 5pt", "5px"), ("4pt 8pt", "4px 8px"), ("50% 50%", "50%"), ("0pt 0pt", "0"), ("3pt", "3px"),
    ("1pt 2pt 3pt", None), ("", None), ("auto auto", None),
])
def test_parse_radius(value, expected):
    assert parse_radius(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("-fm-font-family(arial,sans-serif,ArialMT;sans-serif)", '"arial", sans-serif'),
    ("-fm-font-family(Helvetica Neue,HelveticaNeue-Bold)", '"Helvetica Neue", sans-serif'),
    ("-fm-font-family(Times New Roman,TimesNewRomanPSMT;serif)", '"Times New Roman", serif'),
    ("-fm-font-family(\xff0Qˇ,ArialMT)", '"ArialMT", sans-serif'),  # an unusable display name
    ("-fm-font-family(\xff0Qˇ,\xff0Qˇ)", None),
    ("Georgia, serif", '"Georgia", serif'),
    ('"Comic Sans MS"', '"Comic Sans MS", sans-serif'),
    ("x\"; } body { color: red", None),
])
def test_parse_font_family(value, expected):
    assert parse_font_family(value) == expected


@pytest.mark.parametrize("value, expected", [("top", "top"), ("center", "middle"), ("bottom", "bottom"),
                                             (" Center ", "middle"), ("baseline", None)])
def test_parse_vertical_align(value, expected):
    assert parse_vertical_align(value) == expected


def test_parse_declarations_keeps_semicolons_inside_parentheses():
    decls = parse_declarations("\n\tfont-family: -fm-font-family(a,b;sans-serif);\n\tColor: red;\n\tbad;\n\tcolor: blue")
    assert decls == {"font-family": "-fm-font-family(a,b;sans-serif)", "color": "blue"}


def test_parse_rules_reads_every_selector_form():
    rules = parse_rules("""/* Object Styles */
edit_box:normal .self { color: rgba(0%,0%,0%,1); }
button.FM-1A2B-3C:hover .inner_border { padding-left: 2pt; }
header text_box:normal .self { font-size: 9pt; }
self.FM-1A2B-3C
{
}
leading_sub_summary_1:normal .self, footer:normal .self { background-color: rgba(0%,0%,0%,1); }
weird > thing { color: red; }
""")
    got = [(r.context, r.element, r.cls, r.state, r.sub) for r in rules]
    assert got == [
        (None, "edit_box", None, "normal", "self"),
        (None, "button", "FM-1A2B-3C", "hover", "inner_border"),
        ("header", "text_box", None, "normal", "self"),
        (None, "self", "FM-1A2B-3C", "normal", "self"),  # no state: normal; no sub-element: the box
        (None, "leading_sub_summary_1", None, "normal", "self"),
        (None, "footer", None, "normal", "self"),
    ]
    assert rules[2].decls == {"font-size": "9pt"}


def test_clean_declarations_keeps_the_whitelist_only():
    decls = {
        "background-color": "rgba(100%,0%,0%,1)", "background-image": "url(x.png)", "box-shadow": "0 0 1pt red",
        "border-top-style": "dashed", "border-left-style": "wavy", "border-top-width": "2pt",
        "border-top-right-radius": "4pt 4pt", "font-weight": "bold", "font-style": "italic", "font-size": "14pt",
        "text-align": "center", "-fm-text-vertical-align": "bottom", "-fm-icon-color": "rgba(0%,0%,0%,1)",
        "padding-left": "0.5em", "margin-top": "3pt", "line-height": "1line", "color": "nope",
    }
    assert clean_declarations(decls) == {
        "background-color": "#ff0000", "border-top-style": "dashed", "border-top-width": "2px",
        "border-top-right-radius": "4px", "font-weight": "bold", "font-style": "italic", "font-size": "14px",
        "text-align": "center", "vertical-align": "bottom", "padding-left": "0.5em",
        "icon-color": "#000000",  # P5: the icon colour, which the viewer paints glyph icons with
    }
    assert clean_declarations(decls, only={"padding-left"}) == {"padding-left": "0.5em"}


def test_icon_colour_comes_from_the_icon_sub_element():
    theme = ThemeStyles("button:normal .self { color: rgba(0%,0%,0%,1); } "
                        "button:normal .icon { -fm-icon-color: rgba(100%,100%,100%,1); padding-left: 9pt; } "
                        "button.blue:normal .icon { -fm-icon-color: rgba(0%,0%,100%,1); }")
    assert resolve_style(theme, "button") == {"color": "#000000", "icon-color": "#ffffff"}  # .icon gives only the colour
    assert resolve_style(theme, "button", "blue")["icon-color"] == "#0000ff"
    local = "self:normal .icon { -fm-icon-color: rgba(100%,0%,0%,1); }"
    assert resolve_style(theme, "button", None, local)["icon-color"] == "#ff0000"


def test_compact_style():
    sides = {f"border-{s}-{p}": v for s in ("top", "right", "bottom", "left")
             for p, v in (("color", "#000000"), ("width", "1px"), ("style", "solid"))}
    radii = {f"border-{c}-radius": "4px" for c in ("top-left", "top-right", "bottom-right", "bottom-left")}
    pads = {"padding-top": "1px", "padding-right": "2px", "padding-bottom": "1px", "padding-left": "2px"}
    assert compact_style({**sides, **radii, **pads, "color": "#ffffff"}) == {
        "border-color": "#000000", "border-width": "1px", "border-style": "solid", "border-radius": "4px",
        **pads, "color": "#ffffff"}
    # Unequal sides, a missing side and two-value radii stay as they are.
    uneven = {**sides, "border-left-width": "2px"}
    assert "border-left-width" in compact_style(uneven) and "border-width" not in compact_style(uneven)
    assert compact_style({"border-top-color": "#000000"}) == {"border-top-color": "#000000"}
    two = {k: "4px 8px" for k in radii}
    assert compact_style(two) == two


def test_is_opaque():
    assert is_opaque({"background-color": "#ffffff"})
    assert not is_opaque({"background-color": "rgba(255,255,255,0.9)"})
    assert not is_opaque({"color": "#000000"}) and not is_opaque(None)


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------

def test_element_for():
    assert element_for("Edit Box") == "edit_box" and element_for("Text") == "text_box"
    assert element_for("Drop-down Calendar") == "calendar" and element_for("PopoverPanel") == "popover"
    assert element_for("Button", "Button Bar") == "button_bar_segment" and element_for("Button") == "button"
    assert element_for("Panel", "Tab Control") == "tab_panel" and element_for("Panel", "Slide Control") is None
    assert element_for("Group") is None and element_for("Grouped Button") is None and element_for(None) is None


def test_part_element():
    assert part_element("Top Navigation") == "top_nav_part" and part_element("Body") == "body"
    assert part_element("Leading Sub-summary") == "leading_sub_summary"
    assert part_element("Some New Part") == "some_new_part" and part_element(None) is None


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------

_THEME = """
edit_box:normal .self { background-color: rgba(100%,100%,100%,1); color: rgba(0%,0%,0%,1); font-size: 12pt; }
edit_box:normal .inner_border { border-top-left-radius: 3pt 3pt; padding-left: 2pt; background-color: rgba(0%,0%,0%,1); }
edit_box:normal .text { padding-top: 1pt; color: rgba(100%,0%,0%,1); }
edit_box:focus .self { background-color: rgba(0%,0%,100%,1); }
edit_box.minimal:normal .self { background-color: rgba(0%,0%,0%,0); }
body edit_box:normal .self { font-size: 10pt; }
button:normal .self { color: rgba(0%,0%,100%,1); text-align: center; }
shape.FM-AA:normal .self { background-color: rgba(100%,100%,0%,1); }
rectangle:normal .self { border-top-style: solid; }
layout_background:normal .self { background-color: rgba(50%,50%,50%,1); background-image: none; }
"""


def test_theme_rule_merges_box_inner_border_and_text():
    t = ThemeStyles(_THEME)
    # The box takes everything; the inner border only its radii and padding; the text its padding.
    assert t.rule("edit_box") == {"background-color": "#ffffff", "color": "#000000", "font-size": "12px",
                                  "border-top-left-radius": "3px", "padding-left": "2px", "padding-top": "1px"}
    assert t.rule("edit_box", context="body") == {"font-size": "10px"}
    assert t.rule("nothing") == {} and bool(t) and not ThemeStyles("")


def test_named_style_lookup():
    t = ThemeStyles(_THEME)
    assert t.style_element("edit_box", "minimal") == "edit_box"
    assert t.style_element("rectangle", "FM-AA") == "shape"     # a rectangle's custom styles are shape.…
    assert t.style_element("edit_box", "FM-AA") == "shape"      # any element as a last resort
    assert t.style_element("edit_box", "missing") is None


def test_resolve_style_cascade_order():
    t = ThemeStyles(_THEME)
    # theme element → element in its part → named style → local CSS; only the normal state.
    local = "self:normal .self\n{\n\tcolor: rgba(0%,50.1961%,0%,1);\n}\nself:hover .self { color: rgba(0%,0%,0%,1); }\n"
    style = resolve_style(t, "edit_box", "minimal", local, part="body")
    assert style == {"background-color": "rgba(0,0,0,0)", "color": "#008000", "font-size": "10px",
                     "border-top-left-radius": "3px", "padding-left": "2px", "padding-top": "1px"}
    # A named style found under another element brings that element's base style first.
    assert resolve_style(t, "rectangle", "FM-AA") == {"border-top-style": "solid", "background-color": "#ffff00"}
    assert resolve_style(t, "oval", "FM-AA") == {"background-color": "#ffff00"}
    # No theme: local CSS alone; no element and no local CSS: nothing.
    assert resolve_style(None, "edit_box", None, local) == {"color": "#008000"}
    assert resolve_style(t, None) == {}


def test_apex_blue_elements(apex_blue):
    assert apex_blue.rule("layout_background") == {"background-color": "#f2f2f2"}
    assert apex_blue.rule("top_nav_part") == {"background-color": "#a7d2e8"}
    edit = apex_blue.rule("edit_box")
    assert edit["background-color"] == "#f9f9f9" and edit["border-top-color"] == "#e6e6e6"
    assert edit["border-top-left-radius"] == "5px" and edit["font-size"] == "16px"
    text = apex_blue.rule("text_box")
    assert text == {"font-family": '"HelveticaNeue", sans-serif', "font-size": "16px", "color": "#282828",
                    "text-align": "left", "vertical-align": "middle"}
    # A built-in named style of the theme.
    primary = resolve_style(apex_blue, "button", "primary_button")
    assert primary["background-color"] == "#0091ce" and primary["color"] == "#ffffff"
    assert apex_blue.style_element("button", "primary_button") == "button"


def test_apex_blue_with_everything_bagel_local_css(apex_blue):
    root = etree.parse(str(ROOT / "EverythingBagel.xml"), etree.XMLParser(huge_tree=True, resolve_entities=False)).getroot()
    local = [el for el in root.iter() if isinstance(el.tag, str) and etree.QName(el).localname == "LocalCSS"]
    assert local and all(el.get("name") == "" for el in local)
    style = resolve_style(apex_blue, "text_box", None, local[0].text, part="body")
    assert style["text-align"] == "right" and style["color"] == "#282828"


# ---------------------------------------------------------------------------
# Reading a docs folder
# ---------------------------------------------------------------------------

def test_style_source_reads_the_raw_files(tmp_path):
    assert StyleSource.load(tmp_path) is None  # no raw/: wireframe only
    raw = tmp_path / "raw"
    raw.mkdir()
    theme = '<Theme name="My Theme"><CSS><![CDATA[edit_box:normal .self { color: rgba(100%,0%,0%,1); }]]></CSS></Theme>'
    layout = ('<Layout id="1" name="L"><LayoutThemeReference name="My Theme"/><PartsList>'
              '<Part type="Body"><Definition><LocalCSS name="FM-B" displayName="B"><![CDATA[self.FM-B {}]]></LocalCSS>'
              '</Definition><ObjectList><LayoutObject id="7" type="Edit Box"><LocalCSS name="minimal" displayName="M">'
              '<![CDATA[self:normal .self { font-size: 9pt; }]]></LocalCSS></LayoutObject></ObjectList></Part>'
              '</PartsList></Layout>')
    (raw / "themes.json").write_bytes(orjson.dumps({"xml": {"theme:My Theme": theme}}))
    (raw / "layouts.json").write_bytes(orjson.dumps({"xml": {"layout:L": layout}}))
    source = StyleSource.load(tmp_path)
    css = source.layout("layout:L")  # the theme from the layout's own reference
    assert css.theme.rule("edit_box") == {"color": "#ff0000"}
    assert css.parts == [("FM-B", "self.FM-B {}")]
    assert css.object_local("7") == ("minimal", "self:normal .self { font-size: 9pt; }")
    assert css.object_local("99") == (None, None)
    assert source.layout("layout:missing") is None
    (raw / "layouts.json").write_bytes(b"not json")
    assert StyleSource.load(tmp_path) is None
