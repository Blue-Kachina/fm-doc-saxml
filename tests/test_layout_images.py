"""Icons and images in the HTML viewer's layout preview (layout_preview.md, phase P5).

The hand-made layout of test_layout_preview.py gets a ``<LibraryCatalog>`` and images in both
forms FileMaker writes: a button icon stored inline on the object (SaXML 2.2) and catalog
references (SaXML 2.3) from a popover button and from graphics. SVG button icons are written
by default; pictures and SVG graphics only with ``--layout-images``. The last test draws them
in Chrome (skipped without Playwright): ``uv run --with playwright pytest tests/test_layout_images.py``.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from lxml import etree

from fm_saxml.cli import _run_pipeline, app
from fm_saxml.parser.coverage import xml_inventory
from fm_saxml.parser.extractors.library import extract_library, object_image, parse_streams
from fm_saxml.render.html import VIEWER_DIR
from fm_saxml.render.html.layout_preview import IMAGE_MAX_BYTES, build_layout_preview, sanitize_svg

from .test_layout_preview import MAC_SAMPLE, _STUB, _build, _call_args, _layout_data, _layout_xml, _obj, _route, runner

# A glyph icon with everything the sanitizer must take out. Its shape has fill="none": FileMaker
# paints the fm_fill class in the style's icon colour anyway.
_SVG_ICON = ('<?xml version="1.0" encoding="utf-8"?><!-- Generator: SomeEditor, jsmithy -->'
             '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'xmlns:x="urn:editor" viewBox="0 0 24 24" onload="alert(1)" x:private="1">'
             '<metadata>jsmithy</metadata><script>alert(2)</script>'
             '<g class="fm_fill"><rect x="2" y="2" width="20" height="20" fill="none"/></g>'
             '<image xlink:href="http://example.com/x.png" width="1" height="1"/>'
             '<use href="#a" style="fill: url(http://example.com/f)"/></svg>')
_SVG_LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#c00"/></svg>'
_PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
# The original file name: length-prefixed, XOR 0x5A, here a Mac path with a user name. Never written.
_FNAM = bytes(b ^ 0x5A for b in b"\x00\x00\x00\x01Macintosh HD/Users/jsmithy/Desktop/icon.svg").hex().upper()

KEYS = {"svg": "A" * 32, "png": "B" * 32, "big": "C" * 32, "pdf": "D" * 32, "logo": "E" * 32}


def _b64(data: str | bytes) -> str:
    return base64.b64encode(data.encode() if isinstance(data, str) else data).decode()


def _streams(main: str, data_b64: str, glyph: bool = False) -> str:
    return (f'<StreamList><Stream name="MAIN" type="id">{main}</Stream>'
            f'<Stream name="{main}" type="Base64" size="{len(data_b64)}">{data_b64}</Stream>'
            + ('<Stream name="GLPH" type="Hex" size="1">01</Stream>' if glyph else "")
            + f'<Stream name="FNAM" type="Hex" size="{len(_FNAM) // 2}">{_FNAM}</Stream></StreamList>')


def _entry(key: str, n: int, main: str, data_b64: str, glyph: bool = False) -> str:
    return f'<BinaryData><LibraryReference id="{n}" key="{key}"></LibraryReference>{_streams(main, data_b64, glyph)}</BinaryData>'


def _ref(key: str, n: int) -> str:
    return f'<BinaryData><LibraryReference id="{n}" key="{key}"></LibraryReference></BinaryData>'


def _image_xml(dest: Path) -> Path:
    """The styled test layout with a catalog, an inline icon, a catalog icon and three graphics."""
    xml = _layout_xml(dest, styled=True).read_text(encoding="utf-8")
    big = _b64(base64.b64decode(_PNG_1PX) + b"\0" * (IMAGE_MAX_BYTES + 1))
    catalog = ("<LibraryCatalog membercount=\"5\">"
               + _entry(KEYS["svg"], 2, "SVG ", _b64(_SVG_ICON), glyph=True) + _entry(KEYS["png"], 3, "PNGf", _PNG_1PX)
               + _entry(KEYS["big"], 4, "PNGf", big) + _entry(KEYS["pdf"], 5, "PDF ", _b64("%PDF-1.4"))
               + _entry(KEYS["logo"], 6, "SVG ", _b64(_SVG_LOGO)) + "</LibraryCatalog>")
    xml = xml.replace("<LayoutCatalog", catalog + "<LayoutCatalog", 1)
    # Button 2 ("Send"): an icon left of its label, stored inline (SaXML 2.2).
    send = xml.index('<LayoutObject id="2" ')
    cut = xml.index("</Label>", send) + len("</Label>")
    inline = f'<IconData type="4" size="12"><BinaryData>{_streams("SVG ", _b64(_SVG_ICON), glyph=True)}</BinaryData></IconData>'
    xml = xml[:cut] + inline + xml[cut:]
    # Popover button 11 ("More"): icon only, from the catalog (SaXML 2.3).
    more = xml.index('<LayoutObject id="11" ')
    cut = xml.index("</Label>", more) + len("</Label>")
    xml = xml[:cut] + f'<IconData type="1" size="14">{_ref(KEYS["svg"], 2)}</IconData>' + xml[cut:]
    # Graphics in the header: a picture, one over the size limit, a PDF and an SVG logo.
    graphics = "".join(
        _obj(oid, "Graphic", (2, left, 38, left + 36), f'<Graphic><Formatting><Options>3</Options></Formatting>{_ref(KEYS[k], n)}</Graphic>',
             name=f"logo_{k}")
        for oid, left, k, n in ((21, 130, "png", 3), (22, 170, "big", 4), (23, 210, "pdf", 5), (24, 250, "logo", 6)))
    header_end = xml.index("</ObjectList></Part>", xml.index('<Part type="Header"'))
    xml = xml[:header_end] + graphics + xml[header_end:]
    xml = xml.replace("button:normal .inner_border",
                      "button:normal .icon\n{\n\t-fm-icon-color: rgba(100%,100%,0%,1);\n}\nbutton:normal .inner_border", 1)
    dest.write_text(xml, encoding="utf-8")
    return dest


def _library(out: Path) -> dict[str, dict]:
    folder = out / VIEWER_DIR / "data" / "_" / "library"
    out_ = {}
    for js in sorted(folder.glob("*.js")) if folder.exists() else ():
        key, lib_key, data = _call_args(js.read_text(encoding="utf-8"), "layoutLibrary")
        assert key == "_" and js.stem == lib_key
        out_[lib_key] = data
    return out_


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not MAC_SAMPLE.exists(), reason="Mac sample not present")
def test_library_catalog_is_parsed():
    root = etree.parse(str(MAC_SAMPLE)).getroot()
    library = extract_library(root.find("Structure/AddAction"))
    assert set(library) == {"FB20EC575E6EDDBB999B96424B592A2A", "AD0839F1A7443424E36715EE0DF4B8FD",
                            "5E073C73805B1722F13C603388CE8966", "3016CAB4C485F18E6FE9DE1ACF8429EB"}
    for entry in library.values():
        assert set(entry) == {"kind", "data", "glyph"}  # never the file name (FNAM)
        assert entry["kind"] == "svg" and entry["glyph"] is True and entry["data"].startswith(b"<?xml")
    # The coverage report counts the catalog (and graphics) as read now.
    inventory = xml_inventory(root)
    assert "LibraryCatalog" not in inventory["skipped"].get("Catalogs (Structure/AddAction)", {})
    assert "Graphic" not in inventory["skipped"].get("Layout object", {})
    assert "LibraryCatalog" not in inventory["unrecognised"].get("Catalogs (Structure/AddAction)", {})


@pytest.mark.skipif(not MAC_SAMPLE.exists(), reason="Mac sample not present")
def test_mac_sample_icons_resolve_by_key():
    model = _run_pipeline(MAC_SAMPLE)
    data = build_layout_preview(model, "layout:EverythingBagel")
    icons = {o["id"]: o["ic"] for o in data["objects"] if "ic" in o}
    assert icons == {"21": ["FB20EC575E6EDDBB999B96424B592A2A", 4, 12], "22": ["AD0839F1A7443424E36715EE0DF4B8FD", 4, 12],
                     "23": ["5E073C73805B1722F13C603388CE8966", 4, 12], "32": ["3016CAB4C485F18E6FE9DE1ACF8429EB", 1, 54]}
    assert all(k in model._library for k, _, _ in icons.values())


def test_streams_and_inline_keys():
    streams = etree.fromstring(_streams("SVG ", _b64(_SVG_LOGO)))
    assert parse_streams(streams) == {"kind": "svg", "data": _SVG_LOGO.encode(), "glyph": False}
    hexed = etree.fromstring('<StreamList><Stream name="MAIN" type="id">PNGf</Stream>'
                             '<Stream name="PNGf" type="Hex">89504E47</Stream></StreamList>')
    assert parse_streams(hexed) == {"kind": "png", "data": b"\x89PNG", "glyph": False}
    assert parse_streams(etree.fromstring('<StreamList><Stream name="MAIN" type="id">PDF </Stream></StreamList>')) == \
        {"kind": "pdf", "data": None, "glyph": False}  # the export left the bytes out
    one = object_image(etree.fromstring(f"<BinaryData>{_streams('SVG ', _b64(_SVG_LOGO))}</BinaryData>"))
    two = object_image(etree.fromstring(f"<BinaryData>{_streams('SVG ', _b64(_SVG_LOGO), glyph=True)}</BinaryData>"))
    assert one[0] == two[0] and one[0].startswith("i")  # same picture, same key: written once
    assert object_image(etree.fromstring(_ref("not a/safe key", 1)))[0].startswith("h")  # hashed into a file name


def test_sanitize_svg():
    svg = sanitize_svg(_SVG_ICON.encode())
    assert svg.startswith("<svg") and 'class="fm_fill"' in svg and "<rect" in svg
    for gone in ("onload", "<script", "alert", "metadata", "jsmithy", "Generator", "example.com", "x:private", "<?xml"):
        assert gone not in svg, gone
    assert 'href="#a"' in svg  # links inside the SVG are kept
    glyph = sanitize_svg(_SVG_ICON.encode(), glyph=True)
    assert ".fm_fill,.fm_fill *{fill:#000}" in glyph
    assert sanitize_svg(b"<html><script>x</script></html>") is None
    assert sanitize_svg(b"<svg") is None
    assert sanitize_svg(b'<!DOCTYPE svg [<!ENTITY e SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&e;</svg>') \
        in (None, '<svg xmlns="http://www.w3.org/2000/svg"/>')
    # CSS that loads without a plain url(…), and animation that sets an outside href.
    ns = 'xmlns="http://www.w3.org/2000/svg"'
    for evil in (f'<svg {ns}><style>@IMPORT "http://evil.example/a.css";</style><rect/></svg>',
                 f'<svg {ns}><rect style="fill:image-set(\'http://evil.example/x.png\' 1x)"/></svg>',
                 f'<svg {ns}><rect style="fill:u\\72l(http://evil.example/x)"/></svg>',
                 f'<svg {ns}><style>rect{{fill:u\\72l(http://evil.example/x)}}</style><rect/></svg>',
                 f'<svg {ns}><use href="#r"><set attributeName="href" to="http://evil.example/s.svg#a"/></use></svg>',
                 f'<svg {ns}><rect><animate attributeName="href" values="http://evil.example/"/></rect></svg>'):
        clean = sanitize_svg(evil.encode())
        assert "evil" not in clean and ("<rect" in clean or "<use" in clean), clean
    # A link is unwrapped: its shapes stay.
    linked = sanitize_svg(f'<svg {ns}><a href="#q"><path class="fm_fill" d="M0 0h10v10z"/>t</a>u</svg>'.encode())
    assert linked == f'<svg {ns}><path class="fm_fill" d="M0 0h10v10z"/>tu</svg>'


def test_raw_xml_keeps_only_svg_icon_pictures():
    from fm_saxml.render.json.raw_xml import _drop_pictures

    layout = etree.fromstring(
        "<Layout>"
        f'<LayoutObject id="1"><Button><IconData type="4">{_streams("SVG ", _b64(_SVG_LOGO), glyph=True)}</IconData></Button></LayoutObject>'
        f'<LayoutObject id="2"><Button><IconData type="4">{_streams("PNGf", _PNG_1PX)}</IconData></Button></LayoutObject>'
        f'<LayoutObject id="3"><Graphic><BinaryData>{_streams("SVG ", _b64(_SVG_LOGO))}</BinaryData></Graphic></LayoutObject>'
        f'<LayoutObject id="4"><Graphic><BinaryData>{_streams("JPEG", _PNG_1PX)}</BinaryData></Graphic></LayoutObject>'
        "</Layout>")
    _drop_pictures({"layouts": [("layout:L", layout)]})

    def names(oid: str) -> list[str]:
        return [s.get("name") for s in layout.find(f"LayoutObject[@id='{oid}']").iter("Stream")]

    assert names("1") == ["MAIN", "SVG ", "GLPH", "FNAM"]  # an SVG button icon keeps its bytes
    assert names("2") == ["MAIN", "FNAM"] and names("3") == ["MAIN", "FNAM"] and names("4") == ["MAIN", "FNAM"]
    assert _PNG_1PX not in etree.tostring(layout, encoding="unicode")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def test_svg_icons_by_default(tmp_path):
    xml = _image_xml(tmp_path / "Images.xml")
    result = runner.invoke(app, ["build", str(xml), "-o", str(tmp_path / "docs"), "-f", "--html"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "docs"
    data = _layout_data(out)
    objs = {o["id"]: o for o in data["objects"]}
    inline_key = objs["2"]["ic"][0]
    assert objs["2"]["ic"] == [inline_key, 4, 12] and inline_key.startswith("i")
    assert objs["11"]["ic"] == [KEYS["svg"], 1, 14]
    assert [objs[i]["im"] for i in ("21", "22", "23", "24")] == [KEYS["png"], KEYS["big"], KEYS["pdf"], KEYS["logo"]]
    assert data["lib"] == {
        inline_key: {"k": "svg", "g": 1}, KEYS["svg"]: {"k": "svg", "g": 1},
        KEYS["png"]: {"k": "png", "x": "images"}, KEYS["big"]: {"k": "png", "x": "images"},
        KEYS["pdf"]: {"k": "pdf", "x": "type"}, KEYS["logo"]: {"k": "svg", "x": "images"},  # an SVG graphic is artwork
    }
    library = _library(out)
    assert set(library) == {inline_key, KEYS["svg"]}
    assert library[KEYS["svg"]]["k"] == "svg" and library[KEYS["svg"]]["g"] == 1
    assert "<script" not in library[KEYS["svg"]]["svg"] and "fm_fill" in library[KEYS["svg"]]["svg"]
    printed = " ".join(result.output.split())  # the console wraps long lines
    assert "Layout preview icons: 2 written (1 KB); skipped 3 pictures / SVG graphics (--layout-images includes them), 1 PDF" in printed
    _no_file_names(out)
    # The icon colour from the theme's ".icon" rule is in the button's style.
    assert data["styles"][objs["2"]["sy"]]["icon-color"] == "#ffff00"


def test_layout_images_adds_pictures_with_a_size_limit(tmp_path):
    out = _build(tmp_path, "--html", "--layout-images", xml=_image_xml(tmp_path / "Images.xml"))
    data = _layout_data(out)
    assert data["lib"][KEYS["png"]] == {"k": "png"} and data["lib"][KEYS["logo"]] == {"k": "svg"}
    assert data["lib"][KEYS["big"]] == {"k": "png", "x": "size"} and data["lib"][KEYS["pdf"]] == {"k": "pdf", "x": "type"}
    library = _library(out)
    assert library[KEYS["png"]] == {"k": "png", "m": "image/png", "d": _PNG_1PX}
    assert KEYS["big"] not in library and KEYS["pdf"] not in library
    assert all(js.stat().st_size <= IMAGE_MAX_BYTES for js in (out / VIEWER_DIR / "data" / "_" / "library").glob("*.js"))
    _no_file_names(out)


def test_no_layout_preview_writes_no_images(tmp_path):
    out = _build(tmp_path, "--html", "--no-layout-preview", xml=_image_xml(tmp_path / "Images.xml"))
    assert not (out / VIEWER_DIR / "data").exists()


def test_markdown_stays_plain(tmp_path):
    out = _build(tmp_path, "--html", "--layout-images", xml=_image_xml(tmp_path / "Images.xml"))
    for md in out.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        assert _PNG_1PX not in text and "<svg" not in text, md


def _no_file_names(out: Path) -> None:
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in (".js", ".json", ".md", ".html"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert _FNAM not in text and "jsmithy" not in text, path


# ---------------------------------------------------------------------------
# In the browser
# ---------------------------------------------------------------------------

def test_icons_and_pictures_render(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    out = _build(tmp_path, "--html", "--layout-images", xml=_image_xml(tmp_path / "Images.xml"))
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(_STUB + "try { localStorage.removeItem('fm-saxml-layout-preview-mode'); } catch (e) {}")
        page.goto((out / "index.html").as_uri() + _route(doc="layout:ContactDetail", file="_"))
        page.wait_for_selector(".fm-lp[data-images='done']", state="attached", timeout=30000)
        icon = ("id => { const o = document.querySelector(`.fm-lp-o[data-id='${id}']`); const i = o.querySelector('.fm-lp-ic');"
                " if (!i) return null; const s = getComputedStyle(i); const r = i.getBoundingClientRect();"
                " return {tag: i.tagName, glyph: i.classList.contains('glyph'), bg: s.backgroundColor,"
                " mask: s.maskImage || s.webkitMaskImage, w: Math.round(r.width), h: Math.round(r.height),"
                " natural: i.naturalWidth || 0, label: getComputedStyle(o.querySelector('.t')).visibility}; }")
        send = page.evaluate(icon, "2")
        # The inline glyph: a mask painted in the theme's icon colour (yellow), left of the label.
        assert send["tag"] == "I" and send["glyph"] and send["bg"] == "rgb(255, 255, 0)"
        assert send["mask"].startswith('url("data:image/svg+xml') and send["label"] == "visible"
        more = page.evaluate(icon, "11")
        assert more["glyph"] and more["label"] == "hidden"  # icon only
        png = page.evaluate(icon, "21")
        assert png["tag"] == "IMG" and png["natural"] == 1  # the picture decoded
        logo = page.evaluate(icon, "24")
        assert logo["tag"] == "IMG" and logo["natural"] > 0
        assert page.evaluate(icon, "22") is None and page.evaluate(icon, "23") is None  # too big, a PDF
        assert page.evaluate("document.querySelector(`.fm-lp-o[data-id='22']`).classList.contains('im-skip')")
        # The glyph really paints: yellow pixels on the red button (its shape has fill="none").
        shot = page.locator(".fm-lp-o[data-id='2'] .fm-lp-ic").screenshot()
        assert sum(1 for r, g, b in _png_pixels(shot) if r > 200 and g > 200 and b < 80) > 20
        # Wireframe: the glyph takes the kind's colour, pictures are faded.
        page.click("[data-mode='wireframe']")
        assert page.evaluate(icon, "2")["bg"] != "rgb(255, 255, 0)"
        assert page.evaluate("getComputedStyle(document.querySelector(`.fm-lp-o[data-id='21'] img`)).opacity") == "0.45"
        # Details panel and the WebMCP-facing description name the image.
        page.click(".fm-lp-o[data-id='22']", force=True)
        side = page.inner_text(".fm-lp-side")
        assert "PNG" in side and "over the size limit" in side
        described = page.evaluate("(async () => { const d = await FMDocs.preview.layout('_', 'layout:ContactDetail');"
                                  " const i = d.objects.findIndex(o => o.id === '11'); return FMDocs.preview.describe('_', d, i); })()")
        assert described["icon"] == {"placement": "icon only", "size": 14, "libraryKey": KEYS["svg"], "kind": "svg",
                                     "included": True, "glyph": True}
        assert not errors
        browser.close()


def _png_pixels(png: bytes) -> list[tuple[int, int, int]]:
    """RGB pixels of a Playwright screenshot (8-bit RGB/RGBA PNG), without an imaging library."""
    import struct
    import zlib

    pos, chunks = 8, []
    width = height = color = 0
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, _, color = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            chunks.append(body)
        pos += 12 + length
    bpp = 4 if color == 6 else 3
    raw = zlib.decompress(b"".join(chunks))
    stride = width * bpp
    rows, prev = [], bytearray(stride)
    for y in range(height):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p_ = a + b - c
                pa, pb, pc = abs(p_ - a), abs(p_ - b), abs(p_ - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return [tuple(r[x:x + 3]) for r in rows for x in range(0, stride, bpp)]
