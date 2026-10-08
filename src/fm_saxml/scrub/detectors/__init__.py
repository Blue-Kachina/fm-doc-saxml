"""Value detectors. Each returns ``Hit`` spans over the text it is given.

Detectors only *find* values; the engine decides which hits win when they
overlap, maps values to placeholders and rewrites the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from ..policy import ScrubPolicy


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    category: str
    detector: str
    # Lower wins when two hits overlap: a known key shape beats a generic header rule.
    priority: int
    # Flag for manual review instead of redacting (weak evidence, e.g. prose in a comment).
    flag: bool = False


Detector = Callable[[str, ScrubPolicy], Iterable[Hit]]


def regex_hits(
    pattern: re.Pattern,
    text: str,
    category: str | Callable[[re.Match], str],
    detector: str,
    priority: int,
    group: int | str = 0,
    accept: Callable[[re.Match], bool] | None = None,
) -> Iterable[Hit]:
    for m in pattern.finditer(text):
        start, end = m.span(group)
        if start < 0 or start == end:
            continue
        if accept is not None and not accept(m):
            continue
        cat = category(m) if callable(category) else category
        yield Hit(start, end, cat, detector, priority)


def all_detectors(policy: ScrubPolicy) -> list[Detector]:
    """Text detectors enabled at ``policy.level``, in no particular order."""
    from . import comments, credentials, encoded, hosts, known_keys, pii

    found: list[Detector] = [
        known_keys.detect,
        credentials.detect,
        encoded.detect,
        comments.detect,
    ]
    if policy.standard:
        found += [hosts.detect, pii.detect]
    return found
