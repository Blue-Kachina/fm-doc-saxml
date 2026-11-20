"""FileMaker theme and object CSS, resolved to plain CSS for the layout preview (P4).

FileMaker keeps a layout's look in two places, both CDATA in the export:

- the theme's ``<CSS>`` (``raw/themes.json``): one rule set per element and state, e.g.
  ``edit_box:normal .self``, ``button.FM-1A2B…:normal .inner_border`` (a named custom style),
  ``header text_box:normal .self`` (text in a header);
- each object's (and part's) ``<LocalCSS name displayName>`` (``raw/layouts.json``): its named
  style as ``name`` and its own changes as ``self:normal .self`` rules.

The dialect: colours are ``rgba(52.549%,80.39%,30.2%,1)``; fonts are
``-fm-font-family(Display Name,PostScriptName;generic)``; ``-fm-text-vertical-align`` is
``top|center|bottom``; lengths are points; ``.self`` is the object's box, ``.inner_border``
holds radii and padding on many elements, ``.text`` the text inset.

Only the ``:normal`` state is resolved (no hover, focus, placeholder), in this order: the
theme's element style, the element's style in the object's part, the named custom style,
then the object's local CSS. Only a short whitelist of properties is kept (colours,
borders, radii, fonts, alignment, padding), converted to plain CSS with points as px
(the preview draws one pt as one px and zooms with a transform). Every value is
re-written from parsed numbers or checked against a fixed set of words, so nothing from
the export reaches the page as raw CSS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Object types and parts → the theme's element names
# ---------------------------------------------------------------------------

ELEMENTS: dict[str, str] = {
    "Text": "text_box",
    "Edit Box": "edit_box",
    "Concealed Edit Box": "edit_box",
    "Drop-down List": "drop_down",
    "Pop-up Menu": "pop_up",
    "Checkbox Set": "checkbox_set",
    "Radio Button Set": "radio_set",
    "Drop-down Calendar": "calendar",
    "Container": "container",
    "Button": "button",
    "Popover Button": "button",
    "Button Bar": "button_bar",
    "Portal": "portal",
    "Tab Control": "tab_control",
    "Slide Control": "dot_control",
    "PopoverPanel": "popover",
    "Web Viewer": "web_viewer",
    "Rectangle": "rectangle",
    "Rounded Rectangle": "rounded",
    "Oval": "oval",
    "Line": "line",
    "Graphic": "graphics",
    "Chart": "chart",
}
# A named style can live under a related element (a rectangle's custom styles are ``shape.…``).
_ALIASES: dict[str, tuple[str, ...]] = {
    "rectangle": ("shape",), "rounded": ("shape", "rectangle"), "oval": ("shape",),
    "button_bar_segment": ("button",), "button": ("button_bar_segment",),
}
PART_ELEMENTS: dict[str, str] = {
    "Top Navigation": "top_nav_part",
    "Bottom Navigation": "bottom_nav_part",
    "Title Header": "title_header",
    "Title Footer": "title_footer",
    "Header": "header",
    "Footer": "footer",
    "Body": "body",
    "Leading Grand Summary": "leading_grand_summary",
    "Trailing Grand Summary": "trailing_grand_summary",
    "Leading Sub-summary": "leading_sub_summary",
    "Trailing Sub-summary": "trailing_sub_summary",
}


def element_for(object_type: Optional[str], parent_type: Optional[str] = None) -> Optional[str]:
    """The theme element an object of this type is styled as (None: drawn without a style).

    A button inside a button bar is a ``button_bar_segment``; a tab control's panel is a
    ``tab_panel``; groups, grouped buttons and slide panels have no style of their own.
    """
    if object_type in ("Button", "Popover Button") and parent_type == "Button Bar":
        return "button_bar_segment"
    if object_type == "Panel":
        return "tab_panel" if parent_type == "Tab Control" else None
    return ELEMENTS.get(object_type or "")


def part_element(part_type: Optional[str]) -> Optional[str]:
    if not part_type:
        return None
    return PART_ELEMENTS.get(part_type) or re.sub(r"[^a-z0-9]+", "_", part_type.lower()).strip("_") or None


# ---------------------------------------------------------------------------
# Values: the dialect → plain CSS
# ---------------------------------------------------------------------------

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_RGBA_RE = re.compile(rf"^rgba?\(\s*({_NUM})(%?)\s*,\s*({_NUM})(%?)\s*,\s*({_NUM})(%?)\s*(?:,\s*({_NUM})(%?)\s*)?\)$", re.I)
_HEX_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
_LENGTH_RE = re.compile(rf"^({_NUM})(pt|px|em|%)?$", re.I)
_FONT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,62}$")
_GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
_BORDER_STYLES = {"none", "hidden", "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset"}
_FONT_WEIGHTS = {"normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700", "800", "900"}
_FONT_STYLES = {"normal", "italic", "oblique"}
_TEXT_ALIGN = {"left", "right", "center", "justify", "start", "end"}
_VALIGN = {"top": "top", "center": "middle", "middle": "middle", "bottom": "bottom"}


def _fmt(v: float) -> str:
    v = round(v, 3)
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def parse_color(value: str) -> Optional[str]:
    """``rgba(100%,50%,0%,1)`` → ``#ff8000``; with alpha < 1 → ``rgba(255,128,0,0.5)``.

    Also takes ``rgb()`` / ``rgba()`` with 0–255 numbers, ``#hex`` and ``transparent``.
    """
    v = (value or "").strip()
    if v.lower() == "transparent":
        return "rgba(0,0,0,0)"
    if _HEX_RE.match(v):
        return v.lower()
    m = _RGBA_RE.match(v)
    if not m:
        return None
    rgb = []
    for num, pct in ((m.group(1), m.group(2)), (m.group(3), m.group(4)), (m.group(5), m.group(6))):
        x = float(num) * 2.55 if pct else float(num)
        rgb.append(max(0, min(255, round(x))))
    alpha = 1.0
    if m.group(7) is not None:
        alpha = float(m.group(7)) / 100 if m.group(8) else float(m.group(7))
        alpha = max(0.0, min(1.0, alpha))
    if alpha >= 1:
        return "#" + "".join(f"{c:02x}" for c in rgb)
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{_fmt(alpha)})"


def parse_length(value: str) -> Optional[str]:
    """``5pt`` → ``5px`` (one point is one px in the preview); em, % and px are kept; ``0`` → ``0``."""
    m = _LENGTH_RE.match((value or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if n == 0:
        return "0"
    if unit in ("pt", "px", ""):
        if unit == "" or abs(n) > 10000:
            return None
        return f"{_fmt(n)}px"
    return f"{_fmt(n)}{unit}"


def parse_radius(value: str) -> Optional[str]:
    """``5pt 5pt`` (horizontal, vertical) → ``5px``; ``4pt 8pt`` → ``4px 8px``."""
    parts = (value or "").split()
    if not 1 <= len(parts) <= 2:
        return None
    out = [parse_length(p) for p in parts]
    if None in out:
        return None
    return out[0] if len(out) == 1 or out[0] == out[1] else f"{out[0]} {out[1]}"


def parse_font_family(value: str) -> Optional[str]:
    """``-fm-font-family(Helvetica Neue,HelveticaNeue-Bold;sans-serif)`` → ``"Helvetica Neue", sans-serif``.

    The first name is the family FileMaker shows; PostScript names (``ArialMT``) are left out
    unless nothing else is usable. Names with odd characters are dropped. ``sans-serif`` is
    added when the value names no generic family.
    """
    v = (value or "").strip()
    m = re.match(r"^-fm-font-family\((.*)\)$", v, re.S)
    if m:
        names = re.split(r"[,;]", m.group(1))
    else:
        names = v.split(",")
    names = [n.strip().strip("'\"").strip() for n in names]
    families: list[str] = []
    generics: list[str] = []
    for i, n in enumerate(names):
        if n.lower() in _GENERIC_FONTS:
            if n.lower() not in generics:
                generics.append(n.lower())
        elif _FONT_NAME_RE.match(n) and (i == 0 or not m) and n not in families:
            families.append(n)
    if not families and m:  # only a PostScript name was usable
        families = [n for n in names[1:2] if _FONT_NAME_RE.match(n) and n.lower() not in _GENERIC_FONTS]
    if not families and not generics:
        return None
    # A Mac font missing on the viewer's machine shouldn't fall back to the browser's serif.
    return ", ".join([f'"{f}"' for f in families] + (generics or ["sans-serif"]))


def _word(allowed: Iterable[str]):
    allowed = set(allowed)

    def parse(value: str) -> Optional[str]:
        v = (value or "").strip().lower()
        return v if v in allowed else None
    return parse


def parse_vertical_align(value: str) -> Optional[str]:
    """``-fm-text-vertical-align: center`` → ``middle`` (written as ``vertical-align``)."""
    return _VALIGN.get((value or "").strip().lower())


_SIDES = ("top", "right", "bottom", "left")
_CORNERS = ("top-left", "top-right", "bottom-right", "bottom-left")
# Kept property → (written name, parser). Everything else is dropped.
WHITELIST: dict[str, tuple[str, Any]] = {
    "background-color": ("background-color", parse_color),
    "color": ("color", parse_color),
    "font-family": ("font-family", parse_font_family),
    "font-size": ("font-size", parse_length),
    "font-weight": ("font-weight", _word(_FONT_WEIGHTS)),
    "font-style": ("font-style", _word(_FONT_STYLES)),
    "text-align": ("text-align", _word(_TEXT_ALIGN)),
    "-fm-text-vertical-align": ("vertical-align", parse_vertical_align),
    **{f"border-{s}-color": (f"border-{s}-color", parse_color) for s in _SIDES},
    **{f"border-{s}-width": (f"border-{s}-width", parse_length) for s in _SIDES},
    **{f"border-{s}-style": (f"border-{s}-style", _word(_BORDER_STYLES)) for s in _SIDES},
    **{f"border-{c}-radius": (f"border-{c}-radius", parse_radius) for c in _CORNERS},
    **{f"padding-{s}": (f"padding-{s}", parse_length) for s in _SIDES},
    # A button's icon colour (P5; ".icon" sub-element). Not a CSS property: the viewer paints icons with it.
    "-fm-icon-color": ("icon-color", parse_color),
}
# What each sub-element adds: the box takes everything; the inner border its radii and
# padding; the text its padding; the icon its colour.
_RADII = {f"border-{c}-radius" for c in _CORNERS}
_PADDING = {f"padding-{s}" for s in _SIDES}
_SUBS: tuple[tuple[str, Optional[set[str]]], ...] = (("self", None), ("inner_border", _RADII | _PADDING), ("text", _PADDING),
                                                     ("icon", {"-fm-icon-color"}))


def clean_declarations(decls: dict[str, str], only: Optional[set[str]] = None) -> dict[str, str]:
    """The whitelisted declarations of a rule, as plain CSS (unusable values are dropped)."""
    out: dict[str, str] = {}
    for prop, value in decls.items():
        if prop not in WHITELIST or (only is not None and prop not in only):
            continue
        name, parse = WHITELIST[prop]
        parsed = parse(value)
        if parsed is not None:
            out[name] = parsed
    return out


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CssRule:
    """One selector of a rule: ``[context ]element[.cls][:state][ .sub]`` and its declarations."""

    element: str
    cls: Optional[str]
    state: str
    sub: str
    context: Optional[str]
    decls: dict[str, str] = field(hash=False, compare=False)


_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_SELECTOR_RE = re.compile(
    r"^(?:(?P<ctx>[a-z][a-z0-9_]*)\s+)?(?P<el>[a-z][a-z0-9_]*)(?:\.(?P<cls>[A-Za-z0-9_\-]+))?"
    r"(?::(?P<state>[a-z_]+))?(?:\s+\.(?P<sub>[a-z_]+))?$")


def parse_declarations(body: str) -> dict[str, str]:
    """``a: b; c: d`` → ``{a: b, c: d}`` (later wins; ``;`` inside parentheses is kept)."""
    out: dict[str, str] = {}
    depth = 0
    start = 0
    chunks = []
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            chunks.append(body[start:i])
            start = i + 1
    chunks.append(body[start:])
    for chunk in chunks:
        if ":" not in chunk:
            continue
        prop, value = chunk.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            out[prop] = value
    return out


def parse_rules(css: Optional[str]) -> list[CssRule]:
    """Every rule of a theme ``<CSS>`` or ``<LocalCSS>``, one per selector. A selector with no
    state is the normal state; one with no sub-element is the box (``.self``)."""
    out: list[CssRule] = []
    for m in _BLOCK_RE.finditer(_COMMENT_RE.sub("", css or "")):
        decls = parse_declarations(m.group(2))
        for selector in m.group(1).split(","):
            s = _SELECTOR_RE.match(" ".join(selector.split()))
            if not s:
                continue
            out.append(CssRule(element=s.group("el"), cls=s.group("cls"), state=s.group("state") or "normal",
                               sub=s.group("sub") or "self", context=s.group("ctx"), decls=decls))
    return out


def _layer(rules: Iterable[CssRule]) -> dict[str, str]:
    """The plain CSS of a set of normal-state rules for one selector: box, then inner border, then text."""
    by_sub: dict[str, dict[str, str]] = {}
    for r in rules:
        by_sub.setdefault(r.sub, {}).update(r.decls)
    out: dict[str, str] = {}
    for sub, only in _SUBS:
        if sub in by_sub:
            out.update(clean_declarations(by_sub[sub], only))
    return out


class ThemeStyles:
    """A theme's ``<CSS>``, indexed for the cascade (normal state only)."""

    def __init__(self, css: Optional[str]) -> None:
        self._rules: dict[tuple[Optional[str], str, Optional[str]], list[CssRule]] = {}
        self._classes: dict[str, list[str]] = {}
        for r in parse_rules(css):
            if r.state != "normal":
                continue
            self._rules.setdefault((r.context, r.element, r.cls), []).append(r)
            if r.cls and r.context is None:
                els = self._classes.setdefault(r.cls, [])
                if r.element not in els:
                    els.append(r.element)
        self._cache: dict[tuple, dict[str, str]] = {}

    def __bool__(self) -> bool:
        return bool(self._rules)

    def rule(self, element: str, cls: Optional[str] = None, context: Optional[str] = None) -> dict[str, str]:
        """The plain CSS of ``[context ]element[.cls]:normal`` (box + inner border + text)."""
        key = (context, element, cls)
        if key not in self._cache:
            self._cache[key] = _layer(self._rules.get(key, ()))
        return self._cache[key]

    def has(self, element: str, cls: Optional[str] = None) -> bool:
        return (None, element, cls) in self._rules

    def style_element(self, element: Optional[str], cls: str) -> Optional[str]:
        """The element a named style is defined under: the object's own, a related one, or any."""
        for e in ((element,) if element else ()) + _ALIASES.get(element or "", ()):
            if self.has(e, cls):
                return e
        found = self._classes.get(cls)
        return found[0] if found else None


