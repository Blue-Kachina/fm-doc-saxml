"""Find every string in a model and decide how to scrub it.

Works on both shapes the pipeline produces: the parser's ``RawModel`` dicts
(snake_case keys) and a saved ``model.json`` (camelCase aliases). Every string
is one of:

* ``calc``: calculation text. Only string literals and comments may change.
* ``text``: free text (comments, descriptions, value list values, paths).
* ``person``: account and modified-by names, scrubbed at the strict level only.
* skipped: identifiers, names and enums. Schema names are what the
  documentation is about, and references are resolved by them.

Unknown keys default to ``text``: a new extractor field gets scanned, not leaked.

Script step strings also carry a ``StepCtx`` (which script, which step, which
parameter) so structural rules can tell a Re-Login password from any other calc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from .placeholders import PLACEHOLDER_RE

_CALC_KEYS = {"calculation", "install_condition", "formula"}

_SKIP_KEYS = {
    "name", "table", "type", "kind", "role", "parameter", "slot", "event", "part", "operator",
    "theme", "group", "via_to", "data_source", "repetition", "timestamp", "confidence",
    "file_name", "fmp_file_name", "solution_name", "filemaker_version", "file_maker_version",
    "parameters", "scope", "schema_version", "enabled", "label", "title", "href", "variable",
}
_SKIP_SUFFIX_RE = re.compile(
    r"(?:^|_)(?:id|ids|uuid|hash|index|name|names|type|kind|path|at|version|count|table|tables|scope)$"
)
# Keys whose whole subtree is identifiers / bookkeeping.
_SKIP_SUBTREES = {"references", "backlinks", "scrubbing", "field_refs", "layout_ref", "script_ref",
                  "value_list_refs", "referenced_fields", "privilege_set_refs", "storage"}
_PERSON_KEYS = {"user_name", "account_name"}
_STEP_COLLECTIONS = ("steps", "script_steps", "button_step")

_ENTITY_LABELS = {
    "tables": "Table", "fields": "Field", "table_occurrences": "Table occurrence",
    "relationships": "Relationship", "layouts": "Layout", "layout_objects": "Layout object",
    "scripts": "Script", "steps": "Step", "script_steps": "Script step",
    "custom_functions": "Custom function", "value_lists": "Value list",
    "privilege_sets": "Privilege set", "accounts": "Account",
    "extended_privileges": "Extended privilege", "custom_menus": "Custom menu",
    "custom_menu_sets": "Custom menu set", "themes": "Theme",
    "file_references": "File reference", "external_data_sources": "External data source",
    "button_step": "Button step",
}

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STEP_TEXT_WIDTH = 80  # the parser's raw_text preview: f"{name} [ {calc[:80]} ]"


def snake(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


@dataclass
class StepCtx:
    """Where a script-step string sits: enough for structural rules and variable tracing."""

    step: dict
    script_key: Any          # groups the steps of one script
    location: str
    calc: Optional[dict] = None  # the calculations[] entry, for per-parameter calc slots

    def _get(self, name: str, default: Any = None) -> Any:
        key = _key(self.step, name)
        return self.step.get(key, default) if key else default

    @property
    def step_id(self) -> str:
        return str(self._get("step_type_id") or self._get("step_id") or "")

    @property
    def name(self) -> str:
        return self._get("name") or ""

    @property
    def index(self) -> int:
        try:
            return int(self._get("index", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def variable(self) -> Optional[str]:
        params = self._get("parameters")
        return self._get("variable") or (params.get("variable") if isinstance(params, dict) else None)

    @property
    def target_field(self) -> Optional[str]:
        refs = self._get("field_refs") or []
        return refs[0].get("name") if refs and isinstance(refs[0], dict) else None

    @property
    def calcs(self) -> list[dict]:
        return [c for c in (self._get("calculations") or []) if isinstance(c, dict)]


@dataclass
class Slot:
    container: Any  # dict or list
    key: Any        # dict key or list index
    kind: str
    location: str
    ctx: Optional[StepCtx] = None

    def get(self) -> str:
        return self.container[self.key]

    def set(self, value: str) -> None:
        self.container[self.key] = value


@dataclass
class StepText:
    """A step whose joined calculation / raw_text preview were derived from its per-parameter
    calcs. They are re-derived after scrubbing rather than scrubbed on their own, so a value
    redacted in one parameter can't survive in the copies."""

    step: dict
    name_key: str
    calcs_key: Optional[str]
    calc_key: Optional[str]   # set when the joined `calculation` is derived
    raw_key: Optional[str]    # set when `raw_text` is derived


@dataclass
class Walk:
    slots: list[Slot] = field(default_factory=list)
    step_texts: list[StepText] = field(default_factory=list)
    steps: list[StepCtx] = field(default_factory=list)


def collect_slots(roots: dict[str, Any]) -> Walk:
    walk = Walk()
    for key, value in roots.items():
        if isinstance(value, (dict, list)):
            _walk(value, snake(key), [], walk, None, None)
    return walk


def rebuild_step_texts(step_texts: list[StepText]) -> None:
    for st in step_texts:
        joined = _joined(st.step, st.calcs_key)
        if st.calc_key:
            st.step[st.calc_key] = joined
        if st.raw_key:
            calc = (st.step.get(st.calc_key) if st.calc_key else None) or joined or ""
            st.step[st.raw_key] = f"{st.step.get(st.name_key, '')} [ {_truncate(calc)} ]"


def _joined(step: dict, calcs_key: Optional[str]) -> Optional[str]:
    calcs = step.get(calcs_key) if calcs_key else None
    if not isinstance(calcs, list):
        return None
    return "\n".join(c.get("text", "") for c in calcs if isinstance(c, dict)) or None


