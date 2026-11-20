"""Data for the HTML viewer's layout preview (``--html``; ``--no-layout-preview`` turns it off).

The viewer draws each layout as FileMaker shows it in Layout mode: its parts as bands and
every object at its real position, so people (and agents) can find things on it. See
``layout_preview.md`` in the repo for the plan and the findings this relies on.

One classic script per layout, loaded when the layout is shown (file:// pages can't fetch()):

``_viewer/data/<file>/layouts/index.js``
    ``FMDocs.layoutPreviewIndex(key, {layouts, fields, xfields?})``: each layout's docId, number,
    name, object count, page and problem count, and for each field the objects that show it, so
    a field page can link to them without loading every layout (``xfields``: fields of other
    files in a multi-file build, by that file's key)
``_viewer/data/<file>/layouts/<n>.js``
    ``FMDocs.layoutPreview(key, layoutDocId, {...})``: the layout's parts and objects

Coordinates are points from the layout's top left (P0 findings, 7.1): top-level objects are
already absolute; a nested object's bounds are relative to its container, so each ancestor's
top/left is added, up to a popover panel, whose own bounds are absolute. Objects are written
in document order, which is FileMaker's back-to-front paint order, so an object's index is
its z-order. The Markdown pages and the model keep the raw (relative) bounds.

Styles (P4): when the build wrote ``raw/`` (scrubbed theme and layout XML),
``analyze/layout_css.py`` resolves each object's and part's normal-state theme style to a few
plain CSS properties. Each layout file then has a ``styles`` table (deduplicated) that
objects and parts point into with ``sy``, and ``bg`` for the layout background. Without
``raw/`` (``--no-raw-xml``, a render from model.json) the preview is a wireframe only.

Images (P5): button icons and graphics come from the export's ``<LibraryCatalog>`` (or the
icon stored inline on the object, SaXML 2.2). Objects carry the library key (``ic``: ``[key,
placement, size]``, ``im``: key) and each layout file a ``lib`` table saying, per key, what
the image is and whether it was written. Each image used is written once per file:

``_viewer/data/<file>/library/<key>.js``
    ``FMDocs.layoutLibrary(key, libKey, {k, g, svg} | {k, m, d})``: an SVG as (sanitized)
    text, so the scrubbing guard can read it, or a picture as base64

SVG button icons are written by default. Pictures (PNG, JPEG, GIF) and SVG graphics are
written only with ``images`` (``--layout-images``): they can show logos or client artwork the
scrubber can't check. Images over ``image_max`` bytes, PDFs and other kinds are skipped and
counted. A render from model.json has no images (they are not in the contract).
"""

from __future__ import annotations

import base64
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from lxml import etree

from ...analyze.layout_css import (LayoutCss, StyleSource, compact_style, element_for, is_opaque, part_element,
                                   resolve_style)
from ...model.document_model import DocumentModel
from ...utils.file_writer import write_text
from ..markdown.link_resolver import LinkResolver
from .viewer import VIEWER_DIR, _js_literal
from .webmcp import DATA_DIR, _join

PREVIEW_DIR = "layouts"
LIBRARY_DIR = "library"
FORMAT_VERSION = 1
# Images bigger than this (bytes, as written) are skipped and counted (a DRCC logo is 1.4 MB).
IMAGE_MAX_BYTES = 256 * 1024
_MIMES = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif"}
# Why an image wasn't written (the build prints the counts): needs --layout-images, too big,
# a kind a browser can't show in an <img> (PDF, BMP, TIFF…), no bytes in the export, not a usable SVG.
SKIP_REASONS = ("images", "size", "type", "missing", "invalid")

# Text kept per object: enough to recognise and search it, not whole calculations.
_LABEL_MAX = 80
_TOOLTIP_MAX = 120
_CALC_MAX = 160
# Objects this thin are drawn but flagged (a line's thickness is its stroke, so lines aren't).
_TINY = 2.0
_LINES = {"Line"}
# Bits of a layout object's <Options> (P0 findings, 7.4): anchoring. Top + left is the default.
_ANCHORS = ((0x10000000, "t"), (0x20000000, "l"), (0x40000000, "r"), (0x80000000, "b"))

