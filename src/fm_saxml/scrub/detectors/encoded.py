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
    return bool(_USERPASS_RE.fullmatch(decoded))


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    for m in _B64_RE.finditer(text):
        if is_base64_userpass(m.group()):
            yield Hit(m.start(), m.end(), "password", "base64_userpass", 40)
