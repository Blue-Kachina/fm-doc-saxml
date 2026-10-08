"""Personal data: email addresses and card numbers."""

from __future__ import annotations

import re
from typing import Iterable

from ..policy import ScrubPolicy
from . import Hit

_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
# 13-19 digits, optionally grouped by spaces or dashes, not glued to letters (hex, ids).
_CARD_RE = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")


def _is_url_userinfo(text: str, start: int) -> bool:
    """``https://user:pass@host`` and ``ftp://user@host`` look like addresses but aren't."""
    before = text[max(0, start - 7):start].lower()
    if before.endswith("mailto:"):
        return False
    return before.endswith((":", "/"))


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --- strict level -------------------------------------------------------------
# Separators required, so bare digit runs (ids, timestamps) don't qualify.
_NANP_PHONE_RE = re.compile(r"(?<![\d+])(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?![\d-])")
_INTL_PHONE_RE = re.compile(r"(?<![\w+])\+[1-9]\d{0,2}(?:[ .-]\(?\d{1,4}\)?){2,5}(?![\d-])")
_IBAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Z0-9])")
_SSN_RE = re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])")
_SIN_RE = re.compile(r"(?<![\d-])[1-79]\d{2}[ -]\d{3}[ -]\d{3}(?![\d-])")


def iban_ok(iban: str) -> bool:
    s = iban.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def _strict_hits(text: str) -> Iterable[Hit]:
    for pattern in (_NANP_PHONE_RE, _INTL_PHONE_RE):
        for m in pattern.finditer(text):
            digits = sum(c.isdigit() for c in m.group())
            if 10 <= digits <= 15:
                yield Hit(m.start(), m.end(), "phone", "phone_number", 72)
    for m in _IBAN_RE.finditer(text):
        if iban_ok(m.group()):
            yield Hit(m.start(), m.end(), "iban", "iban", 71)
    for m in _SSN_RE.finditer(text):
        yield Hit(m.start(), m.end(), "national_id", "us_ssn", 71)
    for m in _SIN_RE.finditer(text):
        if luhn_ok(re.sub(r"[ -]", "", m.group())):
            yield Hit(m.start(), m.end(), "national_id", "canadian_sin", 71)


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    if policy.strict and any(c.isdigit() for c in text):
        yield from _strict_hits(text)
    if "@" in text:
        for m in _EMAIL_RE.finditer(text):
            if _is_url_userinfo(text, m.start()):
                continue
            yield Hit(m.start(), m.end(), "email", "email", 70)
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        # Luhn keeps FileMaker's own long ids and timestamps out.
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            yield Hit(m.start(), m.end(), "card", "card_number", 70)
