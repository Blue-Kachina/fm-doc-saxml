"""A small, lossless tokenizer for FileMaker calculation text.

Scrubbing only ever rewrites the *contents* of string literals and comments.
The lexer is what makes that guarantee checkable: every character of the input
lands in exactly one token, so ``"".join(t.text for t in tokens) == text``, and
any change outside a STRING / COMMENT token is a bug.

FileMaker strings are double-quoted only, with backslash escapes (``\\"``,
``\\\\``, ``\\¶``). Comments are ``/* ... */`` (not nested) and ``// ...`` to the
end of the line. Unterminated strings and comments run to the end of the text,
which is what FileMaker's own editor does with them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STRING = "STRING"
COMMENT = "COMMENT"
WS = "WS"
VAR = "VAR"
NAME = "NAME"
NUMBER = "NUMBER"
OP = "OP"

_TOKEN_RE = re.compile(
    r"""
      (?P<STRING>"(?:[^"\\]|\\.)*(?:"|\Z))
    | (?P<BLOCK>/\*.*?(?:\*/|\Z))
    | (?P<LINE>//[^\r\n]*)
    | (?P<WS>\s+)
    | (?P<VAR>\${1,2}[\w.~]+)
    | (?P<NAME>[^\W\d][\w.~]*|~[\w.~]+)
    | (?P<NUMBER>\d+(?:\.\d+)?)
    | (?P<OP>.)
    """,
    re.S | re.X,
)

_KIND = {"BLOCK": COMMENT, "LINE": COMMENT}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    start: int
    end: int

    @property
    def content_span(self) -> tuple[int, int]:
        """Absolute span of the editable inside of a STRING or COMMENT token."""
        if self.kind == STRING:
            closed = len(self.text) >= 2 and self.text.endswith('"') and not _escaped_close(self.text)
            return self.start + 1, self.end - (1 if closed else 0)
        if self.kind == COMMENT:
            if self.text.startswith("/*"):
                closed = len(self.text) >= 4 and self.text.endswith("*/")
                return self.start + 2, self.end - (2 if closed else 0)
            return self.start + 2, self.end
        return self.start, self.start


def _escaped_close(text: str) -> bool:
    """True when the final quote is escaped, i.e. the string is unterminated."""
    backslashes = len(text) - 1 - len(text[:-1].rstrip("\\"))
    return backslashes % 2 == 1


def tokenize(text: str) -> list[Token]:
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        group = m.lastgroup
        tokens.append(Token(_KIND.get(group, group), m.group(), m.start(), m.end()))
    return tokens


def significant(tokens: list[Token]) -> list[Token]:
    """Tokens without whitespace, for simple look-behind rules."""
    return [t for t in tokens if t.kind != WS]
