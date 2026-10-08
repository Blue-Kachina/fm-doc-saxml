"""FileMaker calc lexer: lossless, and string/comment boundaries are right."""

import pytest

from fm_saxml.scrub.calc_lexer import COMMENT, NAME, OP, STRING, VAR, tokenize

CALCS = [
    'Let ( [ $x = "a" ; ~y = 2 ] ; $x & ~y )',
    '"He said \\"hi\\"" & ¶ & "C:\\\\path\\\\"',
    '/* block "with quotes" */ 1 // line "comment"\n2',
    '"unterminated',
    '"ends with escaped quote \\"',
    '/* unterminated comment',
    'Table::Field & $$global & Custom.Function ( 1.5 ; "x" )',
    "",
]


@pytest.mark.parametrize("calc", CALCS)
def test_tokens_reassemble_the_input_exactly(calc):
    assert "".join(t.text for t in tokenize(calc)) == calc


def test_strings_respect_backslash_escapes():
    toks = [t for t in tokenize('"a \\"b\\" c" & "d"') if t.kind == STRING]
    assert [t.text for t in toks] == ['"a \\"b\\" c"', '"d"']


def test_comment_markers_inside_strings_are_not_comments():
    toks = tokenize('"http://x/*y*/" & 1')
    assert [t.kind for t in toks if t.kind in (STRING, COMMENT)] == [STRING]


def test_quotes_inside_comments_are_not_strings():
    toks = tokenize('/* "a" */ "b" // "c"')
    assert [(t.kind, t.text) for t in toks if t.kind in (STRING, COMMENT)] == [
        (COMMENT, '/* "a" */'), (STRING, '"b"'), (COMMENT, '// "c"'),
    ]


def test_variables_and_names():
    kinds = [(t.kind, t.text) for t in tokenize("$a = $$b.c ; ~loc = Foo.Bar") if t.kind != "WS"]
    assert kinds == [
        (VAR, "$a"), (OP, "="), (VAR, "$$b.c"), (OP, ";"), (NAME, "~loc"), (OP, "="), (NAME, "Foo.Bar"),
    ]


@pytest.mark.parametrize("calc,inner", [
    ('"abc"', "abc"),
    ('"abc', "abc"),
    ('"ab\\"', 'ab\\"'),
    ('/* x */', " x "),
    ("// y", " y"),
    ("/* z", " z"),
])
def test_content_span_excludes_delimiters(calc, inner):
    tok = tokenize(calc)[0]
    start, end = tok.content_span
    assert calc[start:end] == inner
