"""The scrubber: runs detectors, resolves overlaps, replaces values with placeholders.

Two kinds of string are scrubbed differently:

* **calc** text (formulas, step parameters, custom function bodies) is tokenized
  first, and only the insides of string literals and comments may change, so
  the logic of the calculation survives intact.
* **text** (comments, descriptions, value list values, paths) is scanned whole.

A run over a model happens in two passes. Pass 1 detects and replaces. Pass 2
replaces every *other* occurrence of each value pass 1 found, so a password
detected in a Re-Login step is also gone from the comment that repeats it.
"""

from __future__ import annotations

import bisect
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ..model.document_model import ScrubFinding, ScrubSummary
from .calc_lexer import COMMENT, NAME, OP, STRING, VAR, Token, significant, tokenize
from .detectors import Hit, all_detectors
from .detectors.entropy import looks_random
from .detectors.known_keys import has_pem_marker
from .placeholders import PLACEHOLDER_RE, PlaceholderRegistry
from .policy import CREDENTIAL_CATEGORIES, ScrubPolicy, category_from_name
from .structural import Flag, local_hits, plan
from .walker import Slot, collect_slots, rebuild_step_texts

ENGINE_VERSION = "3"

_PREVIEW_RADIUS = 40
_SCHEME_WORD_RE = re.compile(r"\s*(?:Bearer|Basic|Token|Digest|OAuth)?\s*", re.I)
_REFERENCE_RE = re.compile(r"\$|::")
ALLOW_MARKER = "fm-saxml:allow"
_ALLOW_RE = re.compile(re.escape(ALLOW_MARKER), re.I)
_NAME_BASED = {"keyword_assignment", "json_credential"}
_VALUE_LIKE_RE = re.compile(r"(?=.*[A-Za-z0-9]).{4,}", re.S)
_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}")


@dataclass
class _Pending:
    """A finding whose preview is taken from the slot's *final* text, after both passes."""

    category: str
    detector: str
    location: str
    placeholder: str
    slot: Optional[Slot]
    preview: str = ""
    action: str = "redacted"
    note: str = ""


