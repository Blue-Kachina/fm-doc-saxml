"""Credentials written as prose: "temp password is swordfish99", "API key: Zx81-…".

The keyword rules need ``name = "value"`` syntax, so documentation that simply
states a secret slips through them. Redacting prose wholesale would mangle the
docs, so only the value token is touched, and only when it clearly looks like
a secret (digits, symbols or mixed case). A plain word long enough to be a
password is flagged for review instead. Everything else ("password is
required") is left alone.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from ..policy import ScrubPolicy, category_from_name
from . import Hit

_COMMON_WORDS = {
    "required", "optional", "missing", "invalid", "incorrect", "wrong", "expired", "changed",
    "stored", "saved", "needed", "empty", "blank", "valid", "null", "none", "true", "false",
    "reset", "sent", "set", "defined", "provided", "supplied", "encrypted", "hashed", "hidden",
    "masked", "generated", "returned", "passed", "used", "unique", "different", "configured",
    "located", "available", "unknown", "below", "above", "there", "here", "always", "never",
    "stored", "shared", "private", "public", "secret", "correct", "same", "obtained", "fetched",
    "retrieved", "refreshed", "rotated", "revoked", "updated", "created", "deleted", "please",
    # programming words: "password: parameter is a JSON…", "token: string"
    "parameter", "parameters", "string", "number", "object", "variable", "variables", "field",
    "fields", "value", "values", "boolean", "array", "script", "result", "response", "request",
    "header", "headers", "payload", "argument", "arguments", "function", "global", "optional",
}
_TRAILING_PUNCT = ".,;:)]}!?'\""
_AUTH_SCHEMES = {"bearer", "basic", "token", "digest", "oauth", "negotiate", "apikey"}
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z-]*")


@lru_cache(maxsize=8)
def _prose_re(keyword_alt: str) -> re.Pattern:
    return re.compile(
        r"(?<![\w$:])((?:" + keyword_alt + r")[\w-]*)"     # the credential word, not a Table::field name
        r"[^\r\n=:]{0,24}?"                                 # "for the staging server"
        r"(?:\s(?:is|was|=)\s|\s?(?<!:)[:=](?!:)\s?)"       # "is" / ":" / "=", but not "::"
        r"[\"'“]?([^\s\"'“”,;()<>]{3,})",                   # the value token
        re.I,
    )


# An attribute name and its "=", as markup in a string writes it: type=  type=\  (before \"…\")
_ATTRIBUTE_RE = re.compile(r"[A-Za-z_][\w.-]*=\\?")


def _is_markup(text: str, m: re.Match, value: str) -> bool:
    """XML or HTML after a credential word, not a credential: ``<token xsi:type=\\"xsd:string\\">``.

    The ":" there is a namespace prefix glued to the words on both sides, and it belongs to
    another word than the credential one (``apikey:Zx81`` is still a credential). A value
    that is only an attribute name and its "=" is markup too.
    """
    if _ATTRIBUTE_RE.fullmatch(value):
        return True
    sep = m.start(2) - 1
    while sep > m.end(1) and text[sep] in "\"'“":
        sep -= 1
    return (text[sep] == ":" and sep > m.end(1) and text[sep - 1].isalnum()
            and text[sep + 1:sep + 2].isalnum() and text[m.end(1):sep].strip() != "")


def _looks_secret(value: str) -> bool:
    has_digit = any(c.isdigit() for c in value)
    has_symbol = any(not c.isalnum() for c in value)
    mixed_case = any(c.isupper() for c in value[1:]) and any(c.islower() for c in value)
    return len(value) >= 4 and (has_digit or has_symbol or mixed_case)


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    if not policy.keyword_re.search(text):
        return
    for m in _prose_re(policy.keyword_alt).finditer(text):
        start, end = m.span(2)
        value = m.group(2)
        stripped = value.rstrip(_TRAILING_PUNCT)
        end -= len(value) - len(stripped)
        value = stripped
        # A reference or a placeholder is where the secret lives, not the secret;
        # "Authorization: Bearer " names the scheme, the token comes after it.
        if not value or value.startswith(("$", "[")) or "::" in value or "(" in value:
            continue
        if value.lower() in _AUTH_SCHEMES:
            continue
        if _is_markup(text, m, value):
            continue
        # "Authorization: DeepL-Auth-Key " & $key: a vendor's scheme name, followed by the
        # (separately concatenated) key. A word of letters and hyphens then a space is a scheme.
        if (m.group(1).lower().endswith("authorization") and _SCHEME_RE.fullmatch(value)
                and text[end:end + 1] in (" ", "\t")):
            continue
        if not policy.is_credential_name(m.group(1)):
            continue
        category = category_from_name(m.group(1))
        if _looks_secret(value):
            yield Hit(start, end, category, "comment_credential", 45)
        elif value.isalpha() and len(value) >= 6 and value.lower() not in _COMMON_WORDS:
            yield Hit(start, end, category, "comment_review", 46, flag=True)
