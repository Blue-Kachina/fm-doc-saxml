"""Placeholders: the same secret gets the same label everywhere.

``[REDACTED:api_key#1]`` used in five scripts tells a reader "these calls share
one key" without revealing it. A registry can be shared by several runs (the
two sides of a ``diff``) so a changed value shows up as a changed label.

Two styles:

* **numbered** (default): ``#1``, ``#2`` in order of discovery. Stable within one run.
* **fingerprint**: ``#3f9a1c``, a keyed hash (HMAC-SHA256) of the value under a secret
  salt from ``FM_SAXML_SCRUB_SALT``. Stable across runs and machines that share the
  salt, so placeholders in separately saved models can be compared. Without the
  salt the fingerprint can't be reversed or brute-forced; with a short or leaked
  salt, a weak password could be, so the salt must be long and kept private.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from typing import Optional

from .policy import CREDENTIAL_CATEGORIES

PLACEHOLDER_RE = re.compile(
    r"\[(?:REDACTED:[a-z_]+|HOST|USER|EMAIL|CARD|PERSON|PHONE|IBAN|NATIONAL_ID)#[0-9a-f]+\]"
)

_LABELS = {
    "host": "HOST", "user": "USER", "email": "EMAIL", "card": "CARD", "person": "PERSON",
    "phone": "PHONE", "iban": "IBAN", "national_id": "NATIONAL_ID",
}

# Words too common to replace everywhere just because they were a home-dir or account name.
_COMMON_NAMES = {
    "admin", "administrator", "user", "users", "guest", "root", "test", "tester", "dev",
    "developer", "owner", "default", "public", "server", "client", "local",
}

MIN_SALT_LENGTH = 16
_FINGERPRINT_LENGTH = 6


def label_for(category: str) -> str:
    if category in CREDENTIAL_CATEGORIES:
        return f"REDACTED:{category}"
    return _LABELS.get(category, "REDACTED:credential")


def substitutable(value: str, category: str) -> bool:
    """Whether every occurrence of ``value`` can safely be replaced, not just the detected one.

    A credential like ``"password"`` or a host like ``intranet`` is also an ordinary
    word, and replacing it in every comment would mangle the documentation.
    """
    v = value.strip()
    if category in CREDENTIAL_CATEGORIES:
        # Letters only ("password", "changeme") reads as a word; needs to be long to be safe.
        return len(v) >= 12 if v.isalpha() else len(v) >= 6
    if category == "host":
        return len(v) >= 4 and any(c == "." or c.isdigit() for c in v)
    if category in ("user", "person"):
        return len(v) >= 3 and v.lower() not in _COMMON_NAMES
    return len(v) >= 4


class PlaceholderRegistry:
    def __init__(self, salt: Optional[str] = None) -> None:
        self._by_value: dict[str, tuple[str, str]] = {}
        self._taken: set[str] = set()
        self._counters: Counter[str] = Counter()
        self._key = salt.encode("utf-8") if salt else None

    @property
    def style(self) -> str:
        return "fingerprint" if self._key else "numbered"

    @property
    def salt_id(self) -> Optional[str]:
        """Identifies the salt (not the salt itself), so two models can tell whether they share one."""
        if not self._key:
            return None
        return hmac.new(self._key, b"fm-saxml/salt-id", hashlib.sha256).hexdigest()[:8]

    def placeholder(self, value: str, category: str) -> str:
        known = self._by_value.get(value)
        if known:
            return known[0]
        label = label_for(category)
        if self._key:
            digest = hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()
            n = _FINGERPRINT_LENGTH
            ph = f"[{label}#{digest[:n]}]"
            while ph in self._taken:  # a short-prefix collision between two values
                n += 2
                ph = f"[{label}#{digest[:n]}]"
        else:
            self._counters[label] += 1
            ph = f"[{label}#{self._counters[label]}]"
        self._by_value[value] = (ph, category)
        self._taken.add(ph)
        return ph

    def category_of(self, value: str) -> str:
        return self._by_value[value][1]

    def substitutable_values(self) -> dict[str, str]:
        """value -> placeholder for every value safe to replace (and to guard for) everywhere."""
        return {v: ph for v, (ph, cat) in self._by_value.items() if substitutable(v, cat)}

    def values(self) -> list[str]:
        return list(self._by_value)

    def __len__(self) -> int:
        return len(self._by_value)