class Scrubber:
    def __init__(self, policy: ScrubPolicy | None = None, registry: PlaceholderRegistry | None = None) -> None:
        self.policy = policy or ScrubPolicy()
        # Not `registry or ...`: an empty registry is falsy (it has a __len__).
        self.registry = registry if registry is not None else PlaceholderRegistry()
        self._detectors = all_detectors(self.policy)
        self._pending: list[_Pending] = []
        self._sub_cache: tuple[int, Optional[re.Pattern]] = (-1, None)
        self._allowed_values: set[str] = set()
        self.last_changes: list[tuple[str, str, str]] = []

    # ------------------------------------------------------------------
    # Public, single-string API
    # ------------------------------------------------------------------

    def scrub_text(self, text: str, location: str = "") -> str:
        return self._scrub_text(text, location, None)

    def scrub_calc(self, text: str, location: str = "") -> str:
        return self._scrub_calc(text, location, None)

    # ------------------------------------------------------------------
    # Whole-model runs
    # ------------------------------------------------------------------

    def scrub_raw(self, raw: Any) -> ScrubSummary:
        """Scrub a parser ``RawModel`` in place, before normalization copies its strings around."""
        roots = {name: getattr(raw, name) for name in raw.__dataclass_fields__}
        return self._run(roots)

    def scrub_model_data(self, data: dict) -> ScrubSummary:
        """Scrub a ``model.json`` dict in place (a model saved unscrubbed, or by an older engine)."""
        roots = {k: v for k, v in data.items() if k != "scrubbing"}
        source = data.get("source")
        if isinstance(source, dict) and isinstance(source.get("fileName"), str):
            source["fileName"] = self.scrub_text(source["fileName"], "Source file")
        summary = self._run(roots)
        data["scrubbing"] = summary.model_dump(by_alias=True, mode="json")
        return summary

    def summary(self, findings: list[ScrubFinding]) -> ScrubSummary:
        counts = Counter()
        for ph, cat in {(f.placeholder, f.category) for f in findings if f.action == "redacted"}:
            counts[cat] += 1
        return ScrubSummary(
            applied=True, level=self.policy.level.value, engineVersion=ENGINE_VERSION,
            placeholderStyle=self.registry.style, saltId=self.registry.salt_id,
            counts=dict(sorted(counts.items())), findings=findings,
        )

    def guard_values(self) -> dict[str, str]:
        return self.registry.substitutable_values()

    def _run(self, roots: dict[str, Any]) -> ScrubSummary:
        # Findings recorded since the last run (e.g. the source path) belong to this one.
        walk = collect_slots(roots)
        originals = [slot.get() for slot in walk.slots]
        # Structural rules and variable tracing, planned on the original texts.
        structure = plan(walk, self.policy)

        # A calc or text marked "fm-saxml:allow" is left exactly as it is, and what it
        # contains is allowed everywhere, so the same value isn't redacted next door.
        allowed = {id(s) for s in walk.slots if _allow_marked(s)}
        for slot in walk.slots:
            if id(slot) in allowed:
                self._allow_slot(slot, structure.hits.get(id(slot), []))
        slots = [s for s in walk.slots if id(s) not in allowed]
        for flag in structure.flags:
            if flag.slot is None or id(flag.slot) not in allowed:
                self._record_flag(flag)

        for slot in slots:
            value = slot.get()
            if not value:
                continue
            if slot.kind == "calc":
                new = self._scrub_calc(value, slot.location, slot, structure.hits.get(id(slot), []))
            elif slot.kind == "person":
                new = self._scrub_person(value, slot.location, slot)
            else:
                new = self._scrub_text(value, slot.location, slot)
            if new != value:
                slot.set(new)

        sub_re = self._substitution_re()
        if sub_re is not None:
            for slot in slots:
                value = slot.get()
                if not value:
                    continue
                spans = self._editable_spans(value) if slot.kind == "calc" else [(0, len(value))]
                hits = [h for h in self._known_value_hits(sub_re, value) if _inside(h, spans)]
                if hits:
                    slot.set(self._apply(value, hits, slot.location, slot))

        rebuild_step_texts(walk.step_texts)
        # What changed, by original text: lets the XML writer apply the same edits to the source file.
        self.last_changes = [
            (slot.kind, old, slot.get()) for slot, old in zip(walk.slots, originals) if slot.get() != old
        ]
        return self.summary(self._finalize())

    def _allow_slot(self, slot: Slot, structural: list[Hit]) -> None:
        """Record the marker, and allow every value a scrub of this slot would have redacted."""
        value = slot.get() or ""
        sandbox = Scrubber(self.policy)
        if slot.kind == "calc":
            sandbox._scrub_calc(value, "", None, structural)
        else:
            sandbox._scrub_text(value, "", None)
        self._allowed_values.update(sandbox.registry.values())
        self._pending.append(_Pending(
            "allowed", "allow_marker", slot.location, "", None, action="allowed",
            note=f"Marked {ALLOW_MARKER}: left unchanged" + (
                f", and {len(sandbox.registry)} value(s) in it are allowed everywhere." if len(sandbox.registry) else "."),
        ))

    def _record_flag(self, flag: Flag) -> None:
        location = flag.slot.location if flag.slot is not None else ""
        self._pending.append(_Pending(flag.category, flag.detector, location, "", None,
                                      action="flagged", note=flag.note))

    # ------------------------------------------------------------------
    # Scrubbing one string
    # ------------------------------------------------------------------

    def _scrub_text(self, text: str, location: str, slot: Optional[Slot]) -> str:
        if not text or len(text) < 6:
            return text
        return self._apply(text, self._text_hits(text), location, slot)

    def _scrub_calc(self, text: str, location: str, slot: Optional[Slot],
                    structural: Optional[list[Hit]] = None) -> str:
        """``structural`` comes from the run's plan; standalone calls resolve positional
        arguments within the calc instead (no script context to trace through)."""
        # Secrets only live inside string literals and comments.
        if not text or ('"' not in text and "/" not in text):
            return text
        tokens = tokenize(text)
        editable = [t for t in tokens if t.kind in (STRING, COMMENT)]
        if not editable:
            return text
        spans = [t.content_span for t in editable]

        hits = [h for h in self._text_hits(text) if _inside(h, spans)]
        hits += structural if structural is not None else local_hits(text, self.policy)
        hits += self._assignment_hits(tokens, text, 0)
        for tok in editable:
            if tok.kind == COMMENT:
                # Commented-out code still carries real secrets: $apikey = "..." inside /* */.
                start, end = tok.content_span
                hits += self._assignment_hits(tokenize(text[start:end]), text[start:end], start)

        strings = [t for t in editable if t.kind == STRING]
        if has_pem_marker(text):
            # A key-handling calc: the base64 body has no shape of its own and is
            # often split across concatenated literals, so every literal goes.
            hits += [Hit(*t.content_span, "secret", "private_key", 5) for t in strings if _has_content(text, t)]
        if self.policy.strict:
            for t in strings:
                start, end = t.content_span
                if looks_random(text[start:end]):
                    hits.append(Hit(start, end, "secret", "high_entropy", 50))

        return self._apply(text, hits, location, slot)

    def _scrub_person(self, text: str, location: str, slot: Optional[Slot]) -> str:
        bare = text.strip()
        # [Guest], [Full Access] and directory-group UUIDs are not people.
        if not self.policy.strict or not bare or (bare.startswith("[") and bare.endswith("]")) or _UUID_RE.fullmatch(bare):
            return text
        return self._apply(text, [Hit(0, len(text), "person", "person_name", 80)], location, slot)

    def _text_hits(self, text: str) -> list[Hit]:
        hits: list[Hit] = []
        for detect in self._detectors:
            hits.extend(detect(text, self.policy))
        return hits

    def _assignment_hits(self, tokens: list[Token], text: str, offset: int) -> list[Hit]:
        """``$apiKey = "..."`` and Let() locals ``smtp_password = "..."``."""
        hits = []
        sig = significant(tokens)
        for i in range(2, len(sig)):
            tok, eq, name = sig[i], sig[i - 1], sig[i - 2]
            if tok.kind != STRING or eq.kind != OP or eq.text != "=" or name.kind not in (VAR, NAME):
                continue
            if not self.policy.is_credential_name(name.text):
                continue
            start, end = tok.content_span
            if _SCHEME_WORD_RE.fullmatch(text[start:end]):
                continue
            hits.append(Hit(start + offset, end + offset, category_from_name(name.text), "keyword_assignment", 20))
        return hits

    def _apply(self, text: str, hits: Iterable[Hit], location: str, slot: Optional[Slot]) -> str:
        hits = list(hits)
        if not hits:
            return text
        taken = [m.span() for m in PLACEHOLDER_RE.finditer(text)]
        accepted: list[Hit] = []
        flags = [h for h in hits if h.flag]
        hits = [h for h in hits if not h.flag]
        for h in sorted(hits, key=lambda h: (h.priority, h.start - h.end, h.start)):
            value = text[h.start:h.end]
            if not value.strip() or any(h.start < e and s < h.end for s, e in taken):
                continue
            if self.policy.is_allowed(value) or value in self._allowed_values:
                continue
            # A reference ($token, Users::Password) is where the secret is used, not the secret.
            if h.category in CREDENTIAL_CATEGORIES and h.detector != "known_value" and _REFERENCE_RE.match(value.strip()):
                continue
            # Name-based rules: $searchToken = "¶" is a delimiter, not a credential.
            if h.detector in _NAME_BASED and not _VALUE_LIKE_RE.search(value):
                continue
            accepted.append(h)
            taken.append((h.start, h.end))

        # Weak evidence is reported, never applied, and only where nothing was redacted.
        for h in flags:
            value = text[h.start:h.end]
            if any(h.start < e and s < h.end for s, e in taken) or self.policy.is_allowed(value):
                continue
            masked = text[:h.start] + "••••" + text[h.end:]
            self._pending.append(_Pending(
                h.category, h.detector, location, "", None, preview=_preview(masked, h.start, h.start + 4),
                action="flagged", note="Reads like a credential written in prose. Left unchanged: check it by hand.",
            ))
        if not accepted:
            return text

        accepted.sort(key=lambda h: h.start)
        out, pos, marks = [], 0, []
        length = 0
        for h in accepted:
            value = text[h.start:h.end]
            category = self.registry.category_of(value) if h.detector == "known_value" else h.category
            ph = self.registry.placeholder(value, category)
            out.append(text[pos:h.start])
            length += h.start - pos
            marks.append((length, category, h.detector, ph))
            out.append(ph)
            length += len(ph)
            pos = h.end
        out.append(text[pos:])
        new = "".join(out)

        for at, category, detector, ph in marks:
            pending = _Pending(category, detector, location, ph, slot)
            if slot is None:
                pending.preview = _preview(new, at, at + len(ph))
            self._pending.append(pending)
        return new

    # ------------------------------------------------------------------
    # Pass 2: every other occurrence of a known value
    # ------------------------------------------------------------------

    def _substitution_re(self) -> Optional[re.Pattern]:
        if self._sub_cache[0] == len(self.registry):
            return self._sub_cache[1]
        values = sorted(self.registry.substitutable_values(), key=len, reverse=True)
        pattern = None
        if values:
            alt = "|".join(re.escape(v) for v in values)
            pattern = re.compile(f"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])")
        self._sub_cache = (len(self.registry), pattern)
        return pattern

    def _known_value_hits(self, pattern: re.Pattern, text: str) -> list[Hit]:
        return [Hit(m.start(), m.end(), "credential", "known_value", 0) for m in pattern.finditer(text)]

    def substitute(self, text: str) -> str:
        """Replace already-known values in free text (previews, report lines), recording nothing."""
        pattern = self._substitution_re()
        if pattern is None or not text:
            return text
        pieces, pos = [], 0
        for m in PLACEHOLDER_RE.finditer(text):
            pieces.append(pattern.sub(lambda v: self.registry.placeholder(v.group(), ""), text[pos:m.start()]))
            pieces.append(m.group())
            pos = m.end()
        pieces.append(pattern.sub(lambda v: self.registry.placeholder(v.group(), ""), text[pos:]))
        return "".join(pieces)

    def substitute_calc(self, text: str) -> str:
        """``substitute`` for calc text: only inside string literals and comments."""
        pattern = self._substitution_re()
        if pattern is None or not text:
            return text
        spans = self._editable_spans(text)
        hits = [m for m in pattern.finditer(text)
                if _inside(Hit(m.start(), m.end(), "", "", 0), spans)
                and not any(p.start() < m.end() and m.start() < p.end() for p in PLACEHOLDER_RE.finditer(text))]
        for m in reversed(hits):
            text = text[:m.start()] + self.registry.placeholder(m.group(), "") + text[m.end():]
        return text

    @staticmethod
    def _editable_spans(text: str) -> list[tuple[int, int]]:
        if '"' not in text and "/" not in text:
            return []
        return [t.content_span for t in tokenize(text) if t.kind in (STRING, COMMENT)]

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def _finalize(self) -> list[ScrubFinding]:
        seen = set()
        findings = []
        for p in self._pending:
            location = self.substitute(p.location)
            preview = p.preview
            if p.slot is not None and p.placeholder:
                final = p.slot.get() or ""
                at = final.find(p.placeholder)
                preview = _preview(final, at, at + len(p.placeholder)) if at >= 0 else ""
            preview = self.substitute(preview)
            # The same value in a field's calculation and calculations[].text, or the same
            # flag raised from two copies of a calc, is one finding.
            key = (location, p.placeholder) if p.action == "redacted" else (location, p.action, p.note, preview)
            if key in seen:
                continue
            seen.add(key)
            findings.append(ScrubFinding(
                category=p.category, detector=p.detector, location=location,
                placeholder=p.placeholder, preview=preview, action=p.action, note=self.substitute(p.note),
            ))
        self._pending = []
        return findings