def resolve_style(theme: Optional[ThemeStyles], element: Optional[str], style_name: Optional[str] = None,
                  local_css: Optional[str] = None, part: Optional[str] = None) -> dict[str, str]:
    """An object's (or part's) normal-state style, as plain CSS.

    The cascade: the theme's ``element`` style, then ``<part> element`` (a theme's style for
    the element inside that part), then the named style ``element.<style_name>`` (looked up
    under a related element when the object's own has no such style, with that element's
    base style first), then the object's own ``<LocalCSS>``.
    """
    out: dict[str, str] = {}
    if theme and element:
        out.update(theme.rule(element))
        if part:
            out.update(theme.rule(element, context=part))
    if theme and style_name:
        owner = theme.style_element(element, style_name)
        if owner is not None:
            if owner != element:
                out.update(theme.rule(owner))
            out.update(theme.rule(owner, style_name))
    if local_css:
        out.update(_layer(r for r in parse_rules(local_css) if r.state == "normal" and r.element == "self"))
    return out


_SHORTHANDS = (
    ("border-color", tuple(f"border-{s}-color" for s in _SIDES)),
    ("border-width", tuple(f"border-{s}-width" for s in _SIDES)),
    ("border-style", tuple(f"border-{s}-style" for s in _SIDES)),
    ("border-radius", tuple(f"border-{c}-radius" for c in _CORNERS)),
    ("padding", tuple(f"padding-{s}" for s in _SIDES)),
)
SHORTHAND_NAMES = {name for name, _ in _SHORTHANDS}