_WS_RE = re.compile(r"\s+")
_LITERAL_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*$', re.DOTALL)


_UNSET: Any = object()


def write_layout_previews(model: DocumentModel, output_dir: str | Path, *, file_key: str = "", prefix: str = "",
                          cross_file: Optional[dict[str, tuple[str, str]]] = None,
                          style_source: Optional[StyleSource] = _UNSET, images: bool = False,
                          image_max: int = IMAGE_MAX_BYTES,
                          cross_targets: Optional[dict[str, tuple[str, str]]] = None) -> dict[str, Any]:
    """Write one file's preview data under ``output_dir/_viewer/data/<file_key or '_'>/layouts/``.

    ``output_dir`` is the viewer's root (the batch root in a multi-file build) and ``prefix``
    the file's folder inside it (``"Invoices/"``, or ``""``). ``cross_targets`` maps a
    cross-file reference's provisional docId to ``(file key, docId there)``: fields of other
    files shown on this file's layouts go in the index's ``xfields`` (``{fileKey: {fieldDocId:
    [[n, ids]]}}``), so the field's own page and ``locate_layout_object`` find them. Returns the manifest entry for
    the file: ``{key, dir, layouts, styled, images}``. Styles come from the file's ``raw/``
    folder (``output_dir/<prefix>raw``) unless ``style_source`` is given (None: wireframe
    only). ``images`` also writes pictures and SVG graphics (not only SVG button icons);
    ``images`` in the result counts what was written and skipped (``write_library``).
    """
    key = file_key or "_"
    out_dir = Path(output_dir) / VIEWER_DIR / DATA_DIR / key / PREVIEW_DIR
    links = LinkResolver(model, cross_file)
    paths = _Paths(links, prefix, cross_file or {})
    # The file's own docs folder holds its raw/ (a batch writes one per file).
    source = StyleSource.load(Path(output_dir) / prefix) if style_source is _UNSET else style_source
    styled = 0
    library, image_stats = write_library(model, out_dir.parent / LIBRARY_DIR, key, images=images, image_max=image_max)

    index_rows: list[list[Any]] = []
    fields: dict[str, list[list[Any]]] = defaultdict(list)
    xfields: dict[str, dict[str, list[list[Any]]]] = defaultdict(lambda: defaultdict(list))
    targets = {d: ((t_key or "_"), t_id) for d, (t_key, t_id) in (cross_targets or {}).items()}
    for n, layout in enumerate(model.entities.layouts.values(), start=1):
        css = source.layout(layout.doc_id, layout.theme) if source is not None else None
        data = build_layout_preview(model, layout.doc_id, paths, css=css, library=library)
        styled += bool(data.get("styles"))
        _write(out_dir / f"{n}.js", f"FMDocs.layoutPreview({_js_literal(key)},{_js_literal(layout.doc_id)},"
                                    f"{_js_literal(data, compact=True)});\n")
        problems = sum(data["problems"].values())
        index_rows.append([layout.doc_id, n, layout.name, len(data["objects"]), data["path"], problems])
        by_field: dict[tuple[str, str], list[str]] = defaultdict(list)
        em = model.entities
        for doc_id in layout.layout_objects:
            obj = em.layout_objects.get(doc_id)
            if obj is None or not obj.field_doc_id:
                continue
            # A field in another file of the batch: listed under that file's key and its docId there.
            owner, field_doc_id = targets.get(obj.field_doc_id, (key, obj.field_doc_id))
            if owner == key and field_doc_id not in em.fields:
                continue
            by_field[(owner, field_doc_id)].append(_short_id(doc_id, data["objPrefix"]))
        for (owner, field_doc_id), ids in by_field.items():
            (fields if owner == key else xfields[owner])[field_doc_id].append([n, ids])

    index: dict[str, Any] = {"v": FORMAT_VERSION, "layouts": index_rows, "fields": dict(fields)}
    if xfields:
        index["xfields"] = {owner: dict(m) for owner, m in sorted(xfields.items())}
    _write(out_dir / "index.js", f"FMDocs.layoutPreviewIndex({_js_literal(key)},{_js_literal(index, compact=True)});\n")
    return {"key": key, "dir": prefix.rstrip("/"), "layouts": len(index_rows), "styled": styled,
            "images": image_stats}


