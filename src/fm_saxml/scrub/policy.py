"""Scrubbing levels, keyword lists and the compiled policy detectors run against."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ScrubLevel(str, Enum):
    SECRETS = "secrets"    # credentials, keys, tokens only
    STANDARD = "standard"  # + internal hosts, home-dir usernames, emails, card numbers
    STRICT = "strict"      # + high-entropy literals, account and modified-by names


# Credential keywords: a name containing one of these marks its value as a secret.
# Adapted from the FileMaker XML Scrubber (Andrew Kear, CC BY 4.0).
DEFAULT_KEYWORDS = (
    r"api[_-]?key", r"apikey", r"token", r"bearer", r"authorization",
    r"password", r"passwd", r"pwd", r"secret", r"smtp[_-]?pass", r"smtp[_-]?key",
    r"private[_-]?key", r"auth[_-]?key", r"ssh[_-]?key", r"sftp[_-]?pass",
    r"passphrase", r"credential", r"oauth",
)

# A credential-looking name that ends in one of these describes the secret
# rather than holding it: $tokenUrl, "token_type", $passwordHint.
NON_SECRET_SUFFIXES = (
    "url", "uri", "endpoint", "host", "name", "label", "field", "type", "expires",
    "expiry", "expiration", "length", "len", "count", "prompt", "hint", "policy",
    "format", "mode", "status", "id", "scope", "redirect", "callback", "provider", "server",
    "file", "folder", "date", "time", "timeout", "interval", "flag", "enabled", "required",
    "message", "error", "title", "description", "note", "version",
)
# FileMaker naming conventions tack short type/scope tags onto names: tokenUri_g, apiKey_t.
_FM_TAG_RE = re.compile(r"_[a-z]{1,3}$")

CREDENTIAL_CATEGORIES = frozenset({"api_key", "token", "password", "secret", "credential", "oauth", "smtp", "license"})


def category_from_name(name: str) -> str:
    n = name.lower()
    if re.search(r"api[_-]?key|apikey", n):
        return "api_key"
    if re.search(r"token|bearer|authorization", n):
        return "token"
    if re.search(r"password|passwd|pwd", n):
        return "password"
    if "secret" in n:
        return "secret"
    if "smtp" in n:
        return "smtp"
    if "oauth" in n:
        return "oauth"
    return "credential"


@dataclass
class ScrubPolicy:
    level: ScrubLevel = ScrubLevel.STANDARD
    extra_keywords: list[str] = field(default_factory=list)
    allow_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.level = ScrubLevel(self.level)
        parts = list(DEFAULT_KEYWORDS) + [re.escape(k) for k in self.extra_keywords if k.strip()]
        self.keyword_alt = "|".join(parts)
        self.keyword_re = re.compile(f"(?:{self.keyword_alt})", re.I)
        self._suffix_re = re.compile(
            r"(?:^|[_.\-])(?:" + "|".join(NON_SECRET_SUFFIXES) + r")$"
            r"|(?<=[a-z0-9])(?:" + "|".join(s.capitalize() for s in NON_SECRET_SUFFIXES) + r")$"
        )
        try:
            self.allow_res = [re.compile(p) for p in self.allow_patterns]
        except re.error as exc:
            raise ValueError(f"Invalid --scrub-allow pattern: {exc}") from exc

    @property
    def standard(self) -> bool:
        return self.level in (ScrubLevel.STANDARD, ScrubLevel.STRICT)

    @property
    def strict(self) -> bool:
        return self.level is ScrubLevel.STRICT

    def is_credential_name(self, name: str) -> bool:
        """True for ``$apiKey``, ``smtp_password``; False for ``$tokenUrl``, ``token_type``."""
        bare = name.lstrip("$~").strip()
        if not bare or not self.keyword_re.search(bare):
            return False
        untagged = _FM_TAG_RE.sub("", bare)
        return not (self._suffix_re.search(bare) or self._suffix_re.search(untagged))

    def is_allowed(self, value: str) -> bool:
        return any(r.fullmatch(value) for r in self.allow_res)
