"""Provider key and token shapes. Near-zero false positives, so they apply everywhere.

Shapes adapted from the FileMaker XML Scrubber (Andrew Kear, CC BY 4.0), with
extra providers and a leading boundary so ``task-management-…`` isn't read as
an ``sk-`` key.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..policy import ScrubPolicy
from . import Hit

# A key starts at a boundary: not glued to the end of a longer identifier.
_B = r"(?<![A-Za-z0-9_\-])"
# OttoFMS keys look like ordinary identifiers (dk_..., ak_...), so require a digit and a letter.
_MIXED = r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])"

# (detector id, pattern, capture group holding the secret)
KNOWN_KEYS: tuple[tuple[str, str, int], ...] = (
    ("openai", _B + r"sk-proj-[\w-]{10,}", 0),
    ("openai", _B + r"sk-(?:ant-)?[\w-]{20,}", 0),          # also Anthropic sk-ant-
    ("google_api_key", _B + r"AIza[\w-]{30,}", 0),
    ("google_oauth_secret", _B + r"GOCSPX-[\w-]{20,}", 0),
    ("xai", _B + r"xai-[\w-]{10,}", 0),
    ("groq", _B + r"gsk_[A-Za-z0-9]{20,}", 0),
    ("aws_access_key_id", _B + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])", 0),
    ("github", _B + r"gh[pousr]_[A-Za-z0-9]{20,}", 0),
    ("github", _B + r"github_pat_[A-Za-z0-9_]{20,}", 0),
    ("gitlab", _B + r"glpat-[\w-]{20,}", 0),
    ("slack", _B + r"xox[abprs]-[A-Za-z0-9-]{10,}", 0),
    ("slack", _B + r"xapp-[A-Za-z0-9-]{10,}", 0),
    ("stripe", _B + r"[sr]k_(?:live|test)_[A-Za-z0-9]{20,}", 0),
    ("sendgrid", _B + r"SG\.[\w-]{16,}\.[\w-]{16,}", 0),
    ("ottofms", _B + r"(?:dk|ak)_" + _MIXED + r"[A-Za-z0-9]{10,}", 0),
    ("huggingface", _B + r"hf_[A-Za-z0-9]{30,}", 0),
    ("npm", _B + r"npm_[A-Za-z0-9]{36}", 0),
    ("shopify", _B + r"shp(?:at|ss|ca|pa)_[a-fA-F0-9]{32}", 0),
    ("jwt", _B + r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}", 0),
    # Incoming webhooks: the path is the credential, the host stays as context.
    ("slack_webhook", r"hooks\.slack\.com/(services/[A-Za-z0-9/]+)", 1),
    ("discord_webhook", r"discord(?:app)?\.com/api/webhooks/(\d+/[\w-]+)", 1),
    ("teams_webhook", r"\.webhook\.office\.com/([^\s\"'\\<>]+)", 1),
)

_COMPILED = [(det, re.compile(p), g) for det, p, g in KNOWN_KEYS]
_PEM_RE = re.compile(r"-----BEGIN[A-Z0-9 ]*PRIVATE KEY-----")


def has_pem_marker(text: str) -> bool:
    return bool(_PEM_RE.search(text))


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    for det, pattern, group in _COMPILED:
        for m in pattern.finditer(text):
            start, end = m.span(group)
            yield Hit(start, end, "api_key", det, 10)
