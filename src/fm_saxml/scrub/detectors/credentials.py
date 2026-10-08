"""Credentials identified by where they sit: JSON keys, HTTP headers, URLs, connection strings.

The value's shape says nothing here; the name or header in front of it does.
Rules adapted from the FileMaker XML Scrubber (Andrew Kear, CC BY 4.0).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from ..policy import ScrubPolicy, category_from_name
from . import Hit, regex_hits

# A header/param value runs until whitespace, a quote, a backslash (escaped quote
# or \r\n inside a FileMaker string) or a separator.
_VAL = r"[^\s\"'\\;,&]+"

_AUTH_HEADER_RE = re.compile(
    r"(?:Proxy-)?Authorization\s*[:=]\s*\\?[\"']?\s*(?:Bearer|Basic|Token|Digest|OAuth)\s+(" + _VAL + ")",
    re.I,
)
_KEY_HEADER_RE = re.compile(
    r"(?:X-)?(?:API[_-]?Key|Auth[_-]?Token|Access[_-]?Token|Functions-Key|FM-Data-Session-Token)"
    r"\s*:\s*\\?[\"']?\s*(" + _VAL + ")",
    re.I,
)
_APIM_HEADER_RE = re.compile(r"Ocp-Apim-Subscription-Key\s*:\s*\\?[\"']?\s*(" + _VAL + ")", re.I)
_COOKIE_RE = re.compile(r"(?:Set-)?Cookie\s*:\s*([^\"'\\\r\n]+)", re.I)
_CURL_USER_RE = re.compile(r"(?:^|[\s\"'])(?:-u|--user|--proxy-user)\s+\\?[\"']?[^\s\"'\\:;]+:([^\s\"'\\;]+)")

# scheme://user:password@host, any scheme (https, sftp, jdbc:mysql, mongodb+srv ...).
_USERINFO_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@\"'\\]+:([^/\s@\"'\\]+)@")
# Query parameters whose name marks the value as a credential. key= and code= are
# deliberately broad: over-redacting is the right failure direction here.
_QUERY_RE = re.compile(
    r"[?&](api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|id[_-]?token|token|key"
    r"|secret|client[_-]?secret|password|pwd|passwd|sig|signature|sas|code|phpsessid|jsessionid"
    r"|session[_-]?id)=([^&\s\"'\\<>#]+)",
    re.I,
)
# Connection-string attributes: Password=...; Pwd=...; AccountKey=...; SharedAccessSignature=...
_CONN_RE = re.compile(
    r"(?<![\w$])(password|pwd|accountkey|sharedaccesssignature|accesstoken|authenticationtoken)"
    r"\s*=\s*([^;,\"'\s&\\]+)",
    re.I,
)


@lru_cache(maxsize=8)
def _json_res(keyword_alt: str) -> tuple[re.Pattern, re.Pattern]:
    key = r"[\w.-]*(?:" + keyword_alt + r")[\w.-]*"
    # Escaped form inside a FileMaker string: \"password\":\"x\" (Insert from URL --data bodies).
    escaped = re.compile(r'\\"(' + key + r')\\"[ \t]*:[ \t]*\\"((?:[^"\\]|\\[^"])*)\\"', re.I)
    # Plain form in comments and non-calc text: "password":"x"
    plain = re.compile(r'"(' + key + r')"[ \t]*:[ \t]*"((?:[^"\\]|\\.)*)"', re.I)
    return escaped, plain


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    if ":" in text or "=" in text:
        if '"' in text:
            for pattern in _json_res(policy.keyword_alt):
                yield from regex_hits(
                    pattern, text, lambda m: category_from_name(m.group(1)), "json_credential", 20, group=2,
                    accept=lambda m: policy.is_credential_name(m.group(1)),
                )
        yield from regex_hits(_AUTH_HEADER_RE, text, "token", "authorization_header", 30, group=1)
        yield from regex_hits(_KEY_HEADER_RE, text, "api_key", "api_key_header", 30, group=1)
        yield from regex_hits(_APIM_HEADER_RE, text, "api_key", "api_key_header", 30, group=1)
        yield from regex_hits(_COOKIE_RE, text, "token", "cookie_header", 30, group=1)
        yield from regex_hits(_CURL_USER_RE, text, "password", "curl_user", 30, group=1)
        yield from regex_hits(_USERINFO_RE, text, "password", "url_userinfo", 30, group=1)
        yield from regex_hits(
            _QUERY_RE, text, lambda m: category_from_name(m.group(1)), "url_query_secret", 30, group=2,
        )
        yield from regex_hits(
            _CONN_RE, text, lambda m: "secret" if m.group(1).lower().startswith(("account", "shared")) else category_from_name(m.group(1)),
            "connection_string", 30, group=2,
        )
