"""Structure-aware rules: where a calc sits says it is a credential, whatever it looks like.

* A ``<Parameter type="Password">`` calc (Re-Login, Reset Account Password, Add Account,
  Execute SQL's ODBC password, …).
* Configure AI Account / Configure RAG Account calcs.
* Set Variable into a credential-named variable (``$apiKey``, ``$$SMTP_PASSWORD``).
* Set Field / Insert Calculated Result into a credential-named field (``Users::Password``),
  and Set Field By Name whose target names one.
* Positional credential arguments (see ``positional.py``).

The value is handled by shape: a literal is redacted where it is; a ``$variable`` is
traced back to the Set Variable that assigned it (earlier in the same script, or
anywhere in the file for a ``$$global``) and redacted *there*; a field reference is
flagged, since the secret lives in data rather than in this file.

The plan is computed on the original texts before anything is rewritten, so its hits
can target any slot, not just the one being looked at.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .calc_lexer import NAME, STRING, Token, tokenize
from .detectors import Hit
from .policy import ScrubPolicy, category_from_name
from .positional import Use, _code_tokens, classify, credential_uses, local_assignment
from .walker import Slot, StepCtx, Walk

SET_VARIABLE, SET_FIELD, INSERT_CALCULATED_RESULT, SET_FIELD_BY_NAME = "141", "76", "77", "147"
AI_ACCOUNT_STEPS = {"212", "227"}  # Configure AI Account, Configure RAG Account
_STEP_IDS_BY_NAME = {
    "set variable": SET_VARIABLE, "set field": SET_FIELD,
    "insert calculated result": INSERT_CALCULATED_RESULT, "set field by name": SET_FIELD_BY_NAME,
    "configure ai account": "212", "configure rag account": "227",
}
_PRIORITY = 15  # after known key shapes (10), before generic keyword rules (20)
_MAX_TRACE_DEPTH = 4
_SCHEME_ONLY_RE = re.compile(r"\s*(?:Bearer|Basic|Token|Digest|OAuth)?\s*", re.I)
_FIELD_NAME_RE = re.compile(r"::\s*([^\"&;)\]¶]+)")


@dataclass
class Flag:
    slot: Optional[Slot]
    category: str
    detector: str
    note: str


@dataclass
class Plan:
    hits: dict[int, list[Hit]] = field(default_factory=lambda: defaultdict(list))
    flags: list[Flag] = field(default_factory=list)


def _norm_var(name: Optional[str]) -> str:
    return re.sub(r"\[.*$", "", (name or "")).strip().lower()


def _step_kind(ctx: StepCtx) -> str:
    return ctx.step_id or _STEP_IDS_BY_NAME.get(ctx.name.strip().lower(), "")


def _has_call(tokens: list[Token]) -> bool:
    toks = _code_tokens(tokens)
    return any(a.kind == NAME and b.text == "(" for a, b in zip(toks, toks[1:]))


def _meaningful(content: str) -> bool:
    return any(c.isalnum() for c in content) and not _SCHEME_ONLY_RE.fullmatch(content)


class Planner:
    def __init__(self, walk: Optional[Walk], policy: ScrubPolicy) -> None:
        self.policy = policy
        self.plan = Plan()
        self._tokens: dict[int, list[Token]] = {}
        self.calc_slots: dict[int, Slot] = {}
        self.by_script: dict[object, list[StepCtx]] = defaultdict(list)
        self.globals: dict[str, list[StepCtx]] = defaultdict(list)
        if walk is None:
            return
        for slot in walk.slots:
            if slot.kind == "calc" and slot.ctx is not None and slot.ctx.calc is slot.container:
                self.calc_slots[id(slot.container)] = slot
        for ctx in walk.steps:
            self.by_script[ctx.script_key].append(ctx)
            if _step_kind(ctx) == SET_VARIABLE and _norm_var(ctx.variable).startswith("$$"):
                self.globals[_norm_var(ctx.variable)].append(ctx)
        for steps in self.by_script.values():
            steps.sort(key=lambda c: c.index)

    # ------------------------------------------------------------------

    def run(self, walk: Walk) -> Plan:
        for slot in walk.slots:
            if slot.kind != "calc":
                continue
            per_param = slot.ctx is not None and slot.ctx.calc is slot.container
            if slot.ctx is not None and not per_param:
                continue  # a step's raw_text / joined copies: covered via the per-parameter calcs
            self.analyze(slot, slot.get(), slot.ctx if per_param else None)
        return self.plan

    def analyze(self, slot: Optional[Slot], text: str, ctx: Optional[StepCtx]) -> None:
        if not text:
            return
        tokens = self._tokenize(slot, text)
        for use in credential_uses(tokens, text, self.policy):
            self._resolve(use, slot, ctx, tokens, text, 0)
        if ctx is not None:
            rule = self._structural_rule(ctx)
            if rule:
                category, detector, via = rule
                self._resolve(Use(classify(tokens), _code_tokens(tokens), category, detector, via),
                              slot, ctx, tokens, text, 0)

    def _tokenize(self, slot: Optional[Slot], text: str) -> list[Token]:
        key = id(slot) if slot is not None else 0
        if slot is None or key not in self._tokens:
            self._tokens[key] = tokenize(text)
        return self._tokens[key]

    # ------------------------------------------------------------------

    def _structural_rule(self, ctx: StepCtx) -> Optional[tuple[str, str, str]]:
        calc = ctx.calc or {}
        param = (calc.get("parameter") or "").strip()
        kind = _step_kind(ctx)
        if param.lower() == "password":
            return "password", "password_parameter", f"{ctx.name} password"
        if kind in AI_ACCOUNT_STEPS:
            return "api_key", "ai_account", ctx.name
        if kind == SET_VARIABLE:
            var = ctx.variable
            if var and calc.get("slot") != "repetition" and self.policy.is_credential_name(var):
                return category_from_name(var), "credential_variable", f"Set Variable {var}"
        if kind in (SET_FIELD, INSERT_CALCULATED_RESULT):
            target = ctx.target_field
            if target and param == "Calculation" and self.policy.is_credential_name(target):
                cat = category_from_name(target)
                return (cat if cat != "credential" else "password"), "credential_field", f"{ctx.name} into {target}"
        if kind == SET_FIELD_BY_NAME:
            calcs = [c for c in ctx.calcs if c.get("parameter") == "Calculation"]
            if len(calcs) >= 2 and calc is calcs[-1]:
                names = _FIELD_NAME_RE.findall(calcs[0].get("text", ""))
                hit = next((n.strip() for n in names if self.policy.is_credential_name(n.strip())), None)
                if hit:
                    return category_from_name(hit), "credential_field", f"Set Field By Name into {hit}"
        return None

    def _resolve(self, use: Use, slot: Optional[Slot], ctx: Optional[StepCtx], tokens: list[Token],
                 text: str, depth: int) -> None:
        if use.kind == "literal":
            self._hit_strings(use, slot, text)
        elif use.kind == "expr":
            # "Bearer " & "abc" & "def" is a secret split into pieces; the "password" in
            # JSONGetElement ( $parameter ; "password" ) is a key name, not the secret.
            if not _has_call(use.tokens):
                self._hit_strings(use, slot, text)
        elif use.kind in ("name", "var"):
            name = _code_tokens(use.tokens)[0].text
            local = local_assignment(tokens, name)
            if local is not None:
                self._hit_strings(Use("literal", [local], use.category, use.detector, use.via), slot, text)
            elif use.kind == "var":
                self._trace(name, use, slot, ctx, depth)
        elif use.kind == "field":
            self._flag(slot, use, f"{use.via} reads its value from field {use.ref}. Nothing to redact in this "
                                  "file, but that field holds a credential.")

    def _hit_strings(self, use: Use, slot: Optional[Slot], text: str) -> None:
        for tok in use.tokens:
            if tok.kind != STRING:
                continue
            start, end = tok.content_span
            if _meaningful(text[start:end]):
                key = id(slot) if slot is not None else 0
                self.plan.hits[key].append(Hit(start, end, use.category, use.detector, _PRIORITY))

    def _trace(self, var: str, use: Use, slot: Optional[Slot], ctx: Optional[StepCtx], depth: int) -> None:
        norm = _norm_var(var)
        sources: list[StepCtx] = []
        if ctx is not None:
            earlier = [s for s in self.by_script.get(ctx.script_key, [])
                       if s.index < ctx.index and _step_kind(s) == SET_VARIABLE and _norm_var(s.variable) == norm]
            sources = earlier[-1:]
        if not sources and norm.startswith("$$"):
            sources = self.globals.get(norm, [])
        found = False
        for src in sources:
            vslot = self._value_slot(src)
            if vslot is None or depth >= _MAX_TRACE_DEPTH:
                continue
            found = True
            vtext = vslot.get()
            vtokens = self._tokenize(vslot, vtext)
            traced = Use(classify(vtokens), _code_tokens(vtokens), use.category, f"{use.detector}_traced", use.via)
            self._resolve(traced, vslot, vslot.ctx, vtokens, vtext, depth + 1)
        if not found:
            where = "anywhere in this file" if norm.startswith("$$") else "earlier in this script"
            self._flag(slot, use, f"{var} is passed to {use.via}, but no Set Variable assigning it was found "
                                  f"{where}. It may come from a calling script or a script parameter.")

    def _value_slot(self, ctx: StepCtx) -> Optional[Slot]:
        calcs = ctx.calcs
        chosen = next((c for c in calcs if c.get("parameter") == "Variable" and c.get("slot") == "value"), None)
        if chosen is None:
            chosen = next((c for c in calcs if c.get("slot") != "repetition"), None)
        return self.calc_slots.get(id(chosen)) if chosen is not None else None

    def _flag(self, slot: Optional[Slot], use: Use, note: str) -> None:
        self.plan.flags.append(Flag(slot, use.category, use.detector, note))


def plan(walk: Walk, policy: ScrubPolicy) -> Plan:
    return Planner(walk, policy).run(walk)


def local_hits(text: str, policy: ScrubPolicy) -> list[Hit]:
    """Positional hits resolvable within one calc (no script context, no flags)."""
    planner = Planner(None, policy)
    planner.analyze(None, text, None)
    return planner.plan.hits.get(0, [])
