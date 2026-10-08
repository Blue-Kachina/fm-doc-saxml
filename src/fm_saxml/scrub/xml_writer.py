"""Write a scrubbed copy of a Save a Copy as XML export (``fm-saxml scrub``).

Only ``FMSaveAsXML`` exports are accepted. Clipboard XML (``fmxmlsnippet``) and
DDR reports (``FMPReport``) lay out step parameters differently, and the
structural rules here are built on SaveAsXML's typed ``<Parameter>`` elements.

How the edits get from the model back into the XML:

1. The export is parsed and scrubbed exactly as ``build`` does it, so structural
   rules, variable tracing and both passes apply. The scrubber reports every
   string it changed, as (original, scrubbed) pairs.
2. Each text node and attribute of the source tree is matched against those:
   * an exact match (a calc's ``<Text>``, a comment, a value) gets the scrubbed version;
   * otherwise each changed literal or comment *token* is replaced where it appears,
     which covers the copies in ``DDR_INFO``: ChunkList chunks and rendered StepText;
   * values known to be secret are substituted, and anything the parser doesn't
     extract (comment steps, step text) is run through the detectors.
   Binary streams (``<Stream type="Hex">`` …) are never touched.
3. ``hash`` attributes are removed from every changed element and its ancestors,
   and from anything that refers to a removed hash. A digest of the original
   content would let someone confirm a guessed weak password offline.
4. The output is the original file with **only those spans patched**: same
   encoding, BOM, declaration, line endings and formatting, so a diff against
   the input shows exactly what was redacted. Each patch is verified against the
   parsed value first; if any can't be located exactly, the whole document is
   re-serialized instead (equivalent XML, different formatting) and the result says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from lxml import etree

from ..model.document_model import ScrubSummary
from .calc_lexer import COMMENT, STRING, tokenize
from .engine import Scrubber
from .guard import Leak, find_leaks_in_text
from .placeholders import PLACEHOLDER_RE
from .walker import _classify, snake

SUPPORTED_ROOT = "FMSaveAsXML"
_OTHER_FORMATS = {
    "fmxmlsnippet": "clipboard XML (fmxmlsnippet)",
    "FMPReport": "a Database Design Report (FMPReport)",
}
_DECL_RE = re.compile(r"\A\s*(<\?xml[^>]*\?>)(\r?\n)?")
_ENCODING_ATTR_RE = re.compile(r"""encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")
_SKIP_TEXT_TAGS = {"UUID", "DDRREF", "Stream", "BinaryData"}
_BINARY_TYPES = {"hex", "base64", "binary"}


class UnsupportedFormat(ValueError):
    pass


@dataclass
class XmlScrubResult:
    summary: ScrubSummary
    nodes_changed: int
    hashes_removed: int
    leaks: list[Leak]
    reformatted: bool = False  # True when the file had to be re-serialized instead of patched


def detect_encoding(data: bytes) -> tuple[str, bytes]:
    """(Python codec, BOM to write back) for an XML file's bytes."""
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le", b"\xff\xfe"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be", b"\xfe\xff"
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8", b"\xef\xbb\xbf"
    head = data[:200].decode("ascii", errors="replace")
    m = _ENCODING_ATTR_RE.search(head)
    return (m.group(1).lower() if m else "utf-8"), b""


def scrub_xml_file(src: Path, dst: Path, scrubber: Scrubber) -> XmlScrubResult:
    from ..parser.saxml_reader import parse_savexml

    data = src.read_bytes()
    codec, bom = detect_encoding(data)
    parser = etree.XMLParser(strip_cdata=False, huge_tree=True, resolve_entities=False,
                             remove_blank_text=False, no_network=True)
    try:
        tree = etree.parse(str(src), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"not valid XML ({exc})") from exc
    root = tree.getroot()
    root_tag = etree.QName(root).localname
    if root_tag != SUPPORTED_ROOT:
        what = _OTHER_FORMATS.get(root_tag, f"a <{root_tag}> document")
        raise UnsupportedFormat(
            f"this is {what}, not a Save a Copy as XML export. fm-saxml scrub only handles <FMSaveAsXML> files."
        )

    # 1. The model pass: everything build would redact.
    raw = parse_savexml(src)
    summary = scrubber.scrub_raw(raw)
    edits = _Edits(scrubber.last_changes)

    # 2. Apply to every text node and attribute of the source tree.
    rewriter = _Rewriter(scrubber, edits)
    rewriter.rewrite(root)
    dropped = _drop_hashes(root, {e.el for e in rewriter.edits})

    # Findings for values only the XML pass saw (not in the model).
    seen = {f.placeholder for f in summary.findings}
    extra = [f for f in scrubber._finalize() if f.action != "redacted" or f.placeholder not in seen]
    summary.findings.extend(extra)
    summary.counts = scrubber.summary(summary.findings).counts

    # 3. Patch the original text; re-serialize only if a patch can't be placed exactly.
    original = data[len(bom):].decode(codec)
    text = _patch_source(original, root, rewriter.edits, dropped)
    reformatted = text is None
    if text is None:
        text = _serialize(tree, original)
    dst.write_bytes(bom + text.encode(codec))

    leaks = find_leaks_in_text(dst, text, scrubber.guard_values())
    return XmlScrubResult(summary, len({e.el for e in rewriter.edits}), len(dropped), leaks, reformatted)