def _allow_marked(slot: Slot) -> bool:
    """A calc whose *comment* says fm-saxml:allow, or a text containing it."""
    value = slot.get()
    if not value or not _ALLOW_RE.search(value):
        return False
    if slot.kind != "calc":
        return True
    return any(t.kind == COMMENT and _ALLOW_RE.search(t.text) for t in tokenize(value))


def _has_content(text: str, tok: Token) -> bool:
    start, end = tok.content_span
    return bool(text[start:end].strip())


def _inside(hit: Hit, spans: list[tuple[int, int]]) -> bool:
    """True when the hit falls entirely inside one editable span (spans are sorted)."""
    if not spans:
        return False
    i = bisect.bisect_right(spans, (hit.start, float("inf"))) - 1
    return i >= 0 and spans[i][0] <= hit.start and hit.end <= spans[i][1]


def _preview(text: str, start: int, end: int) -> str:
    a = max(0, start - _PREVIEW_RADIUS)
    b = min(len(text), end + _PREVIEW_RADIUS)
    # Don't cut a placeholder in half at either edge.
    for m in PLACEHOLDER_RE.finditer(text, max(0, a - 30), min(len(text), b + 30)):
        if m.start() < a < m.end():
            a = m.start()
        if m.start() < b < m.end():
            b = m.end()
    body = " ".join(text[a:b].split())
    return ("…" if a > 0 else "") + body + ("…" if b < len(text) else "")