def _truncate(calc: str) -> str:
    cut = _STEP_TEXT_WIDTH
    # Never cut a placeholder in half.
    for m in PLACEHOLDER_RE.finditer(calc, 0, cut + 40):
        if m.start() < cut < m.end():
            cut = m.end()
    return calc[:cut]


def _key(d: dict, name: str) -> str | None:
    """The actual key for a snake_case name in either key style."""
    if name in d:
        return name
    parts = name.split("_")
    camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
    return camel if camel in d else None


def _label(collection: str, item: dict) -> str | None:
    title = _ENTITY_LABELS.get(collection)
    if not title:
        return None
    name = item.get("name") or ""
    if collection in _STEP_COLLECTIONS:
        # `index` is 0-based; FileMaker and our script pages number steps from 1.
        try:
            return f"{title} {int(item.get('index')) + 1}: {name}"
        except (TypeError, ValueError):
            return f"{title}: {name}"
    if collection == "fields":
        table = item.get("table_name") or item.get("tableName") or ""
        return f"Field {table}::{name}" if table else f"Field {name}"
    return f"{title} '{name}'" if name else title


def _classify(key: str, collection: str | None, step_like: bool) -> str | None:
    if key in _CALC_KEYS:
        return "calc"
    if key == "text" and collection == "calculations":
        return "calc"
    if key == "raw_text":
        return "calc" if step_like else "text"
    if key in _SKIP_KEYS or _SKIP_SUFFIX_RE.search(key):
        return None
    return "text"


def _step_texts(obj: dict) -> Optional[StepText]:
    """Record which of a step's joined copies were derived from its per-parameter calcs."""
    name_key, calcs_key = _key(obj, "name"), _key(obj, "calculations")
    calc_key, raw_key = _key(obj, "calculation"), _key(obj, "raw_text")
    if not name_key or not calcs_key:
        return None
    joined = _joined(obj, calcs_key)
    if not joined:
        return None
    derived_calc = calc_key if calc_key and obj.get(calc_key) == joined else None
    basis = obj.get(calc_key) if calc_key else joined
    derived_raw = raw_key if (
        raw_key and isinstance(basis, str) and obj.get(raw_key) == f"{obj[name_key]} [ {basis[:_STEP_TEXT_WIDTH]} ]"
    ) else None
    if calc_key and not derived_calc:
        derived_raw = None  # raw_text came from a calculation we scrub on its own
    if not derived_calc and not derived_raw:
        return None
    return StepText(obj, name_key, calcs_key, derived_calc, derived_raw)


def _walk(obj: Any, collection: str | None, loc: list[str], walk: Walk, parent_key: str | None,
          ctx: Optional[StepCtx], script_key: Any = None) -> None:
    where = " › ".join(loc)
    if isinstance(obj, list):
        if collection == "steps":
            script_key = id(obj)  # parser shape: a script's steps share one list
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if collection and collection not in _SKIP_KEYS and not _SKIP_SUFFIX_RE.search(collection):
                    walk.slots.append(Slot(obj, i, "text", where, ctx))
            elif isinstance(item, dict):
                label = _label(collection or "", item)
                item_ctx = replace(ctx, calc=item) if ctx is not None and collection == "calculations" else ctx
                _walk(item, collection, loc + [label] if label else loc, walk, collection, item_ctx, script_key)
            elif isinstance(item, list):
                _walk(item, collection, loc, walk, collection, ctx, script_key)
        return
    if not isinstance(obj, dict):
        return

    step_like = _key(obj, "step_type_id") is not None or collection in _STEP_COLLECTIONS
    derived: set[str] = set()
    if step_like and collection != "calculations":
        # model.json steps are grouped by scriptDocId; parser steps by their shared list.
        key = obj.get("scriptDocId") or obj.get("script_doc_id") or script_key or id(obj)
        ctx = StepCtx(obj, key, where)
        walk.steps.append(ctx)
        st = _step_texts(obj)
        if st:
            walk.step_texts.append(st)
            derived = {k for k in (st.calc_key, st.raw_key) if k}

    for k, v in obj.items():
        sk = snake(k)
        if isinstance(v, str):
            if k in derived:
                continue
            if collection == "accounts" and sk == "name" and parent_key == "accounts":
                walk.slots.append(Slot(obj, k, "person", where))
                continue
            kind = _classify(sk, collection, step_like)
            if kind:
                walk.slots.append(Slot(obj, k, kind, where, ctx))
        elif isinstance(v, dict):
            if sk in _SKIP_SUBTREES or sk == "parameters":
                continue
            if sk == "modified":
                for mk, mv in v.items():
                    if isinstance(mv, str) and snake(mk) in _PERSON_KEYS:
                        walk.slots.append(Slot(v, mk, "person", where))
                continue
            if sk in _ENTITY_LABELS and sk != "button_step" and v and all(isinstance(e, dict) for e in v.values()):
                # model.json entity map: {docId: entity}
                for e in v.values():
                    label = _label(sk, e)
                    _walk(e, sk, loc + [label] if label else loc, walk, sk, None)
                continue
            label = _label(sk, v) if sk == "button_step" else None
            child_ctx = None if sk == "button_step" else ctx
            _walk(v, sk, loc + [label] if label else loc, walk, sk, child_ctx, script_key)
        elif isinstance(v, list):
            if sk in _SKIP_SUBTREES:
                continue
            _walk(v, sk, loc, walk, sk, ctx, script_key)
