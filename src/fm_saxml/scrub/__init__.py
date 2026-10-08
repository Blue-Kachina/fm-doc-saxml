"""Secret and personal-data scrubbing for everything fm-saxml writes.

Credentials, tokens, internal hostnames and personal data found in a FileMaker
export are replaced with numbered placeholders (``[REDACTED:api_key#1]``,
``[HOST#1]``, ``[EMAIL#1]``) before any output is produced, and a guard checks
the written files afterwards. See ``secret-redaction.md`` for the design.

Detection rules are adapted from the FileMaker XML Scrubber by Andrew Kear,
Clockwork Creative Technology (https://github.com/andykear/FileMaker-XML-scrubber,
v1.4), used under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

This is a heuristic scrubber, not a guarantee. Review output before sharing it.
"""

from .engine import ENGINE_VERSION, Scrubber
from .guard import Leak, guard_output
from .placeholders import PLACEHOLDER_RE, PlaceholderRegistry
from .policy import ScrubLevel, ScrubPolicy

__all__ = [
    "ENGINE_VERSION",
    "Leak",
    "PLACEHOLDER_RE",
    "PlaceholderRegistry",
    "ScrubLevel",
    "ScrubPolicy",
    "Scrubber",
    "guard_output",
]