def compact_style(style: dict[str, str]) -> dict[str, str]:
    """Four equal sides (or corners) as one shorthand: ``border-top-color`` … → ``border-color``.

    FileMaker writes every side; most are equal, and the style table is in every layout file.
    A radius with two values (``4px 8px``) stays per corner (the shorthand reads it differently).
    """
    out = dict(style)
    for name, longs in _SHORTHANDS:
        values = {out.get(p) for p in longs}
        if len(values) == 1 and None not in values and not (name == "border-radius" and " " in next(iter(values))):
            for p in longs:
                del out[p]
            out[name] = values.pop()
    return out


def is_opaque(style: Optional[dict[str, str]]) -> bool:
    """Whether a style paints a solid background (it hides what is behind it)."""
    bg = (style or {}).get("background-color", "")
    return bg.startswith("#") and len(bg) == 7


# ---------------------------------------------------------------------------
# Reading the CSS of a built docs folder (raw/themes.json, raw/layouts.json)
# ---------------------------------------------------------------------------

@dataclass
class LayoutCss:
    """One layout's CSS: its theme and each object's and part's ``<LocalCSS>``."""

    theme: Optional[ThemeStyles]
    objects: dict[str, list[tuple[Optional[str], Optional[str]]]]  # object id -> [(style name, local css)], doc order
    parts: list[tuple[Optional[str], Optional[str]]]  # per part, top to bottom

    def object_local(self, object_id: str) -> tuple[Optional[str], Optional[str]]:
        """``(style name, local css)`` of the next object with this id (ids can repeat in odd exports)."""
        found = self.objects.get(object_id)
        if not found:
            return None, None
        return found.pop(0) if len(found) > 1 else found[0]

    def background(self) -> dict[str, str]:
        if not self.theme:
            return {}
        return {k: v for k, v in self.theme.rule("layout_background").items() if k == "background-color"}


