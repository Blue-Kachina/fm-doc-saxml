"""High-entropy string literals (strict level only).

Catches random-looking secrets no shape or name identifies. Applied to whole
string literals, never to free text, and skips the identifiers FileMaker
itself generates (UUIDs, hex hashes).
"""

from __future__ import annotations

import math
import re
from collections import Counter

_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_HEX_RE = re.compile(r"[0-9A-Fa-f]+")
_TOKENISH_RE = re.compile(r"[A-Za-z0-9+/=_\-.]+")

MIN_LENGTH = 20
MIN_BITS_PER_CHAR = 4.0


def shannon_entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_random(literal: str) -> bool:
    if len(literal) < MIN_LENGTH or not _TOKENISH_RE.fullmatch(literal):
        return False
    if _UUID_RE.fullmatch(literal) or _HEX_RE.fullmatch(literal):
        return False
    # Needs a mix of character classes; a long word or number isn't a key.
    classes = sum(bool(re.search(p, literal)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 2 and shannon_entropy(literal) >= MIN_BITS_PER_CHAR