def _write(path: Path, text: str) -> None:
    write_text(path, text)


def write_library(model: DocumentModel, out_dir: Path, file_key: str, *, images: bool = False,
                  image_max: int = IMAGE_MAX_BYTES) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Write each image a layout object uses, once, to ``out_dir/<libKey>.js``.

    Returns ``(lib, stats)``: ``lib`` is ``{libKey: {k: kind, g: 1 if an SVG glyph}}`` for
    written images and ``{k, x: reason}`` for skipped ones (``SKIP_REASONS``); ``stats`` is
    ``{written, bytes, skipped: {reason: n}}``, counted per image, not per use.
    """
    library: dict[str, dict[str, Any]] = getattr(model, "_library", None) or {}
    geometry: dict[str, dict[str, Any]] = getattr(model, "_layout_geometry", None) or {}
    as_icon: set[str] = set()
    used: set[str] = set()
    for g in geometry.values():
        if g.get("icon"):
            as_icon.add(g["icon"])
            used.add(g["icon"])
        if g.get("image"):
            used.add(g["image"])

    lib: dict[str, dict[str, Any]] = {}
    skipped: Counter = Counter()
    written = size = 0
    for lib_key in sorted(used):
        entry = library.get(lib_key)
        kind = entry["kind"] if entry else "other"
        info: dict[str, Any] = {"k": kind}
        payload: Optional[dict[str, Any]] = None
        reason: Optional[str] = None
        if entry is None or not entry.get("data"):
            reason = "missing"
        elif kind != "svg" and kind not in _MIMES:
            reason = "type"
        elif not images and not (kind == "svg" and lib_key in as_icon):
            reason = "images"  # pictures and SVG graphics (logos, artwork) only with --layout-images
        elif kind == "svg":
            svg = sanitize_svg(entry["data"], glyph=bool(entry.get("glyph")))
            if svg is None:
                reason = "invalid"
            else:
                payload = {"k": "svg", "svg": svg}
                if entry.get("glyph"):
                    payload["g"] = info["g"] = 1
        else:
            payload = {"k": kind, "m": _MIMES[kind], "d": base64.b64encode(entry["data"]).decode("ascii")}
        if payload is not None:
            text = (f"FMDocs.layoutLibrary({_js_literal(file_key)},{_js_literal(lib_key)},"
                    f"{_js_literal(payload, compact=True)});\n")
            if len(text.encode("utf-8")) > image_max:
                reason = "size"
            else:
                _write(out_dir / f"{lib_key}.js", text)
                written += 1
                size += len(text.encode("utf-8"))
        if reason is not None:
            info["x"] = reason
            skipped[reason] += 1
        lib[lib_key] = info
    return lib, {"written": written, "bytes": size, "skipped": dict(skipped)}


_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
# Elements that run code, load things, or only carry text about the file (an editor's notes).
# Animation elements go too: <set attributeName="href" to="http://…"> would bring a link back.
_SVG_DROP = {"script", "foreignObject", "metadata", "title", "desc", "iframe", "object", "embed", "audio",
             "video", "handler", "listener", "set", "animate", "animateTransform", "animateMotion",
             "animateColor", "discard"}
# Links are unwrapped: their shapes stay, the link goes.
_SVG_UNWRAP = {"a"}
_EXTERNAL_URL_RE = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.I)
# CSS that can load something without a plain url(…): @import, image-set(…), or a backslash
# escape that could spell either (u\72l(…)).
_CSS_LOAD_RE = re.compile(r"@import|image-set\(|\\", re.I)


def sanitize_svg(data: bytes, glyph: bool = False) -> Optional[str]:
    """An SVG's markup without anything that could run or load: no ``<script>``,
    ``<foreignObject>``, animation elements, ``on…`` attributes, hrefs other than ``#id``,
    ``url(…)`` other than ``url(#id)``, ``@import``, ``image-set(…)`` or backslash escapes in
    CSS, elements and attributes from other namespaces (an editor's own), comments, processing
    instructions or DOCTYPE; ``<a>`` links are unwrapped (their shapes kept). None when it
    isn't a well-formed ``<svg>``.

    The viewer also shows it only as an image (``<img>`` or a CSS mask), where scripts never run.
    ``glyph``: an icon FileMaker paints in the style's icon colour. It fills (and strokes) the
    ``fm_fill`` / ``fm_stroke`` classes whatever their own ``fill`` says, so a rule does that
    here too (black; the viewer uses the icon as a mask and paints the colour itself).
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=True,
                             remove_pis=True, huge_tree=False)
    try:
        root = etree.fromstring(data, parser)
    except (etree.XMLSyntaxError, ValueError):
        return None
    if not isinstance(root.tag, str) or etree.QName(root).localname != "svg":
        return None
    drop = []
    unwrap = []
    for el in root.iter():
        if not isinstance(el.tag, str):  # an entity reference left unresolved
            drop.append(el)
            continue
        q = etree.QName(el)
        if q.namespace not in (None, _SVG_NS) or q.localname in _SVG_DROP:
            drop.append(el)
            continue
        if q.localname in _SVG_UNWRAP:
            unwrap.append(el)
        css = "".join(el.itertext()) if q.localname == "style" else ""
        if css and (_CSS_LOAD_RE.search(css) or _EXTERNAL_URL_RE.search(css)):
            drop.append(el)
            continue
        for name in list(el.attrib):
            a = etree.QName(name)
            local = a.localname.lower()
            value = el.attrib[name]
            if (local.startswith("on") or a.namespace not in (None, _XLINK_NS, _XML_NS)
                    or (local == "href" and not value.strip().startswith("#"))
                    or _EXTERNAL_URL_RE.search(value) or _CSS_LOAD_RE.search(value)):
                del el.attrib[name]
    for el in drop:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    for el in reversed(unwrap):  # innermost first; a dropped subtree's links have no parent chain to root
        parent = el.getparent()
        if parent is None or not any(x is root for x in el.iterancestors()):
            continue
        _unwrap(el)
    if glyph:
        style = etree.Element(f"{{{_SVG_NS}}}style" if etree.QName(root).namespace else "style")
        style.text = ".fm_fill,.fm_fill *{fill:#000}.fm_stroke,.fm_stroke *{stroke:#000}"
        root.insert(0, style)
    return etree.tostring(root, encoding="unicode")


def _unwrap(el: etree._Element) -> None:
    """Replace ``el`` by its children (and text) in its parent."""
    parent = el.getparent()
    at = parent.index(el)
    text = (el.text or "") + (el.tail or "")
    children = list(el)
    for k, child in enumerate(children):
        parent.insert(at + k, child)
    if children:
        last = children[-1]
        last.tail = (last.tail or "") + (el.tail or "")
        text = el.text or ""
    if text:
        prev = parent[at - 1] if at > 0 else None
        if prev is not None:
            prev.tail = (prev.tail or "") + text
        else:
            parent.text = (parent.text or "") + text
    parent.remove(el)


class _Paths:
    """Pages relative to the viewer root, as the WebMCP records give them."""

    def __init__(self, links: LinkResolver, prefix: str, cross_file: dict[str, tuple[str, str]]) -> None:
        self.links = links
        self.prefix = prefix
        self.cross_file = cross_file

    def page(self, doc_id: Optional[str]) -> Optional[str]:
        if not doc_id:
            return None
        own = self.links.path_for(doc_id)
        if own is not None:
            return self.prefix + own
        if doc_id in self.cross_file:
            return _join(self.prefix, self.cross_file[doc_id][0])
        return None

    def title(self, doc_id: Optional[str]) -> Optional[str]:
        if not doc_id:
            return None
        if doc_id in self.cross_file:
            return self.cross_file[doc_id][1]
        return self.links.title_for(doc_id)


def build_layout_preview(model: DocumentModel, layout_doc_id: str, paths: Optional[_Paths] = None,
                         css: Optional[LayoutCss] = None,
                         library: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    """The preview data of one layout (what ``<n>.js`` holds), as a plain dict.

    Keys are short because a big layout has about a thousand objects. Per object:
    ``id`` (docId after ``objPrefix``), ``t`` type, ``b`` absolute ``[top, left, bottom, right]``,
    ``p`` part, ``pa`` parent's index, ``n`` name, ``l`` label, ``f``/``fp`` field and its page,
    ``s``/``sp`` script and its page, ``st`` single-step button action, ``tt`` tooltip,
    ``hc`` hide condition, ``pg`` page (under ``objDir``), ``pr`` portal rows, ``tab`` tab
    control / tab, ``pop`` popover side, ``pt`` popover title, ``a`` anchors when not top-left,
    ``x`` problems, ``cv`` the index of the object that covers it, ``sy`` its style, ``ic``
    its icon ``[libKey, placement, size]`` (placement: 1 icon only, 2 above the label, 3 below,
    4 left, 5 right), ``im`` its graphic's libKey. The index in ``objects`` is the z-order
    (back to front).

    With ``css`` (the layout's theme and local CSS), ``styles`` lists each distinct resolved
    style (plain CSS, see ``analyze/layout_css.py``) and parts carry ``sy`` too; ``bg`` is the
    layout background's style. An object fully under an opaque object in front of it, and
    visible whenever it is, is flagged ``cov`` (``problems.covered``).

    With ``library`` (``write_library``'s table), ``lib`` gives the entries this layout uses.
    """
    em = model.entities
    layout = em.layouts[layout_doc_id]
    paths = paths or _Paths(LinkResolver(model), "", {})
    geometry = getattr(model, "_layout_geometry", None) or {}

    objs = [em.layout_objects[d] for d in layout.layout_objects if d in em.layout_objects]
    index_of = {o.doc_id: i for i, o in enumerate(objs)}
    obj_prefix = _common_prefix(layout.layout_objects)
    layout_page = paths.page(layout_doc_id)
    first_page = paths.page(objs[0].doc_id) if objs else None
    obj_dir = first_page.rsplit("/", 1)[0] + "/" if first_page and "/" in first_page else ""

    parts = _parts(layout)
    width = float(layout.width) if layout.width else None
    height = max((p["top"] + p["height"] for p in parts), default=0.0)

    absolute: dict[int, Optional[list[float]]] = {}

    def rect(i: int, seen: frozenset = frozenset()) -> Optional[list[float]]:
        if i in absolute:
            return absolute[i]
        o = objs[i]
        b = o.bounds
        if b is None or None in (b.top, b.left, b.bottom, b.right):
            absolute[i] = None
            return None
        own = [b.top, b.left, b.bottom, b.right]
        parent = index_of.get(o.parent_object_doc_id or "")
        if o.object_type == "PopoverPanel" or parent is None or parent in seen:
            absolute[i] = own
            return own
        base = rect(parent, seen | {i})
        if base is None:
            absolute[i] = own
            return own
        absolute[i] = [own[0] + base[0], own[1] + base[1], own[2] + base[0], own[3] + base[1]]
        return absolute[i]

    in_popover = _in_popover(objs, index_of)
    records: list[dict[str, Any]] = []
    for i, o in enumerate(objs):
        records.append(_object_record(model, o, i, rect(i), index_of, obj_prefix, obj_dir, paths, geometry))

    counts = _flag_problems(objs, records, width, height, in_popover)
    styles: list[dict[str, str]] = []
    bg: Optional[int] = None
    if css is not None:
        styles, bg = _apply_styles(objs, records, parts, css, index_of)
        counts["covered"] = _flag_covered(objs, records, styles, index_of)
    data: dict[str, Any] = {
        "v": FORMAT_VERSION,
        "docId": layout_doc_id,
        "name": layout.name,
        "path": layout_page,
        "width": _num(width) if width is not None else None,
        "height": _num(height),
        "parts": parts,
        "objPrefix": obj_prefix,
        "objDir": obj_dir,
        "geometry": any(d in geometry for d in layout.layout_objects),
        "problems": counts,
        "objects": records,
    }
    if styles:
        data["styles"] = styles
        if bg is not None:
            data["bg"] = bg
    if library:
        keys = {k for r in records for k in ((r["ic"][0],) if "ic" in r else ()) + ((r["im"],) if "im" in r else ())}
        lib = {k: library[k] for k in sorted(keys) if k in library}
        if lib:
            data["lib"] = lib
    return data


def _apply_styles(objs, records: list[dict[str, Any]], parts: list[dict[str, Any]], css: LayoutCss,
                  index_of: dict[str, int]) -> tuple[list[dict[str, str]], Optional[int]]:
    """Resolve every object's and part's style into a deduplicated table; set ``sy`` on each."""
    table: list[dict[str, str]] = []
    seen: dict[tuple, int] = {}

    def add(style: dict[str, str]) -> Optional[int]:
        if not style:
            return None
        key = tuple(sorted(compact_style(style).items()))
        if key not in seen:
            seen[key] = len(table)
            table.append(dict(key))
        return seen[key]

    for p, (name, local) in zip(parts, css.parts):
        sy = add(resolve_style(css.theme, part_element(p["type"]), name, local))
        if sy is not None:
            p["sy"] = sy
    for o, r in zip(objs, records):
        parent = index_of.get(o.parent_object_doc_id or "")
        element = element_for(o.object_type, objs[parent].object_type if parent is not None else None)
        name, local = css.object_local(o.object_id)
        if element is None and not local:
            continue
        sy = add(resolve_style(css.theme, element, name, local, part=part_element(o.part)))
        if sy is not None:
            r["sy"] = sy
    bg = add(css.background())
    return table, bg


# Types that can't hide anything behind them, or whose "covering" is their job.
_NOT_COVERED = {"Panel", "PopoverPanel", "Tab Control", "Slide Control"}


def _flag_covered(objs, records: list[dict[str, Any]], styles: list[dict[str, str]], index_of: dict[str, int]) -> int:
    """Flag ``cov`` on objects that an opaque object in front of them fully covers.

    The front object must be visible whenever the one behind is: no hide condition, and no
    tab / slide panel or popover of its own that the one behind isn't also in. An object's
    own contents don't count (button bar segments fill their bar; a portal's row fills it).
    Only objects with a resolved style can cover, so this needs the theme CSS.
    """
    n = len(objs)
    parents = [index_of.get(o.parent_object_doc_id or "") for o in objs]

    def chain(i: int) -> list[int]:
        out, j, seen = [], parents[i], {i}
        while j is not None and j not in seen:
            out.append(j)
            seen.add(j)
            j = parents[j]
        return out

    ancestors = [chain(i) for i in range(n)]
    hides = [any(c.role == "hideCondition" for c in o.calculations) for o in objs]

    def conditions(i: int) -> set[int]:
        """The objects whose state decides whether ``i`` is shown."""
        return {a for a in [i, *ancestors[i]] if hides[a] or objs[a].object_type in ("Panel", "PopoverPanel")}

    fronts = [j for j in range(n) if "b" in records[j] and "sy" in records[j]
              and objs[j].object_type not in _NOT_COVERED and is_opaque(styles[records[j]["sy"]])]
    count = 0
    for i in range(n):
        b = records[i].get("b")
        if b is None or objs[i].object_type in _NOT_COVERED:
            continue
        mine = set(ancestors[i]) | {i}
        for j in fronts:
            if j <= i or i in ancestors[j]:
                continue
            f = records[j]["b"]
            if f[0] <= b[0] and f[1] <= b[1] and f[2] >= b[2] and f[3] >= b[3] and conditions(j) <= mine:
                records[i].setdefault("x", []).append("cov")
                records[i]["cv"] = j
                count += 1
                break
    return count


def _parts(layout) -> list[dict[str, Any]]:
    """Each part's top and height: ``<Definition absolute>`` when the export has it, else stacked."""
    out = []
    top = 0.0
    for p in layout.parts:
        h = float(p.height or 0)
        t = float(p.absolute) if p.absolute is not None else top
        part: dict[str, Any] = {"type": p.type, "top": _num(t), "height": _num(h)}
        if p.name and p.name != p.type:
            part["name"] = p.name
        out.append(part)
        top = t + h
    return out


def _object_record(model: DocumentModel, o, i: int, rect: Optional[list[float]], index_of: dict[str, int],
                   obj_prefix: str, obj_dir: str, paths: _Paths, geometry: dict[str, dict[str, int]]) -> dict[str, Any]:
    em = model.entities
    r: dict[str, Any] = {"id": _short_id(o.doc_id, obj_prefix), "t": o.object_type or "Object"}
    if rect is not None:
        r["b"] = [_num(v) for v in rect]
    if o.part:
        r["p"] = o.part
    parent = index_of.get(o.parent_object_doc_id or "")
    if parent is not None:
        r["pa"] = parent
    if o.name:
        r["n"] = _clip(o.name, _LABEL_MAX)
    roles: dict[str, str] = {}
    for c in o.calculations:
        roles.setdefault(c.role, c.text)
    label = o.raw_text or o.label_text or _literal(roles.get("label"))
    if label:
        r["l"] = _clip(label, _LABEL_MAX)
    field = _field_label(model, o, paths)
    if field:
        r["f"] = field
        fp = paths.page(o.field_doc_id)
        if fp:
            r["fp"] = fp
    script = o.button_script_doc_id
    if script:
        r["s"] = paths.title(script) or script.split(":", 1)[-1]
        sp = paths.page(script)
        if sp:
            r["sp"] = sp
    if o.button_step:
        r["st"] = _clip(o.button_step, _CALC_MAX)
    if roles.get("tooltip"):
        r["tt"] = _clip(_literal(roles["tooltip"]) or roles["tooltip"], _TOOLTIP_MAX)
    if "hideCondition" in roles:
        r["hc"] = _clip(roles["hideCondition"], _CALC_MAX) or "(empty)"
    page = paths.page(o.doc_id)
    if page:
        r["pg"] = page[len(obj_dir):] if obj_dir and page.startswith(obj_dir) else page
    if o.portal is not None:
        r["pr"] = {"rows": o.portal.rows or 1, "init": o.portal.initial_row or 1}
    g = geometry.get(o.doc_id, {})
    if o.object_type == "Tab Control":
        r["tab"] = {k: g[src] for k, src in (("def", "tab_default"), ("h", "tab_height")) if src in g}
    elif o.object_type == "Panel" and ("tab_width" in g or "tabLabel" in roles):
        tab: dict[str, Any] = {k: g[src] for k, src in (("w", "tab_width"), ("x", "tab_left")) if src in g}
        if "tabLabel" in roles:
            tab["l"] = _clip(_literal(roles["tabLabel"]) or roles["tabLabel"], _LABEL_MAX)
        r["tab"] = tab
    if o.object_type == "PopoverPanel":
        if "popover_position" in g:
            r["pop"] = g["popover_position"]
        if roles.get("popoverTitle"):
            r["pt"] = _clip(_literal(roles["popoverTitle"]) or roles["popoverTitle"], _LABEL_MAX)
    if o.options is not None:
        anchors = "".join(c for bit, c in _ANCHORS if o.options & bit)
        if anchors != "tl":
            r["a"] = anchors or "-"
    if g.get("icon"):
        r["ic"] = [g["icon"], g.get("icon_pos") or 1, g.get("icon_size") or 16]
    if g.get("image"):
        r["im"] = g["image"]
    return r


def _field_label(model: DocumentModel, o, paths: _Paths) -> Optional[str]:
    """``TO::field`` as FileMaker shows it on the layout (the table occurrence, not the base table)."""
    em = model.entities
    if not o.field_doc_id:
        return None
    field = em.fields.get(o.field_doc_id)
    to = em.table_occurrences.get(o.table_occurrence_doc_id or "")
    if field is not None:
        return f"{to.name}::{field.name}" if to is not None else field.qualified_name
    if o.external_target is not None and o.external_target.name:
        table = o.external_target.table_occurrence or (to.name if to is not None else "")
        return f"{table}::{o.external_target.name}" if table else o.external_target.name
    title = paths.title(o.field_doc_id)
    return title or o.field_doc_id.split(":", 1)[-1]


def _in_popover(objs, index_of: dict[str, int]) -> set[int]:
    """Indexes of popover panels and everything inside them."""
    out: set[int] = set()
    for i, o in enumerate(objs):
        j: Optional[int] = i
        seen: set[int] = set()
        while j is not None and j not in seen:
            seen.add(j)
            if objs[j].object_type == "PopoverPanel":
                out.add(i)
                break
            j = index_of.get(objs[j].parent_object_doc_id or "")
    return out


def _flag_problems(objs, records: list[dict[str, Any]], width: Optional[float], height: float,
                   in_popover: set[int]) -> dict[str, int]:
    """Mark ``x`` on objects outside the layout, too small to see, or exactly duplicated
    (same type, field, bounds, container, label and name, and the same script, button action,
    calculations and triggers).

    Popover panels (and their contents) aren't checked against the layout's edges: they float
    over it, and about a third are placed away from their button on purpose (P0, 7.1).
    """
    counts = {"outside": 0, "tiny": 0, "duplicate": 0}
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, (o, r) in enumerate(zip(objs, records)):
        b = r.get("b")
        if b is None:
            continue
        top, left, bottom, right = b
        problems = []
        if i not in in_popover and (left < 0 or top < 0 or (width is not None and right > width)
                                    or (height and bottom > height)):
            problems.append("out")
        if o.object_type not in _LINES and (bottom - top <= _TINY or right - left <= _TINY):
            problems.append("tiny")
        if problems:
            r["x"] = problems
        if o.object_type == "Panel":  # a control's panels all share its bounds
            continue
        # Same container too: one field on two tab panels at the same spot is normal. Objects that
        # differ in what they do or when they hide (stacked buttons that take turns) aren't duplicates.
        groups[(r["t"], o.field_doc_id or "", tuple(b), r.get("pa"), r.get("l", ""), o.name,
                o.button_script_doc_id or "", o.button_step or "",
                tuple(sorted((c.role, c.text) for c in o.calculations)),
                tuple(sorted((t.event, t.script_doc_id) for t in o.script_triggers)))].append(i)
    for members in groups.values():
        if len(members) > 1:
            for i in members:
                records[i].setdefault("x", []).append("dup")
    for r in records:
        for p in r.get("x", ()):
            counts[{"out": "outside", "tiny": "tiny", "dup": "duplicate"}[p]] += 1
    return counts


def _common_prefix(doc_ids: list[str]) -> str:
    """``layoutObject:<layout>::``: what every object docId of a layout starts with."""
    if not doc_ids:
        return ""
    first = doc_ids[0]
    cut = first.rfind("::")
    prefix = first[:cut + 2] if cut >= 0 else ""
    return prefix if all(d.startswith(prefix) for d in doc_ids) else ""


def _short_id(doc_id: str, prefix: str) -> str:
    return doc_id[len(prefix):] if prefix and doc_id.startswith(prefix) else doc_id


def _literal(calc: Optional[str]) -> Optional[str]:
    """The text of a calculation that is just a quoted string (a tab label, a fixed tooltip)."""
    if not calc:
        return None
    m = _LITERAL_RE.match(calc)
    return m.group(1).replace('\\"', '"').replace("\\\\", "\\") if m else None


def _clip(text: Optional[str], limit: int) -> str:
    text = _WS_RE.sub(" ", text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _num(v: float) -> float | int:
    """Points as written: whole numbers without ``.0``."""
    v = round(float(v), 2)
    return int(v) if v.is_integer() else v