# ---------------------------------------------------------------------------
# What changed
# ---------------------------------------------------------------------------

class _Edits:
    """What the model pass changed, as exact strings and as literal/comment tokens."""

    def __init__(self, changes: list[tuple[str, str, str]]) -> None:
        self.exact: dict[str, str] = {}
        tokens: dict[str, str] = {}
        for kind, old, new in changes:
            key = old.strip()
            current = self.exact.get(key)
            # The same text redacted differently in two places: keep the more redacted one.
            if current is None or _placeholder_count(new) > _placeholder_count(current):
                self.exact[key] = new.strip()
            if kind == "calc":
                for a, b in zip(tokenize(old), tokenize(new)):
                    if a.kind in (STRING, COMMENT) and a.text != b.text and len(a.text) > 2:
                        tokens.setdefault(a.text, b.text)
        self.tokens = sorted(tokens.items(), key=lambda kv: len(kv[0]), reverse=True)

    def replace_tokens(self, value: str) -> str:
        for old, new in self.tokens:
            if old in value:
                value = value.replace(old, new)
        return value


def _placeholder_count(s: str) -> int:
    return len(PLACEHOLDER_RE.findall(s))


@dataclass
class _Edit:
    el: etree._Element
    attr: Optional[str]  # None for the element's text
    old: str
    new: str


class _Rewriter:
    def __init__(self, scrubber: Scrubber, edits: _Edits) -> None:
        self.scrubber = scrubber
        self.patterns = edits
        self._edits: dict[tuple[int, Optional[str]], _Edit] = {}

    @property
    def edits(self) -> list[_Edit]:
        return list(self._edits.values())

    def rewrite(self, root: etree._Element) -> None:
        sites = list(self._sites(root))
        for el, attr, kind, where in sites:
            self._update(el, attr, self._scrub(self._get(el, attr), kind, where))
        # A value first detected late in the document must also go from the nodes
        # before it: substitute again until no new value turns up.
        for _ in range(5):
            known = len(self.scrubber.registry)
            for el, attr, kind, _where in sites:
                value = self._get(el, attr)
                if kind == "calc":
                    new = self.scrubber.substitute_calc(value)
                else:
                    new = self.scrubber.substitute(value)
                self._update(el, attr, new)
            if len(self.scrubber.registry) == known:
                break

    def _sites(self, root: etree._Element):
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue  # XML comments / PIs: none in FileMaker exports
            tag = etree.QName(el).localname
            parent = el.getparent()
            parent_tag = etree.QName(parent).localname if parent is not None else ""
            where = f"XML <{parent_tag}><{tag}>" if parent_tag else f"XML <{tag}>"
            binary = tag in _SKIP_TEXT_TAGS or (el.get("type") or "").lower() in _BINARY_TYPES
            if el.text and el.text.strip() and not binary:
                if tag == "Text" and parent_tag == "Calculation":
                    kind = "calc"
                elif tag == "Chunk":
                    kind = "chunk"
                else:
                    kind = "text" if _classify(snake(tag.lstrip("_")), None, False) else "name"
                yield el, None, kind, where
            for name, value in el.attrib.items():
                if name != "hash" and value.strip():
                    kind = "text" if _classify(snake(name), None, False) else "name"
                    yield el, name, kind, f"{where} @{name}"

    @staticmethod
    def _get(el: etree._Element, attr: Optional[str]) -> str:
        return (el.text or "") if attr is None else (el.get(attr) or "")

    def _update(self, el: etree._Element, attr: Optional[str], new: str) -> None:
        current = self._get(el, attr)
        if new == current:
            return
        key = (id(el), attr)
        if key in self._edits:
            self._edits[key].new = new
        else:
            self._edits[key] = _Edit(el, attr, current, new)
        if attr is None:
            _set_text(el, new)
        else:
            el.set(attr, new)

    def _scrub(self, value: str, kind: str, where: str) -> str:
        stripped = value.strip()
        exact = self.patterns.exact.get(stripped)
        if exact is not None:
            return value.replace(stripped, exact, 1)
        new = self.patterns.replace_tokens(value)
        if kind == "calc":
            # A calc the parser didn't extract: scrub it the same way, in calc mode.
            return self.scrubber.scrub_calc(new, where)
        new = self.scrubber.substitute(new)
        if kind == "text":
            new = self.scrubber.scrub_text(new, where)
        return new


