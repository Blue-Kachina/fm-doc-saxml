"""Encoded credentials: base64 ``user:password`` literals.

A hardcoded Basic-auth value often rides as a bare base64 string assigned to an
innocently named variable, so no keyword or key shape sees it. Decoding is the
only reliable detector. Heuristic from the FileMaker XML Scrubber (Andrew Kear,
CC BY 4.0).
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Iterable

from ..policy import ScrubPolicy
from . import Hit

_B64_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{12,}={0,2}(?![A-Za-z0-9+/=])")
_USERPASS_RE = re.compile(r"[^:\s]{1,64}:\S.{0,127}")
_PRINTABLE_RE = re.compile(r"[\x20-\x7e]+")


def is_base64_userpass(token: str) -> bool:
    if len(token) % 4:
        return False
    try:
        decoded = base64.b64decode(token, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    if not 6 <= len(decoded) <= 194 or not _PRINTABLE_RE.fullmatch(decoded):
        return False
    # JSON / XML payloads (a lone JWT segment, an encoded body) are data, not credentials.
    if decoded[0] in "{<":
        return False
    if not _USERPASS_RE.fullmatch(decoded):
        return False
    # A slice of markup or a URL ("tp://www.w3.org/..." from a line of an encoded SVG), not a secret.
    _user, _, secret = decoded.partition(":")
    if secret.startswith("//") or any(c in decoded for c in '<>"'):
        return False
    return True


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    matches = list(_B64_RE.finditer(text))
    wrapped = _wrapped_block_members(text, matches)
    for i, m in enumerate(matches):
        if i not in wrapped and is_base64_userpass(m.group()):
            yield Hit(m.start(), m.end(), "password", "base64_userpass", 40)


# What may sit between two lines of one wrapped base64 value in a calc: line breaks,
# the pilcrow, and string concatenation ("…" & ¶ & "…").
_WRAP_GAP_RE = re.compile(r'[\s"&¶+]*')
_WRAP_LINE_MIN = 40


def _wrapped_block_members(text: str, matches: list[re.Match]) -> set[int]:
    """Indexes of matches that are lines of a longer base64 value wrapped over several lines.

    Image and file data (Base64Encode output, embedded icons) is wrapped at 64 or 76
    characters. One line of it can decode to printable text that happens to look like
    ``user:password``; a real credential is a single short token.
    """
    members: set[int] = set()
    for i in range(len(matches) - 1):
        a, b = matches[i], matches[i + 1]
        if (len(a.group()) >= _WRAP_LINE_MIN and len(b.group()) >= _WRAP_LINE_MIN
                and _WRAP_GAP_RE.fullmatch(text, a.end(), b.start())):
            members.update((i, i + 1))
    return members
