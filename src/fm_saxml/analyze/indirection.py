"""Find and resolve indirection: places that name a field, script, layout, ... in a string.

Pipeline position: the last step of ``resolve_references`` (it needs the catalogs, the
variables index and the direct references), before backlinks and warnings, so its
``via="byName"`` references show up as backlinks and count as usage.

How it works (handling_indirection.md, section 4):

1. **Sinks** are the places a name is consumed: the argument of ``GetField``,
   ``Evaluate``, ``ExecuteSQL``, ``GetLayoutObjectAttribute``, ``ValueListItems`` and
   ``Field*`` / ``LayoutObjectNames`` functions, a comparison with ``Get ( LayoutName )``
   and friends, and by-name step targets (Set Field By Name, Perform Script [ By name ],
   Go to Layout [ by name ], Go to Object). Custom functions that pass a parameter into a
   sink are sinks too, at every call site.
2. Each sink argument is evaluated to **name shapes** (:class:`Alt`): literal text,
   names captured from a real reference (``GetFieldName ( T::f )``, ``Get ( ScriptName )``),
   names resolved by ID, and unknown parts (field contents, functions we don't model).
   Variables are traced to every place they are set; ``JSONGetElement ( Get (
   ScriptParameter ) ; "key" )`` is traced to the matching key of every caller's
   parameter (Perform Script, buttons, script triggers).
3. Shapes are matched against the catalog of the sink's kind: exact names, ``*``
   patterns (when they match few enough entities), IDs.
4. Each site gets a class (A, A', B, C, D, E; see ``model/indirection.py``) and its
   candidates become ``ReferenceRecord(via="byName")``.

The calc text is already scrubbed. Scrubbing only rewrites string literals and
comments, so a redacted literal simply fails to match (and is never reported as broken).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Iterable, Optional

from ..model.document_model import DocumentModel
from ..model.indirection import IndirectCandidate, IndirectionSite
from ..model.references import ReferenceRecord
from ..normalize.field_resolver import build_external_to_lookup, build_field_resolver
from .calc_ast import (
    Bin, Bracket, Call, Concat, FieldRef, Name, Node, Num, Other, Str, Var, let_bindings, parse, walk,
)

MAX_ALTS = 48             # alternatives kept per expression
MAX_DEPTH = 10            # nested traces (variables, parameters, custom functions)
MAX_PATTERN_MATCHES = 25  # a "*" pattern matching more entities than this is too broad to list
MAX_EVIDENCE = 6

SAFE_ORIGINS = ("capture", "self", "id")

# function (casefold) -> [(argument index, name kind)]
FUNCTION_SINKS: dict[str, list[tuple[int, str]]] = {
    "getfield": [(0, "field")],
    "evaluate": [(0, "expression")],
    "executesql": [(0, "sql")],
    "getlayoutobjectattribute": [(0, "layoutObject")],
    "valuelistitems": [(1, "valueList")],
    "fieldtype": [(1, "field")],
    "fieldcomment": [(1, "field")],
    "fieldstyle": [(1, "layout"), (2, "field")],
    "fieldrepetitions": [(1, "layout"), (2, "field")],
    "fieldbounds": [(1, "layout"), (2, "field")],
    "fieldnames": [(1, "layoutOrTableOccurrence")],
    "fieldids": [(1, "layoutOrTableOccurrence")],
    "layoutobjectnames": [(1, "layout")],
}

# Get ( X ) compared with a name: X (casefold) -> name kind
GET_COMPARISONS = {
    "layoutname": "layout",
    "layouttablename": "tableOccurrence",
    "scriptname": "script",
    "activefieldname": "field",
    "activefieldtablename": "tableOccurrence",
    "activelayoutobjectname": "layoutObject",
}
_COMPARE_OPS = {"=", "≠", "<>"}

# Get ( X ) values that depend on where the calc runs
_CONTEXT_GETS = {"layoutname", "layouttablename", "activefieldname", "activefieldtablename",
                 "activelayoutobjectname", "layoutnumber", "windowname", "filename", "triggertargetpanel",
                 "triggercurrentpanel", "activefieldcontents"}

# Functions whose result is (a form of) their first argument, for name purposes
_PASSTHROUGH = {"trim", "getastext", "quote", "textformatremove", "lower", "upper", "proper"}
# Functions that return some of the values (lines) of their first argument
_VALUE_PICKERS = {"getvalue", "leftvalues", "rightvalues", "middlevalues", "filtervalues"}

_REL_TYPE = {
    "field": "usesField",
    "script": "usesScript",
    "layout": "usesLayout",
    "valueList": "usesValueList",
    "tableOccurrence": "usesTableOccurrence",
    "layoutObject": "usesLayoutObject",
}

# A quick test before parsing a calc: could it contain a function sink or a comparison?
_SINK_HINT = re.compile(
    r"GetField\b|Evaluate|ExecuteSQL|GetLayoutObjectAttribute|ValueListItems|Field(?:Type|Style|Repetitions|Bounds"
    r"|Comment|Names|IDs)|LayoutObjectNames|Get\s*\(\s*(?:LayoutName|LayoutTableName|ScriptName|ActiveField"
    r"|ActiveLayoutObjectName)",
    re.I,
)


# ---------------------------------------------------------------------------
# Name shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Part:
    text: Optional[str]          # None = unknown at analysis time
    origin: str                  # literal | capture | self | id | data | context | param
    target: Optional[str] = None  # docId, for capture / self / id parts
    kind: Optional[str] = None    # target's entity type
    note: str = ""


@dataclass(frozen=True)
class Alt:
    parts: tuple[Part, ...]
    evidence: tuple[str, ...] = ()
    hops: int = 0  # 0 = written in the site's own expression

    @property
    def exact(self) -> bool:
        return all(p.text is not None for p in self.parts)

    @property
    def text(self) -> str:
        return "".join(p.text if p.text is not None else "*" for p in self.parts)

    @property
    def kind(self) -> str:
        """literal | capture | self | id | pattern | opaque"""
        meaningful = [p for p in self.parts if not (p.origin == "literal" and not _has_word(p.text or ""))]
        literal = any(p.origin == "literal" and _has_word(p.text or "") for p in self.parts)
        wild = any(p.text is None for p in self.parts)
        if wild:
            return "pattern" if literal and _has_word(self.text.replace("*", "")) else "opaque"
        if literal:
            return "literal"
        safe = [p for p in meaningful if p.origin in SAFE_ORIGINS]
        if safe and len(safe) == len(meaningful):
            return safe[0].origin
        return "literal"

    @property
    def unknown_notes(self) -> list[str]:
        return [p.note for p in self.parts if p.text is None and p.note]

    def via(self, note: str) -> "Alt":
        """One step further from the site (a variable, a parameter, a function body)."""
        return Alt(self.parts, ((note,) + self.evidence)[:MAX_EVIDENCE], self.hops + 1)

    def noted(self, note: str) -> "Alt":
        """Same distance, one more line of evidence."""
        return Alt(self.parts, ((note,) + self.evidence)[:MAX_EVIDENCE], self.hops)


def _has_word(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _lit(text: str) -> list[Alt]:
    return [Alt((Part(text, "literal"),))]


def _unknown(origin: str, note: str) -> list[Alt]:
    return [Alt((Part(None, origin, note=note),))]


def _concat(left: list[Alt], right: list[Alt]) -> list[Alt]:
    out = []
    for a in left:
        for b in right:
            # hops: the literal written nearest the site decides B (here) vs C (traced)
            out.append(Alt(_merge(a.parts + b.parts), (a.evidence + b.evidence)[:MAX_EVIDENCE],
                           min(a.hops, b.hops) if a.parts and b.parts else max(a.hops, b.hops)))
            if len(out) >= MAX_ALTS:
                return out
    return out


def _merge(parts: tuple[Part, ...]) -> tuple[Part, ...]:
    """Join neighbouring literal texts; collapse neighbouring unknowns."""
    out: list[Part] = []
    for p in parts:
        if out and p.origin == "literal" and out[-1].origin == "literal" and p.text is not None and out[-1].text is not None:
            out[-1] = Part(out[-1].text + p.text, "literal")
        elif out and p.text is None and out[-1].text is None:
            continue
        else:
            out.append(p)
    return tuple(out)


def _dedupe(alts: Iterable[Alt]) -> list[Alt]:
    seen: dict[tuple, Alt] = {}
    for a in alts:
        key = tuple((p.text, p.origin, p.target) for p in a.parts)
        if key not in seen or a.hops < seen[key].hops:
            seen[key] = a
        if len(seen) >= MAX_ALTS:
            break
    return list(seen.values())


# ---------------------------------------------------------------------------
# Evaluation context
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    script_doc_id: Optional[str] = None
    text: str = ""                                   # the calc the nodes belong to
    lets: dict[str, tuple[Node, "Ctx"]] = dc_field(default_factory=dict)   # casefold name -> binding
    cf_args: dict[str, tuple[Node, "Ctx"]] = dc_field(default_factory=dict)
    stack: tuple[str, ...] = ()                      # what is being traced, against cycles
    depth: int = 0

    def child(self, **kw) -> "Ctx":
        values = dict(script_doc_id=self.script_doc_id, text=self.text, lets=self.lets,
                      cf_args=self.cf_args, stack=self.stack, depth=self.depth + 1)
        values.update(kw)
        return Ctx(**values)

    def src(self, node: Node) -> str:
        return self.text[node.start:node.end].strip()


@dataclass
class _CalcSource:
    """A calculation, where it lives and what context it runs in."""
    text: str
    source_doc_id: str
    source_entity_type: str
    role: str
    script_doc_id: Optional[str] = None
    step: Optional[int] = None
    disabled: bool = False


# ---------------------------------------------------------------------------
# The analyzer
# ---------------------------------------------------------------------------

class IndirectionAnalyzer:
    def __init__(self, model: DocumentModel) -> None:
        self.model = model
        ents = model.entities
        self.resolve_field = build_field_resolver(model)
        self.is_external_to = build_external_to_lookup(model)
        self.sites: list[IndirectionSite] = []
        self._site_counts: dict[str, int] = {}
        self._var_memo: dict[tuple, list[Alt]] = {}
        self._param_memo: dict[tuple, list[Alt]] = {}

        # Catalogs by casefold name
        self.by_name: dict[str, dict[str, list[str]]] = {
            "script": {}, "layout": {}, "valueList": {}, "tableOccurrence": {}, "layoutObject": {},
        }
        for s in ents.scripts.values():
            self.by_name["script"].setdefault(s.name.strip().casefold(), []).append(s.doc_id)
        for lay in ents.layouts.values():
            self.by_name["layout"].setdefault(lay.name.strip().casefold(), []).append(lay.doc_id)
        for vl in ents.value_lists.values():
            self.by_name["valueList"].setdefault(vl.name.strip().casefold(), []).append(vl.doc_id)
        for to in ents.table_occurrences.values():
            self.by_name["tableOccurrence"].setdefault(to.name.strip().casefold(), []).append(to.doc_id)
        for obj in ents.layout_objects.values():
            if obj.name:
                self.by_name["layoutObject"].setdefault(obj.name.strip().casefold(), []).append(obj.doc_id)
        self.fields_by_name: dict[str, list[str]] = {}
        for f in ents.fields.values():
            self.fields_by_name.setdefault(f.name.casefold(), []).append(f.doc_id)
        self._qualified_names: Optional[list[tuple[str, str]]] = None
        self.by_fmp_id: dict[str, dict[str, str]] = {
            "script": {s.fmp_id: s.doc_id for s in ents.scripts.values() if s.fmp_id},
            "layout": {lay.fmp_id: lay.doc_id for lay in ents.layouts.values() if lay.fmp_id},
            "tableOccurrence": {t.fmp_id: t.doc_id for t in ents.table_occurrences.values() if t.fmp_id},
        }
        self.data_sources = {ds.name.casefold() for ds in model.external_data_sources if ds.name}

        # Custom functions
        self.cfs: dict[str, object] = {cf.name.casefold(): cf for cf in ents.custom_functions.values()}
        self.cf_capture: dict[str, set[int]] = {}      # param indexes that go into GetFieldName
        self.cf_id_resolver: dict[str, str] = {}       # CF -> kind it maps an ID to the name of
        self.cf_name_lookup: dict[str, str] = {}       # CF -> kind whose *name* it takes (getScriptID ( "x" ))
        self.cf_wrappers: dict[str, list[tuple[int, str, str, Node]]] = {}  # CF -> [(param i, sink, kind, inner arg)]
        self._classify_custom_functions()

        # Callers of each script: (param calc text, calling context, label)
        self.callers: dict[str, list[tuple[str, Optional[str], str]]] = {}
        self._index_callers()

        # Variables: (script docId | None for globals, casefold name) -> VariableEntity
        self.variables: dict[tuple[Optional[str], str], object] = {}
        for var in ents.variables.values():
            key = (var.script_doc_id if var.scope == "local" else None, _base_var(var.name).casefold())
            self.variables[key] = var

    # -- catalogs --------------------------------------------------------------
    def qualified_names(self) -> list[tuple[str, str]]:
        """Every ``TO::field`` this file can write, with the field's docId (for patterns)."""
        if self._qualified_names is None:
            ents = self.model.entities
            by_table: dict[str, list] = {}
            for f in ents.fields.values():
                by_table.setdefault(f.base_table_doc_id, []).append(f)
            out = []
            for to in ents.table_occurrences.values():
                for f in by_table.get(to.base_table_doc_id, []):
                    out.append((f"{to.name}::{f.name}", f.doc_id))
            self._qualified_names = out
        return self._qualified_names

    def label(self, doc_id: Optional[str]) -> str:
        if not doc_id:
            return ""
        ent = self.model.get_entity(doc_id)
        if ent is None:
            return doc_id
        if getattr(ent, "entity_type", "") == "scriptStep":
            script = self.model.entities.scripts.get(ent.script_doc_id)
            return f"step {ent.index + 1} of script \"{script.name if script else ent.script_doc_id}\""
        if getattr(ent, "entity_type", "") == "layoutObject":
            lay = self.model.entities.layouts.get(ent.layout_doc_id)
            what = f"object \"{ent.name}\"" if ent.name else f"{ent.object_type or 'object'} {ent.object_id}"
            return f"{what} on layout \"{lay.name if lay else ent.layout_doc_id}\""
        name = getattr(ent, "qualified_name", None) or getattr(ent, "name", doc_id)
        return f"{ent.entity_type} \"{name}\""

    # -- custom functions --------------------------------------------------------
    def _classify_custom_functions(self) -> None:
        for key, cf in self.cfs.items():
            text = cf.calculation or ""
            params = [p.casefold() for p in cf.parameters]
            if not text:
                continue
            tree = parse(text)
            for node in walk(tree):
                if isinstance(node, Call) and node.key == "getfieldname" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, Name) and arg.name.casefold() in params:
                        self.cf_capture.setdefault(key, set()).add(params.index(arg.name.casefold()))
            low = text.casefold()
            for kind, ids, names in (("script", "scriptids", "scriptnames"), ("layout", "layoutids", "layoutnames"),
                                     ("tableOccurrence", "tableids", "tablenames")):
                if ids in low and names in low and params:
                    if re.search(r"(name)(fromid)?$", key) and not re.search(r"id(fromname)?$", key):
                        self.cf_id_resolver[key] = kind
                    elif re.search(r"id(fromname)?$", key):
                        self.cf_name_lookup[key] = kind
            if "filemaker_fields" in low and params:
                if re.search(r"name(fromid)?$", key) and "fieldid" in low:
                    self.cf_id_resolver.setdefault(key, "field")
                elif re.search(r"id(fromname)?$", key):
                    self.cf_name_lookup.setdefault(key, "field")
        # Wrappers: a CF parameter flows into a sink. Iterate for CFs that call wrappers.
        for _ in range(5):
            changed = False
            for key, cf in self.cfs.items():
                text = cf.calculation or ""
                if not text or key in self.cf_id_resolver or key in self.cf_name_lookup:
                    continue
                params = [p.casefold() for p in cf.parameters]
                if not params:
                    continue
                found = set((i, s, k) for i, s, k, _n in self.cf_wrappers.get(key, []))
                new = list(self.cf_wrappers.get(key, []))
                for sink, kind, arg in self._raw_sinks(parse(text)):
                    for i, p in enumerate(params):
                        if _mentions(arg, p) and (i, sink, kind) not in found:
                            found.add((i, sink, kind))
                            new.append((i, sink, kind, arg))
                            changed = True
                if new:
                    self.cf_wrappers[key] = new
            if not changed:
                break

    def _raw_sinks(self, tree: Node) -> list[tuple[str, str, Node]]:
        """(sink label, kind, argument node) for every function sink in a parsed calc."""
        out = []
        for node in walk(tree):
            if isinstance(node, Call):
                for index, kind in FUNCTION_SINKS.get(node.key, []):
                    if index < len(node.args):
                        out.append((node.name, kind, node.args[index]))
                wrapped = self.cf_wrappers.get(node.key)
                if wrapped:
                    for i, sink, kind, _inner in wrapped:
                        if i < len(node.args):
                            out.append((f"{node.name}() → {sink}", kind, node.args[i]))
                if node.key in self.cf_name_lookup and node.args:
                    out.append((node.name, self.cf_name_lookup[node.key], node.args[0]))
            elif isinstance(node, Bin):
                out.extend(_comparison_sinks(node))
        return out

    # -- callers (for script parameters) -----------------------------------------
    def _index_callers(self) -> None:
        ents = self.model.entities
        for step in ents.script_steps.values():
            if step.name not in ("Perform Script", "Perform Script on Server"):
                continue
            target = next((r.get("targetDocId") for r in step.references
                           if r.get("kind") == "script" and r.get("targetDocId")), None)
            if not target:
                continue
            text = _step_param_text(step)
            self.callers.setdefault(target, []).append((text, step.script_doc_id, self.label(step.doc_id)))
        for obj in ents.layout_objects.values():
            if obj.button_script_doc_id:
                text = next((c.text for c in obj.calculations if c.role == "buttonParameter"), "")
                self.callers.setdefault(obj.button_script_doc_id, []).append((text, None, self.label(obj.doc_id)))
            self._trigger_callers(obj)
        for lay in ents.layouts.values():
            self._trigger_callers(lay)

    def _trigger_callers(self, entity) -> None:
        params = [c.text for c in entity.calculations if c.role == "scriptTriggerParameter"]
        for trig in entity.script_triggers:
            if not trig.script_doc_id:
                continue
            # With several triggers we can't tell which parameter belongs to which one
            text = params[0] if len(params) == 1 and len(entity.script_triggers) == 1 else ""
            self.callers.setdefault(trig.script_doc_id, []).append(
                (text, None, f"{trig.event} trigger on {self.label(entity.doc_id)}"))

    # -- evaluation --------------------------------------------------------------
    def evaluate(self, node: Node, ctx: Ctx, path: tuple[str, ...] = ()) -> list[Alt]:
        if ctx.depth > MAX_DEPTH:
            return _unknown("data", "too deeply nested to trace")
        return _dedupe(self._eval(node, ctx, path))

    def _eval(self, node: Node, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        if isinstance(node, Str):
            if path:
                return self._json_literal(node.value, path)
            return _lit(node.value)
        if isinstance(node, Num):
            return [] if path else _lit(node.text)
        if isinstance(node, Concat):
            if path:
                return _unknown("data", "text built with &")
            alts = [Alt(())]
            for part in node.parts:
                alts = _concat(alts, self.evaluate(part, ctx.child()))
            return alts
        if isinstance(node, Var):
            return self._eval_var(node.name, ctx, path)
        if isinstance(node, Name):
            key = node.name.casefold()
            if key in ctx.lets:
                bound, bctx = ctx.lets[key]
                return self.evaluate(bound, bctx.child(stack=ctx.stack, depth=max(ctx.depth, bctx.depth) + 1), path)
            if key in ctx.cf_args:
                bound, bctx = ctx.cf_args[key]
                return self.evaluate(bound, bctx.child(stack=ctx.stack, depth=max(ctx.depth, bctx.depth) + 1), path)
            return _unknown("data", f"value of {node.name}")
        if isinstance(node, FieldRef):
            return _unknown("data", f"contents of {node.qualified}")
        if isinstance(node, Call):
            return self._eval_call(node, ctx, path)
        if isinstance(node, Bracket) and len(node.items) == 1:
            return self.evaluate(node.items[0], ctx.child(), path)
        return _unknown("data", "a calculation result")

    def _eval_call(self, call: Call, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        key = call.key
        args = call.args
        if key == "getfieldname" and args:
            return [] if path else self._capture_field(args[0], ctx)
        if key == "get" and args:
            what = ctx.src(args[0]).replace(" ", "").casefold()
            if what == "scriptname":
                if path:
                    return []
                if ctx.script_doc_id:
                    script = self.model.entities.scripts.get(ctx.script_doc_id)
                    return [Alt((Part(script.name if script else None, "self", ctx.script_doc_id, "script"),),
                                (f"Get ( ScriptName ) in {self.label(ctx.script_doc_id)}",))]
                return _unknown("context", "Get ( ScriptName ) of the running script")
            if what == "scriptparameter":
                return self._eval_param(ctx, path)
            if what in _CONTEXT_GETS:
                return _unknown("context", f"Get ( {ctx.src(args[0])} ) at run time")
            return _unknown("data", f"Get ( {ctx.src(args[0])} )")
        if key.startswith("jsongetelement") and len(args) >= 2:
            keys = [a for a in self.evaluate(args[1], ctx.child()) if a.exact]
            if not keys:
                return _unknown("data", f"{call.name} with a computed key")
            out: list[Alt] = []
            for k in keys:
                out.extend(self.evaluate(args[0], ctx.child(), _json_path(k.text) + path))
            return out
        if key == "jsonsetelement" and args:
            if not path:
                return _unknown("data", "a JSON object")
            for k_node, v_node in _json_pairs(args):
                k_alts = [a for a in self.evaluate(k_node, ctx.child()) if a.exact]
                for k in k_alts:
                    kp = _json_path(k.text)
                    if kp and path[:len(kp)] == kp:
                        return self.evaluate(v_node, ctx.child(), path[len(kp):])
            return self.evaluate(args[0], ctx.child(), path)
        if key == "if" and len(args) >= 2:
            return [a for n in args[1:3] for a in self.evaluate(n, ctx.child(), path)]
        if key == "case" and len(args) >= 2:
            results = args[1::2] + ([args[-1]] if len(args) % 2 == 1 else [])
            return [a for n in results for a in self.evaluate(n, ctx.child(), path)]
        if key == "choose" and len(args) >= 2:
            return [a for n in args[1:] for a in self.evaluate(n, ctx.child(), path)]
        if key == "let" and len(args) >= 2:
            lets = dict(ctx.lets)
            for name, value in let_bindings(call):
                inner = ctx.child(lets=dict(lets))
                if name.startswith("$"):
                    continue  # a variable: traced through the variables index
                lets[name.casefold()] = (value, inner)
            return self.evaluate(args[-1], ctx.child(lets=lets), path)
        if key in _PASSTHROUGH and args and not path:
            return self.evaluate(args[0], ctx.child())
        if key in _VALUE_PICKERS and args and not path:
            return [v for a in self.evaluate(args[0], ctx.child()) for v in _values(a)]
        if key == "list" and args and not path:
            alts = [Alt(())]
            for i, arg in enumerate(args):
                if i:
                    alts = _concat(alts, _lit("\n"))
                alts = _concat(alts, self.evaluate(arg, ctx.child()))
            return alts
        if key == "substitute" and len(args) >= 2 and not path:
            return self._eval_substitute(args, ctx)
        if key in self.cfs:
            return self._eval_cf_call(call, ctx, path)
        return _unknown("data", f"{call.name}()")

    def _eval_substitute(self, args: list[Node], ctx: Ctx) -> list[Alt]:
        """``Substitute ( template ; [ "~table" ; SQLTable ( T::id ) ] ; ... )``: fill a literal template."""
        rest = args[1:]
        if all(isinstance(a, Bracket) for a in rest):
            pairs = [(b.items[0], b.items[1]) for b in rest if len(b.items) >= 2]
        elif len(rest) >= 2:
            pairs = [(rest[0], rest[1])]
        else:
            pairs = []
        searches = []
        for search_node, replace_node in pairs:
            found = [a.text for a in self.evaluate(search_node, ctx.child())
                     if a.exact and all(p.origin == "literal" for p in a.parts)]
            if len(found) != 1 or not found[0]:
                return _unknown("data", "Substitute with a computed search text")
            searches.append((found[0], self.evaluate(replace_node, ctx.child())))
        out: list[Alt] = []
        for template in self.evaluate(args[0], ctx.child()):
            alts = [Alt((), template.evidence, template.hops)]
            for part in template.parts:
                if part.origin != "literal" or part.text is None:
                    alts = [Alt(_merge(a.parts + (part,)), a.evidence, a.hops) for a in alts]
                    continue
                for piece in _split_all(part.text, searches):
                    alts = _concat(alts, piece if isinstance(piece, list) else _lit(piece))
            out.extend(alts)
            if len(out) >= MAX_ALTS:
                break
        return out

    def _capture_field(self, arg: Node, ctx: Ctx) -> list[Alt]:
        """``GetFieldName ( x )``: a safe capture when ``x`` is (bound to) a field reference."""
        seen = 0
        while isinstance(arg, Name) and seen < 6:
            key = arg.name.casefold()
            binding = ctx.lets.get(key) or ctx.cf_args.get(key)
            if binding is None:
                break
            arg, ctx = binding
            seen += 1
        if isinstance(arg, FieldRef):
            target = self.resolve_field(arg.table, arg.field)
            return [Alt((Part(arg.qualified, "capture", target, "field"),),
                        (f"GetFieldName ( {arg.qualified} )",))]
        if isinstance(arg, (Var, Call, Concat, Str)):
            # GetFieldName of an expression returns the name of the field the expression is
            return _unknown("data", "GetFieldName of an expression")
        return _unknown("data", "GetFieldName of an unknown field")

    def _eval_cf_call(self, call: Call, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        key = call.key
        cf = self.cfs[key]
        if key in self.cf_capture and not path:
            for i in sorted(self.cf_capture[key]):
                if i < len(call.args):
                    alts = self._capture_field(call.args[i], ctx)
                    if alts and alts[0].parts and alts[0].parts[0].origin == "capture":
                        return [Alt(a.parts, (f"{cf.name} ( {a.parts[0].text} )",)) for a in alts]
        if key in self.cf_id_resolver and call.args and not path:
            kind = self.cf_id_resolver[key]
            out = []
            for a in self.evaluate(call.args[0], ctx.child()):
                if a.exact and a.text.strip().isdigit():
                    target = (self.by_fmp_id.get(kind, {}).get(a.text.strip()) if kind != "field" else None)
                    name = self._name_of(target) if target else None
                    out.append(Alt((Part(name, "id", target, kind, note=f"{kind} ID {a.text.strip()}"),),
                                   (f"{cf.name} ( {a.text.strip()} )",)))
                else:
                    out.append(Alt((Part(None, "data", note=f"{cf.name} of a computed ID"),)))
            return out
        if f"cf:{key}" in ctx.stack:
            return _unknown("data", f"recursive {cf.name}()")
        if not cf.calculation:
            return _unknown("data", f"{cf.name}()")
        params = [p.casefold() for p in cf.parameters]
        cf_args = {p: (call.args[i], ctx) for i, p in enumerate(params) if i < len(call.args)}
        inner = Ctx(script_doc_id=ctx.script_doc_id, text=cf.calculation, cf_args=cf_args,
                    stack=ctx.stack + (f"cf:{key}",), depth=ctx.depth + 1)
        return [a.via(f"via {cf.name}()") for a in self.evaluate(parse(cf.calculation), inner, path)]

    def _name_of(self, doc_id: Optional[str]) -> Optional[str]:
        ent = self.model.get_entity(doc_id) if doc_id else None
        return getattr(ent, "name", None) if ent is not None else None

    def _json_literal(self, text: str, path: tuple[str, ...]) -> list[Alt]:
        try:
            value = json.loads(text)
        except ValueError:
            return []
        for key in path:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return []
        return _lit(value if isinstance(value, str) else json.dumps(value))

    # -- variables ---------------------------------------------------------------
    def _eval_var(self, name: str, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        base = _base_var(name)
        is_global = base.startswith("$$")
        scope = None if is_global else ctx.script_doc_id
        if not is_global and scope is None:
            return _unknown("data", f"{base} (a script's local variable)")
        key = (scope, base.casefold(), path)
        if key in self._var_memo:
            return self._var_memo[key]
        trace = f"var:{scope}:{base.casefold()}:{'.'.join(path)}"
        if trace in ctx.stack:
            return []
        self._var_memo[key] = []  # in progress
        var = self.variables.get((scope, base.casefold()))
        out: list[Alt] = []
        sets = [u for u in var.uses if u.access == "set"] if var is not None else []
        if not sets and not is_global:
            # Not set in this script: commonly unpacked from the script parameter by a CF
            # such as #Assign ( Get ( ScriptParameter ) ). Trace the parameter key.
            key_name = base.lstrip("$")
            alts = self._eval_param(ctx.child(stack=ctx.stack + (trace,)), (key_name,) + path)
            out = [a.via(f"{base} is never set in this script; assumed to be the parameter's \"{key_name}\"")
                   for a in alts]
        for use in sets[:MAX_ALTS]:
            out.extend(self._eval_var_set(base, use, ctx.child(stack=ctx.stack + (trace,)), path))
            if len(out) >= MAX_ALTS:
                break
        if not out:
            out = _unknown("data", f"{base} (never set with a value we can trace)")
        out = _dedupe(out)
        self._var_memo[key] = out
        return out

    def _eval_var_set(self, base: str, use, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        ents = self.model.entities
        step = ents.script_steps.get(use.source_doc_id)
        where = self.label(use.source_doc_id)
        if step is not None and use.via == "Set Variable":
            calc = next((c for c in step.calculations if c.slot == "value"), None) or \
                (step.calculations[0] if step.calculations else None)
            if calc is None:
                return []
            sctx = Ctx(script_doc_id=step.script_doc_id, text=calc.text, stack=ctx.stack, depth=ctx.depth)
            return [a.via(f"{base} set at {where}") for a in self.evaluate(parse(calc.text), sctx, path)]
        if use.via == "Let":
            texts = ([c.text for c in step.calculations] if step is not None else
                     [c.text for c in getattr(self.model.get_entity(use.source_doc_id), "calculations", None) or []])
            script = step.script_doc_id if step is not None else None
            out = []
            for text in texts:
                for value, lets in _let_assignments(parse(text), base):
                    sctx = Ctx(script_doc_id=script, text=text, stack=ctx.stack, depth=ctx.depth)
                    sctx.lets = {k: (v, sctx) for k, v in lets.items()}
                    out.extend(a.via(f"{base} set in a Let at {where}") for a in self.evaluate(value, sctx, path))
            return out
        return _unknown("data", f"{base} set by {use.via} at {where}")

    # -- script parameters -------------------------------------------------------
    def _eval_param(self, ctx: Ctx, path: tuple[str, ...]) -> list[Alt]:
        script = ctx.script_doc_id
        what = f"the parameter's \"{'.'.join(path)}\"" if path else "the script parameter"
        if not script:
            return _unknown("param", f"{what} (not in a script)")
        key = (script, path)
        if key in self._param_memo:
            return self._param_memo[key]
        trace = f"param:{script}:{'.'.join(path)}"
        if trace in ctx.stack:
            return []
        callers = self.callers.get(script, [])
        if not callers:
            return _unknown("param", f"{what} (no callers in this file)")
        self._param_memo[key] = []
        out: list[Alt] = []
        for text, caller_script, label in callers[:MAX_ALTS]:
            if not text:
                out.extend(_unknown("param", f"{what} (no parameter from {label})"))
                continue
            cctx = Ctx(script_doc_id=caller_script, text=text, stack=ctx.stack + (trace,), depth=ctx.depth + 1)
            for a in self.evaluate(parse(text), cctx, path):
                out.append(a.via(f"{what} from {label}"))
            if len(out) >= MAX_ALTS:
                break
        out = _dedupe(out) or _unknown("param", f"{what}: no caller passes it" if path else what)
        self._param_memo[key] = out
        return out

    # -- sites -------------------------------------------------------------------
    def run(self) -> None:
        for src in self._calc_sources():
            self._scan_calc(src)
        for step in self.model.entities.script_steps.values():
            self._scan_step(step)

    def _calc_sources(self) -> Iterable[_CalcSource]:
        ents = self.model.entities
        for step in ents.script_steps.values():
            for calc in step.calculations:
                yield _CalcSource(calc.text, step.doc_id, "scriptStep", step.name, step.script_doc_id, step.index + 1,
                                  disabled=not step.enabled)
        for etype, coll in (("field", ents.fields), ("layout", ents.layouts), ("layoutObject", ents.layout_objects),
                            ("customMenu", ents.custom_menus), ("customFunction", ents.custom_functions)):
            for ent in coll.values():
                for calc in ent.calculations:
                    yield _CalcSource(calc.text, ent.doc_id, etype, calc.role)

    def _scan_calc(self, src: _CalcSource) -> None:
        text = src.text
        if not text:
            return
        names = list(self.cf_wrappers) + list(self.cf_name_lookup)
        if not _SINK_HINT.search(text) and not any(n in text.casefold() for n in names):
            return
        tree = parse(text)
        cf_params: list[str] = []
        if src.source_entity_type == "customFunction":
            cf = self.model.entities.custom_functions.get(src.source_doc_id)
            cf_params = [p.casefold() for p in cf.parameters] if cf else []
        lets = _all_lets(tree)
        ctx = Ctx(script_doc_id=src.script_doc_id, text=text)
        ctx.lets = {k: (v, ctx) for k, v in lets.items()}
        for sink, kind, arg in self._raw_sinks(tree):
            if cf_params and any(_mentions(arg, p) for p in cf_params):
                continue  # depends on the CF's parameter: reported at each call site instead
            alts = self._eval_sink_arg(sink, arg, ctx, tree)
            self._add_site(src, sink, kind, ctx.src(arg), alts)

    def _eval_sink_arg(self, sink: str, arg: Node, ctx: Ctx, tree: Node) -> list[Alt]:
        if "() → " in sink:
            # A wrapper CF: evaluate the inner sink's argument with the CF's parameters bound
            cf_key = sink.split("()", 1)[0].casefold()
            call = next((n for n in walk(tree) if isinstance(n, Call) and n.key == cf_key
                         and any(a is arg for a in n.args)), None)
            cf = self.cfs.get(cf_key)
            if call is not None and cf is not None:
                params = [p.casefold() for p in cf.parameters]
                inner_sink = sink.split("→ ", 1)[1]
                for i, s, _k, inner_arg in self.cf_wrappers.get(cf_key, []):
                    if s == inner_sink and i < len(call.args) and call.args[i] is arg:
                        cf_args = {p: (call.args[j], ctx) for j, p in enumerate(params) if j < len(call.args)}
                        inner = Ctx(script_doc_id=ctx.script_doc_id, text=cf.calculation or "", cf_args=cf_args,
                                    stack=(f"cf:{cf_key}",), depth=1)
                        inner.lets = {k: (v, inner) for k, v in _all_lets(parse(cf.calculation or "")).items()}
                        # The argument is written at the call site: same distance as a direct sink
                        return [a.noted(f"via {cf.name}()") for a in self.evaluate(inner_arg, inner)]
        return self.evaluate(arg, ctx)

    def _scan_step(self, step) -> None:
        targets: list[tuple[str, str, str]] = []  # (sink, kind, calc text)
        calcs = step.calculations
        if step.name == "Set Field By Name":
            first = next((p.get("calc") for p in step.params if p.get("kind") == "calc"), 0)
            if isinstance(first, int) and first < len(calcs):
                targets.append(("Set Field By Name", "field", calcs[first].text))
        elif step.name in ("Perform Script", "Perform Script on Server"):
            for i, c in enumerate(calcs):
                labelled = any(p.get("kind") == "calc" and p.get("calc") == i and p.get("label") == "By name"
                               for p in step.params)
                if c.mode == "byName" or labelled:
                    targets.append((f"{step.name} [ By name ]", "script", c.text))
        elif step.name == "Go to Layout":
            for c in calcs:
                if c.mode == "byName":
                    targets.append(("Go to Layout [ by name ]", "layout", c.text))
        for c in calcs:
            if c.parameter == "Object" and (c.slot or "").casefold() == "name":
                targets.append((f"{step.name} [ Object Name ]", "layoutObject", c.text))
        if not targets:
            return
        src = _CalcSource("", step.doc_id, "scriptStep", step.name, step.script_doc_id, step.index + 1,
                          disabled=not step.enabled)
        for sink, kind, text in targets:
            tree = parse(text)
            ctx = Ctx(script_doc_id=step.script_doc_id, text=text)
            ctx.lets = {k: (v, ctx) for k, v in _all_lets(tree).items()}
            alts = self.evaluate(tree, ctx)
            self._add_site(src, sink, kind, text.strip(), alts)

    # -- matching and classification ----------------------------------------------
    def _add_site(self, src: _CalcSource, sink: str, kind: str, expression: str, alts: list[Alt]) -> None:
        if alts:
            # An empty name ("" for "no object") names nothing: not a reference
            alts = [a for a in alts if not (a.kind == "literal" and not a.text.strip())]
            if not alts:
                return
        if kind == "sql":
            candidates, names, klass, note = self._match_sql(alts)
        elif kind == "expression":
            candidates, names, klass, note = self._match_expression(alts)
        else:
            candidates, names, klass, note = self._match(kind, alts)
        if klass is None:
            return  # e.g. Evaluate of a literal with no names in it: not an indirection
        if "<Field Missing>" in expression or "<Table Missing>" in expression:
            klass, note = "E", "FileMaker reports the target as missing"
        if src.disabled:
            note = "; ".join(filter(None, [note, "the step is disabled"]))
        n = self._site_counts.get(src.source_doc_id, 0) + 1
        self._site_counts[src.source_doc_id] = n
        self.sites.append(IndirectionSite(
            docId=f"{src.source_doc_id}#ind{n}", sourceDocId=src.source_doc_id,
            sourceEntityType=src.source_entity_type, scriptDocId=src.script_doc_id, step=src.step,
            role=src.role, sink=sink, nameKind=kind, expression=expression[:500], **{"class": klass},
            names=names[:20], note=note, candidates=candidates,
        ))

    def _match(self, kind: str, alts: list[Alt]):
        candidates: dict[str, IndirectCandidate] = {}
        names: list[str] = []
        unresolved: list[str] = []
        notes: list[str] = []
        kinds = set()
        broad = []
        for alt in alts:
            k = alt.kind
            kinds.add(k)
            if k in SAFE_ORIGINS:
                for p in alt.parts:
                    if p.origin in SAFE_ORIGINS:
                        names.append(p.text or p.note)
                        if p.target:
                            self._cand(candidates, p.target, p.kind or kind, p.text or p.note, p.origin, alt)
                        else:
                            unresolved.append(p.text or p.note)
                continue
            if k == "literal":
                name = alt.text.strip()
                names.append(name)
                hits = self._lookup(kind, name)
                if hits is None:
                    continue  # names another file
                bare = kind == "field" and "::" not in name  # a field of whatever layout is current
                for target, tkind in hits:
                    self._cand(candidates, target, tkind, name, "literal", alt, inferred=bare)
                if not hits:
                    unresolved.append(name)
                continue
            if k == "pattern":
                pattern = alt.text.strip()
                names.append(pattern)
                hits = self._lookup_pattern(kind, pattern)
                if len(hits) > MAX_PATTERN_MATCHES:
                    broad.append(f"\"{pattern}\" matches {len(hits)} names")
                    continue
                for target, tkind in hits:
                    self._cand(candidates, target, tkind, pattern, "pattern", alt)
                continue
            notes.extend(alt.unknown_notes[:1])
        klass = _classify(alts, kinds, bool(candidates), unresolved)
        note_parts = []
        if unresolved and klass != "E":
            note_parts.append("no match for " + ", ".join(f"\"{u}\"" for u in dict.fromkeys(unresolved)))
        if klass == "E":
            note_parts.append("names nothing in this file: " + ", ".join(f"\"{u}\"" for u in dict.fromkeys(unresolved)))
        note_parts.extend(broad)
        if notes and klass in ("C", "D"):
            note_parts.append("unknown: " + "; ".join(dict.fromkeys(notes)))
        return list(candidates.values()), list(dict.fromkeys(names)), klass, "; ".join(note_parts) or None

    def _cand(self, out: dict, target: str, kind: str, name: str, origin: str, alt: Alt,
              inferred: bool = False) -> None:
        if target in out:
            return
        confidence = ("parsed" if alt.hops == 0 and not inferred and origin in ("literal", "capture", "self", "id")
                      else "inferred")
        out[target] = IndirectCandidate(targetDocId=target, targetEntityType=kind, name=name, origin=origin,
                                        confidence=confidence, evidence=list(alt.evidence))

    def _lookup(self, kind: str, name: str) -> Optional[list[tuple[str, str]]]:
        """Entities ``name`` names; [] when none; None when it names something in another file."""
        if not name or "[REDACTED" in name:
            return []
        if kind == "layoutOrTableOccurrence":
            hits = (self._lookup("layout", name) or []) + (self._lookup("tableOccurrence", name) or [])
            return hits
        if kind == "field":
            name = re.sub(r"\[\d+\]$", "", name).strip()
            if "::" in name:
                table, fld = name.split("::", 1)
                if self.is_external_to(table):
                    return None
                target = self.resolve_field(table, fld)
                return [(target, "field")] if target else []
            hits = self.fields_by_name.get(name.casefold(), [])
            return [(h, "field") for h in hits[:MAX_PATTERN_MATCHES]]
        if kind in ("script", "layout") and "::" in name and name.split("::", 1)[0].casefold() in self.data_sources:
            return None
        return [(d, kind) for d in self.by_name.get(kind, {}).get(name.casefold(), [])]

    def _lookup_pattern(self, kind: str, pattern: str) -> list[tuple[str, str]]:
        regex = re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$", re.I | re.S)
        if kind == "layoutOrTableOccurrence":
            return self._lookup_pattern("layout", pattern) + self._lookup_pattern("tableOccurrence", pattern)
        if kind == "field":
            if "::" in pattern:
                hits = {doc for qn, doc in self.qualified_names() if regex.match(qn)}
            else:
                hits = {doc for nm, docs in self.fields_by_name.items() if regex.match(nm) for doc in docs}
            return [(h, "field") for h in sorted(hits)]
        out = []
        for nm, docs in self.by_name.get(kind, {}).items():
            if regex.match(nm):
                out.extend((d, kind) for d in docs)
        return out

    def _match_expression(self, alts: list[Alt]):
        """Evaluate ( "..." ): a literal is a calculation; the fields it names are by-name uses."""
        candidates: dict[str, IndirectCandidate] = {}
        names: list[str] = []
        kinds = set()
        unresolved: list[str] = []
        for alt in alts:
            if alt.kind in SAFE_ORIGINS:
                kinds.add(alt.kind)
                for p in alt.parts:
                    if p.origin in SAFE_ORIGINS and p.target:
                        names.append(p.text or "")
                        self._cand(candidates, p.target, p.kind or "field", p.text or "", p.origin, alt)
                continue
            if alt.kind not in ("literal", "pattern"):
                kinds.add(alt.kind)
                continue
            refs = [n for n in walk(parse(alt.text)) if isinstance(n, FieldRef) and "*" not in n.qualified]
            if refs:
                kinds.add(alt.kind)
            elif alt.kind == "pattern":
                kinds.add("opaque")  # built at run time, no names we can see
            for node in refs:
                names.append(node.qualified)
                hits = self._lookup("field", node.qualified)
                for target, tkind in hits or []:
                    self._cand(candidates, target, tkind, node.qualified, "literal", alt)
                if hits == []:
                    unresolved.append(node.qualified)
        if not kinds:
            return [], [], None, None  # Evaluate of a constant expression: nothing to rename
        alts = [a for a in alts if a.kind not in ("literal", "pattern") or a.kind in kinds]
        klass = _classify(alts, kinds, bool(candidates), unresolved)
        note = ("no match for " + ", ".join(f"\"{u}\"" for u in unresolved)) if unresolved and klass != "E" else None
        if klass == "E":
            note = "names nothing in this file: " + ", ".join(f"\"{u}\"" for u in unresolved)
        return list(candidates.values()), list(dict.fromkeys(names)), klass, note

    def _match_sql(self, alts: list[Alt]):
        """ExecuteSQL: table occurrences after FROM / JOIN / UPDATE / INTO, and their columns."""
        candidates: dict[str, IndirectCandidate] = {}
        names: list[str] = []
        safe = system = literal_tables = dynamic = False
        unresolved: list[str] = []
        for alt in alts:
            sql = "".join(p.text if p.origin == "literal" and p.text is not None else "\x00" for p in alt.parts)
            for p in alt.parts:
                if p.origin in SAFE_ORIGINS and p.target:
                    safe = True
                    self._cand(candidates, p.target, p.kind or "field", p.text or "", p.origin, alt)
                    names.append(p.text or "")
                elif p.text is None and p.origin != "literal":
                    dynamic = True
            tables, columns = _sql_identifiers(sql)
            to_docs = []
            for t in tables:
                if t.casefold().startswith("filemaker_"):
                    system = True
                    continue
                literal_tables = True
                names.append(t)
                hits = self._lookup("tableOccurrence", t)
                if not hits:
                    unresolved.append(t)
                for target, tkind in hits or []:
                    to_docs.append(target)
                    self._cand(candidates, target, tkind, t, "literal", alt)
            for col in columns:
                for to_doc in to_docs:
                    to = self.model.entities.table_occurrences.get(to_doc)
                    target = self.resolve_field(to.name, col) if to else None
                    if target:
                        names.append(f"{to.name}.{col}")
                        self._cand(candidates, target, "field", f"{to.name}.{col}", "literal", alt)
        if literal_tables:
            hops = min(a.hops for a in alts)
            klass = "B" if hops == 0 else "C"
            if unresolved and not candidates:
                klass = "E"
        elif safe:
            klass = "A"
        elif system:
            klass = "A'"
        elif dynamic:
            klass = "D"
        else:
            return [], [], None, None
        note = None
        if system:
            note = "queries the FileMaker_Tables / FileMaker_Fields system tables (by ID or name)"
        if unresolved:
            note = "; ".join(filter(None, [note, "no table occurrence named " +
                                           ", ".join(f"\"{u}\"" for u in dict.fromkeys(unresolved))]))
        return list(candidates.values()), list(dict.fromkeys(names)), klass, note

    # -- output --------------------------------------------------------------------
    def custom_function_roles(self) -> dict[str, str]:
        """CF key -> what it does with names, in a sentence."""
        kinds = {"field": "field", "script": "script", "layout": "layout", "tableOccurrence": "table occurrence",
                 "valueList": "value list", "layoutObject": "layout object", "layoutOrTableOccurrence":
                 "layout or table occurrence", "sql": "table or field (SQL)", "expression": "field (in a formula)"}
        roles: dict[str, str] = {}
        for key, cf in self.cfs.items():
            params = cf.parameters
            parts = []
            if key in self.cf_capture:
                names = ", ".join(f"`{params[i]}`" for i in sorted(self.cf_capture[key]) if i < len(params))
                parts.append(f"Captures the name of the field passed as {names} with GetFieldName: "
                             "calls follow a rename.")
            if key in self.cf_id_resolver:
                parts.append(f"Returns the name of the {kinds[self.cf_id_resolver[key]]} whose ID is passed in: "
                             "calls with a literal ID follow a rename.")
            if key in self.cf_name_lookup:
                parts.append(f"Looks up a {kinds[self.cf_name_lookup[key]]} by the name passed in: "
                             "every call names it in text.")
            for i, sink, kind, _arg in self.cf_wrappers.get(key, []):
                if i < len(params):
                    parts.append(f"Passes `{params[i]}` to {sink}: every call names a {kinds.get(kind, kind)} "
                                 "in text.")
            if parts:
                roles[key] = " ".join(dict.fromkeys(parts))
        return roles

    def emit(self) -> None:
        model = self.model
        model.indirection = self.sites
        roles = self.custom_function_roles()
        for key, cf in self.cfs.items():
            cf.name_role = roles.get(key)
        existing = {(r.source_doc_id, r.target_doc_id, r.relationship_type): r for r in model.references}
        seen: set[tuple[str, str, str]] = set()
        for site in self.sites:
            for cand in site.candidates:
                rel = _REL_TYPE.get(cand.target_entity_type, "usesField")
                key = (site.source_doc_id, cand.target_doc_id, rel)
                prior = existing.get(key)
                if prior is not None and prior.via is None and site.sink.casefold() == "valuelistitems":
                    prior.via, prior.site_doc_id = "byName", site.doc_id  # already linked by CalcRefResolver
                    continue
                if key + (site.sink,) in seen:
                    continue
                seen.add(key + (site.sink,))
                model.references.append(ReferenceRecord(
                    sourceDocId=site.source_doc_id, sourceEntityType=site.source_entity_type,
                    targetDocId=cand.target_doc_id, targetEntityType=cand.target_entity_type,
                    relationshipType=rel, role=site.sink, confidence=cand.confidence, rawText=cand.name,
                    via="byName", siteDocId=site.doc_id,
                ))
            if site.klass == "E":
                model.add_warning(
                    "BYNAME_TARGET_MISSING",
                    f"{site.sink} in {self.label(site.source_doc_id)} names something that doesn't exist",
                    entity_doc_id=site.source_doc_id, detail=site.note,
                )
        opaque = sum(1 for s in self.sites if s.klass == "D")
        if opaque:
            model.add_warning(
                "BYNAME_OPAQUE",
                f"{opaque} by-name reference(s) get their name from data and can't be checked "
                "statically (see Reports/indirection.md)",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(alts: list[Alt], kinds: set[str], resolved: bool, unresolved: list[str]) -> str:
    if not alts:
        return "D"
    if kinds and kinds <= set(SAFE_ORIGINS):
        return "A'" if kinds == {"id"} else "A"
    if "literal" in kinds or "pattern" in kinds:
        literal_alts = [a for a in alts if a.kind in ("literal", "pattern")]
        if unresolved and not resolved and "pattern" not in kinds and all(a.kind == "literal" for a in alts):
            return "E"
        if all(a.hops == 0 for a in literal_alts) and "pattern" not in kinds and kinds <= {"literal", *SAFE_ORIGINS}:
            return "B"
        return "C"
    if kinds & set(SAFE_ORIGINS) and resolved:
        return "C"
    return "D"


def _comparison_sinks(node: Bin) -> list[tuple[str, str, Node]]:
    out = []
    items = node.items
    for i in range(1, len(items) - 1, 2):
        op = items[i]
        if op not in _COMPARE_OPS:
            continue
        left, right = items[i - 1], items[i + 1]
        for get_side, other in ((left, right), (right, left)):
            what = _get_arg(get_side)
            if what in GET_COMPARISONS and not _get_arg(other):
                out.append((f"Get ( {what_label(what)} ) {op}", GET_COMPARISONS[what], other))
    return out


def what_label(key: str) -> str:
    return {"layoutname": "LayoutName", "layouttablename": "LayoutTableName", "scriptname": "ScriptName",
            "activefieldname": "ActiveFieldName", "activefieldtablename": "ActiveFieldTableName",
            "activelayoutobjectname": "ActiveLayoutObjectName"}.get(key, key)


def _get_arg(node) -> Optional[str]:
    if isinstance(node, Call) and node.key == "get" and node.args and isinstance(node.args[0], Name):
        return node.args[0].name.casefold()
    return None


def _mentions(node: Node, name: str) -> bool:
    return any(isinstance(n, Name) and n.name.casefold() == name for n in walk(node))


def _all_lets(tree: Node) -> dict[str, Node]:
    """Non-variable Let bindings anywhere in a calc (last one wins), for tracing ``x`` in ``GetField ( x )``."""
    out: dict[str, Node] = {}
    for node in walk(tree):
        if isinstance(node, Call) and node.key == "let":
            for name, value in let_bindings(node):
                if not name.startswith("$") and not _mentions(value, name.casefold()):
                    out[name.casefold()] = value
    return out


def _let_assignments(tree: Node, var: str) -> list[tuple[Node, dict[str, Node]]]:
    """Values assigned to ``var`` in Let declarations, with the calc's other Let names."""
    out = []
    lets = _all_lets(tree)
    for node in walk(tree):
        if isinstance(node, Call) and node.key == "let":
            for name, value in let_bindings(node):
                if _base_var(name).casefold() == var.casefold():
                    out.append((value, lets))
    return out


def _values(alt: Alt) -> list[Alt]:
    """A return-separated list as one alternative per value (GetValue picks one of them)."""
    if not any(p.origin == "literal" and p.text and "\n" in p.text for p in alt.parts):
        return [alt]
    values: list[list[Part]] = [[]]
    for p in alt.parts:
        if p.origin == "literal" and p.text and "\n" in p.text:
            pieces = p.text.split("\n")
            if pieces[0]:
                values[-1].append(Part(pieces[0], "literal"))
            for piece in pieces[1:]:
                values.append([Part(piece, "literal")] if piece else [])
        else:
            values[-1].append(p)
    return [Alt(_merge(tuple(v)), alt.evidence, alt.hops) for v in values
            if v and any(p.text is None or (p.text or "").strip() for p in v)]


def _split_all(text: str, searches: list[tuple[str, list[Alt]]]) -> list:
    """``text`` cut at each search string, which is replaced by its alternatives (a list)."""
    out: list = []
    i = 0
    while i < len(text):
        hit = None
        for search, repl in searches:
            j = text.find(search, i)
            if j >= 0 and (hit is None or j < hit[0] or (j == hit[0] and len(search) > len(hit[1]))):
                hit = (j, search, repl)
        if hit is None:
            out.append(text[i:])
            break
        j, search, repl = hit
        if j > i:
            out.append(text[i:j])
        out.append(repl)
        i = j + len(search)
    return out


def _json_path(key: str) -> tuple[str, ...]:
    return tuple(k for k in re.sub(r"\[\d+\]", "", key).split(".") if k)


def _json_pairs(args: list[Node]) -> list[tuple[Node, Node]]:
    """(key, value) nodes of JSONSetElement ( json ; [k ; v ; t] ... ) or ( json ; k ; v ; t )."""
    rest = args[1:]
    if rest and all(isinstance(a, Bracket) for a in rest):
        return [(b.items[0], b.items[1]) for b in rest if len(b.items) >= 2]
    if len(rest) >= 2:
        return [(rest[0], rest[1])]
    return []


def _base_var(name: str) -> str:
    return re.sub(r"\[.*$", "", name)


def _step_param_text(step) -> str:
    for p in step.params:
        if p.get("kind") == "calc" and p.get("label") == "Parameter":
            i = p.get("calc")
            if isinstance(i, int) and i < len(step.calculations):
                return step.calculations[i].text
    return ""


_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "in", "is", "null", "like", "join", "inner", "outer", "left",
    "right", "full", "on", "as", "order", "by", "group", "having", "distinct", "count", "sum", "avg", "min", "max",
    "insert", "into", "values", "update", "set", "delete", "asc", "desc", "fetch", "first", "next", "rows", "only",
    "offset", "limit", "union", "all", "case", "when", "then", "else", "end", "between", "exists", "upper", "lower",
    "trim", "cast", "coalesce", "true", "false", "top", "row", "current_date", "current_timestamp", "substring",
    "char", "varchar", "date", "time", "timestamp", "int", "integer", "numeric", "decimal", "concat", "length",
    "strval", "nullif", "position", "extract", "year", "month", "day", "rowid", "rtrim", "ltrim",
}
_SQL_TOKEN = re.compile(r'"((?:[^"]|"")*)"|([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)|\x00|\'(?:[^\']|\'\')*\'|.', re.S)


def _sql_identifiers(sql: str) -> tuple[list[str], list[str]]:
    """Table names (after FROM / JOIN / UPDATE / INTO) and column names in a SQL text.

    ``\\x00`` marks text computed at run time: a table name there is unknown.
    """
    tables: list[str] = []
    columns: list[str] = []
    aliases: set[str] = set()
    expect_table = after_table = False
    for m in _SQL_TOKEN.finditer(sql):
        raw = m.group()
        if not raw.strip():
            continue
        quoted, bare = m.group(1), m.group(2)
        if quoted is None and bare is None:
            expect_table = raw == "," and after_table  # FROM a, b
            after_table = False
            continue
        word = quoted.replace('""', '"') if quoted is not None else bare
        low = word.casefold()
        if quoted is None and low in ("from", "join", "update", "into"):
            expect_table, after_table = True, False
            continue
        if expect_table:
            tables.append(word)
            expect_table, after_table = False, True
            continue
        if after_table and quoted is None and low not in _SQL_KEYWORDS:
            aliases.add(low)  # FROM Invoices i
            after_table = False
            continue
        after_table = False
        if quoted is None and (low in _SQL_KEYWORDS or low in aliases):
            continue
        columns.append(word.split(".", 1)[-1] if quoted is None else word)
    return list(dict.fromkeys(tables)), list(dict.fromkeys(columns))


def analyze_indirection(model: DocumentModel) -> DocumentModel:
    """Populate ``model.indirection`` and add ``via="byName"`` references."""
    model.indirection = []
    analyzer = IndirectionAnalyzer(model)
    analyzer.run()
    analyzer.emit()
    return model