def _set_text(el: etree._Element, new: str) -> None:
    was_cdata = etree.tostring(el, encoding="unicode", with_tail=False).find("<![CDATA[") != -1
    el.text = etree.CDATA(new) if was_cdata and "]]>" not in new else new


def _drop_hashes(root: etree._Element, changed: set[etree._Element]) -> list[tuple[etree._Element, str]]:
    """Remove content digests that would still describe the original values."""
    dropped: list[tuple[etree._Element, str]] = []
    removed_values: set[str] = set()
    changed_keys: set[str] = set()
    for el in changed:
        for node in [el, *el.iterancestors()]:
            h = node.attrib.pop("hash", None)
            if h:
                removed_values.add(h)
                dropped.append((node, h))
            tag = etree.QName(node).localname
            if tag.startswith("_"):  # a DDR_INFO entry, referenced by <DDRREF>key</DDRREF>
                changed_keys.add(tag)
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        h = el.get("hash")
        is_ref = etree.QName(el).localname == "DDRREF" and (el.text or "").strip() in changed_keys
        if h and (h in removed_values or is_ref):
            del el.attrib["hash"]
            dropped.append((el, h))
    return dropped


# ---------------------------------------------------------------------------
# Writing: patch the original text in place
# ---------------------------------------------------------------------------

# Markup in document order; group 1 is set for start tags only.
_MARKUP_RE = re.compile(
    r"<!\[CDATA\[.*?\]\]>|<!--.*?-->|<\?.*?\?>|<!DOCTYPE[^>\[]*(?:\[.*?\])?\s*>|</[^>]*>|<([A-Za-z_][\w.:-]*)",
    re.S,
)
_ENTITY_RE = re.compile(r"&(#x[0-9A-Fa-f]+|#\d+|amp|lt|gt|quot|apos);")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _decode(raw: str, mode: str) -> tuple[str, list[int]]:
    """What a parser makes of ``raw``, plus where each decoded character starts in ``raw``.

    ``mode`` is "cdata" (only line ends are normalized), "text" (entities too) or
    "attr" (and whitespace becomes spaces). ``starts`` has one extra entry: len(raw).
    """
    out: list[str] = []
    starts: list[int] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "\r":
            step = 2 if raw.startswith("\r\n", i) else 1
            ch = " " if mode == "attr" else "\n"
        elif c == "&" and mode != "cdata" and (m := _ENTITY_RE.match(raw, i)):
            ref = m.group(1)
            ch = chr(int(ref[2:], 16)) if ref.startswith("#x") else chr(int(ref[1:])) if ref[0] == "#" else _NAMED[ref]
            step = m.end() - i
        else:
            ch = " " if mode == "attr" and c in "\n\t" else c
            step = 1
        out.append(ch)
        starts.append(i)
        i += step
    starts.append(n)
    return "".join(out), starts


def _escape_like(new: str, raw: str, mode: str, quote: str = '"') -> str:
    """Escape an inserted segment the way the surrounding original text is escaped."""
    if mode == "cdata":
        return new
    out = new.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if mode == "attr":
        out = out.replace(quote, "&quot;" if quote == '"' else "&apos;")
        return out.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
    if '"' not in raw or "&quot;" in raw:
        out = out.replace('"', "&quot;")
    if "&apos;" in raw:
        out = out.replace("'", "&apos;")
    return out.replace("\r", "&#13;")


