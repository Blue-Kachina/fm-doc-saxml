"""Markdown link destinations must be percent-encoded.

CommonMark link destinations written as bare `(...)` (no angle brackets)
break at the first space — anything after it becomes plain trailing text,
not part of the link. FileMaker script/layout/object names routinely
contain spaces (and sometimes parentheses), so every generated href needs
percent-encoding, not just edge cases.
"""

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.normalize.normalize import normalize
from fm_saxml.render.markdown.link_resolver import LinkResolver


def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.scripts = [
        {"id": "1", "name": "UI - Halt If Not in Browse Mode", "steps": []},
        {"id": "2", "name": "Loadi18n ( idLanguage )", "steps": []},
        {"id": "3", "name": "Caller", "steps": []},
    ]
    return raw


def _model():
    return normalize(_raw())


def test_md_link_percent_encodes_spaces():
    links = LinkResolver(_model())
    md = links.md_link("Scripts/Caller.md", "script:UI - Halt If Not in Browse Mode")
    dest = md[md.index("(") + 1: md.rindex(")")]
    assert " " not in dest
    assert "%20" in dest


def test_md_link_percent_encodes_parentheses():
    links = LinkResolver(_model())
    md = links.md_link("Scripts/Caller.md", "script:Loadi18n ( idLanguage )")
    # The label itself legitimately contains parens; only check the destination.
    dest = md[md.index("](") + 2: md.rindex(")")]
    assert "(" not in dest and ")" not in dest


def test_md_link_produces_a_commonmark_safe_destination():
    links = LinkResolver(_model())
    md = links.md_link("Scripts/Caller.md", "script:UI - Halt If Not in Browse Mode")
    # The destination is everything between the first unescaped '(' and the
    # matching ')' — with encoding applied, that must contain no raw space.
    dest = md[md.index("(") + 1: md.rindex(")")]
    assert " " not in dest


def test_md_link_label_is_left_readable():
    links = LinkResolver(_model())
    md = links.md_link("Scripts/Caller.md", "script:UI - Halt If Not in Browse Mode")
    assert md.startswith("[UI - Halt If Not in Browse Mode]")