class StyleSource:
    """The CSS of one file's docs, from the scrubbed ``raw/`` files the build wrote.

    ``StyleSource.load(folder)`` is None when there is no ``raw/`` (``--no-raw-xml``,
    ``--no-json``, a render from model.json): the preview is then a wireframe only.
    """

    def __init__(self, themes: dict[str, str], layouts: dict[str, str]) -> None:
        self._themes_xml = themes
        self._layouts_xml = layouts
        self._themes: dict[str, Optional[ThemeStyles]] = {}

    @classmethod
    def load(cls, folder: Path) -> Optional["StyleSource"]:
        import orjson

        from ..contract import RAW_DIR, RAW_FILES

        layouts_path = Path(folder) / RAW_DIR / RAW_FILES["layouts"]
        themes_path = Path(folder) / RAW_DIR / RAW_FILES["themes"]
        if not layouts_path.is_file():
            return None
        try:
            layouts = orjson.loads(layouts_path.read_bytes()).get("xml") or {}
            themes = orjson.loads(themes_path.read_bytes()).get("xml") or {} if themes_path.is_file() else {}
        except (OSError, ValueError, AttributeError):
            return None
        if not isinstance(layouts, dict) or not isinstance(themes, dict):
            return None
        return cls(themes, layouts)

    def theme(self, theme_name: Optional[str]) -> Optional[ThemeStyles]:
        if not theme_name:
            return None
        if theme_name not in self._themes:
            from ..normalize.ids import theme_doc_id
            from ..normalize.names import normalize_name

            xml = self._themes_xml.get(theme_doc_id(normalize_name(theme_name)))
            css = _theme_css(xml) if xml else None
            styles = ThemeStyles(css) if css else None
            self._themes[theme_name] = styles if styles else None
        return self._themes[theme_name]

    def layout(self, layout_doc_id: str, theme_name: Optional[str] = None) -> Optional[LayoutCss]:
        """The CSS of a layout, or None when its XML isn't there."""
        xml = self._layouts_xml.get(layout_doc_id)
        if not xml:
            return None
        root = _parse(xml)
        if root is None:
            return None
        if not theme_name:
            ref = next((e for e in root if _local(e) == "LayoutThemeReference"), None)
            theme_name = ref.get("name") if ref is not None else None
        objects: dict[str, list[tuple[Optional[str], Optional[str]]]] = {}
        parts: list[tuple[Optional[str], Optional[str]]] = []
        for el in root.iter():
            name = _local(el)
            if name == "LayoutObject":
                local = next((c for c in el if _local(c) == "LocalCSS"), None)
                objects.setdefault(el.get("id", ""), []).append(_local_css(local))
            elif name == "Part":
                definition = next((c for c in el if _local(c) == "Definition"), None)
                local = next((c for c in definition if _local(c) == "LocalCSS"), None) if definition is not None else None
                parts.append(_local_css(local))
        return LayoutCss(theme=self.theme(theme_name), objects=objects, parts=parts)


def _local(el) -> str:
    from lxml import etree

    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _parse(xml: str):
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, strip_cdata=False)
    try:
        return etree.fromstring(xml.encode("utf-8"), parser)
    except etree.XMLSyntaxError:
        return None


def _theme_css(xml: str) -> Optional[str]:
    root = _parse(xml)
    if root is None:
        return None
    css = next((c for c in root if _local(c) == "CSS"), None)
    return css.text if css is not None else None


def _local_css(el) -> tuple[Optional[str], Optional[str]]:
    if el is None:
        return None, None
    return (el.get("name") or None), (el.text or None)