def _segment_patches(raw: str, raw_start: int, mode: str, old: str, new: str,
                     quote: str = '"') -> Optional[list[tuple[int, int, str]]]:
    """Spans of the original file to replace so that ``raw`` parses as ``new`` instead of ``old``.

    Only the characters that actually changed are touched, so line endings, entity
    style and everything around a placeholder stay byte-for-byte as they were.
    """
    decoded, starts = _decode(raw, mode)
    if decoded != old:
        return None
    # Diff word-sized tokens, not characters, so a secret and its placeholder that
    # happen to share a letter are still replaced as one piece.
    a_tok, b_tok = _WORDS_RE.findall(old), _WORDS_RE.findall(new)
    a_at, b_at = _offsets(a_tok), _offsets(b_tok)
    patches = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a_tok, b_tok, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        o1, o2, n1, n2 = a_at[i1], a_at[i2], b_at[j1], b_at[j2]
        patches.append((raw_start + starts[o1], raw_start + starts[o2], _escape_like(new[n1:n2], raw, mode, quote)))
    return patches


_WORDS_RE = re.compile(r"\w+|\s+|[^\w\s]", re.S)


def _offsets(tokens: list[str]) -> list[int]:
    at = [0]
    for t in tokens:
        at.append(at[-1] + len(t))
    return at


def _start_tag_end(text: str, pos: int) -> int:
    """Index just past the '>' closing the start tag that begins at ``pos``."""
    quote = None
    for i in range(pos, len(text)):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ">":
            return i + 1
    raise ValueError("unterminated start tag")


def _patch_source(original: str, root: etree._Element, edits: list[_Edit],
                  dropped: list[tuple[etree._Element, str]]) -> Optional[str]:
    # Element k in document order is start tag k in the text. (libxml2's sourceline
    # can't be used: it stops counting at 65535 lines.)
    targets = {e.el for e in edits} | {el for el, _ in dropped}
    tags = [(m.start(), m.group(1)) for m in _MARKUP_RE.finditer(original) if m.group(1)]
    where: dict[etree._Element, int] = {}
    for k, el in enumerate(e for e in root.iter() if isinstance(e.tag, str)):
        if el in targets:
            if k >= len(tags) or tags[k][1] != el.tag:
                return None  # text and tree disagree: don't guess
            where[el] = tags[k][0]

    def start_tag(el: etree._Element) -> tuple[int, int]:
        start = where[el]
        return start, _start_tag_end(original, start)

    spans: list[tuple[int, int, str]] = []
    try:
        for e in edits:
            s, end = start_tag(e.el)
            if e.attr is None:
                if original.startswith("<![CDATA[", end):
                    a = end + len("<![CDATA[")
                    b = original.index("]]>", a)
                    if "]]>" in e.new:
                        return None
                    patches = _segment_patches(original[a:b], a, "cdata", e.old, e.new)
                else:
                    b = original.index("<", end)
                    patches = _segment_patches(original[end:b], end, "text", e.old, e.new)
            else:
                m = re.compile(r"\s" + re.escape(e.attr) + r"\s*=\s*([\"'])(.*?)\1", re.S).search(original, s, end)
                if m is None:
                    return None
                patches = _segment_patches(m.group(2), m.start(2), "attr", e.old, e.new, m.group(1))
            if patches is None:
                return None
            spans.extend(patches)
        for el, value in dropped:
            s, end = start_tag(el)
            m = re.compile(r"\s+hash\s*=\s*([\"'])" + re.escape(value) + r"\1").search(original, s, end)
            if m is None:
                return None
            spans.append((m.start(), m.end(), ""))
    except ValueError:
        return None

    spans.sort()
    for (a1, b1, _), (a2, _, _) in zip(spans, spans[1:]):
        if a2 < b1:
            return None  # overlapping edits: don't guess
    out, pos = [], 0
    for a, b, rep in spans:
        out.append(original[pos:a])
        out.append(rep)
        pos = b
    out.append(original[pos:])
    patched = "".join(out)
    try:  # must still be well-formed (checked without the declaration, which may name UTF-16)
        etree.fromstring(_DECL_RE.sub("", patched).encode("utf-8"),
                         etree.XMLParser(huge_tree=True, resolve_entities=False))
    except etree.XMLSyntaxError:
        return None
    return patched


def _serialize(tree: etree._ElementTree, original: str) -> str:
    """Fallback: the modified tree, with the input's declaration and line endings."""
    body = etree.tostring(tree, encoding="unicode")
    crlf = "\r\n" in original and original.count("\n") == original.count("\r\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    decl = _DECL_RE.match(original)
    return (decl.group(1) + (decl.group(2) or ("\r\n" if crlf else "\n")) + body) if decl else body
