"""Index FileMaker variables: where each ``$local`` and ``$$global`` is set and read.

Sources:

* Script steps. Targets in ``params`` are assignments (Set Variable, and the
  ``Target:`` of Insert from URL, Get File Exists, ...). ``$x`` in a step calc is a read,
  except a ``Let`` declaration (``Let ( [ $x = 1 ; ... ] ; ... )``), which is an assignment.
* Every other calculation in the file (fields, layouts, layout objects, custom functions,
  custom menus), for ``$$globals`` only. A ``$local`` there belongs to whichever script
  happens to be running, so it can't be attributed.

Variable names are case-insensitive in FileMaker. A repetition (``$x[2]``) is the same
variable. Runs after normalization, on calc text that has already been scrubbed:
scrubbing only rewrites string literals and comments, never names.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from ..model.document_model import DocumentModel
from ..model.entities import VariableEntity, VariableUse
from ..scrub.calc_lexer import COMMENT, OP, VAR, WS, Token, tokenize


def calc_variables(text: str) -> list[tuple[str, bool]]:
    """``(name, assigned)`` for each variable token in a calc, in order.

    ``assigned`` is True for a ``Let`` declaration, False for a read.
    """
    tokens = [t for t in tokenize(text or "") if t.kind not in (WS, COMMENT)]
    out: list[tuple[str, bool]] = []
    frames: list[_Frame] = []
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else None
        frame = frames[-1] if frames else None
        if tok.kind == OP and tok.text == "(":
            is_let = prev is not None and prev.text.lower() == "let"
            frames.append(_Frame(let=is_let))
            continue
        if tok.kind == OP and tok.text == ")":
            if frames:
                frames.pop()
            continue
        if frame is None or not frame.declaring:
            if tok.kind == VAR:
                out.append((tok.text, False))
            continue
        # Inside a Let's declarations
        if tok.kind == OP and tok.text == "[":
            if frame.at_start and frame.square == 0:
                frame.bracketed = True
            frame.square += 1
            frame.at_start = frame.square == 1 and frame.bracketed
            continue
        if tok.kind == OP and tok.text == "]":
            frame.square -= 1
            if frame.bracketed and frame.square == 0:
                frame.declaring = False
            continue
        if tok.kind == OP and tok.text == ";" and frame.square == (1 if frame.bracketed else 0):
            if frame.bracketed:
                frame.at_start = True
            else:
                frame.declaring = False
            continue
        if tok.kind == VAR:
            out.append((tok.text, frame.at_start and _assigns(tokens, i)))
        frame.at_start = False
    return out


class _Frame:
    """One open parenthesis. ``declaring`` while inside a Let's declaration list."""

    def __init__(self, let: bool) -> None:
        self.declaring = let
        self.bracketed = False
        self.square = 0
        self.at_start = let  # next token starts a declaration


def _assigns(tokens: list[Token], i: int) -> bool:
    """``$x = ...`` or ``$x[n] = ...`` from position ``i``."""
    j = i + 1
    if j < len(tokens) and tokens[j].text == "[":
        depth = 0
        while j < len(tokens):
            if tokens[j].text == "[":
                depth += 1
            elif tokens[j].text == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        j += 1
    return j < len(tokens) and tokens[j].text == "="


def _base_name(name: str) -> str:
    """``$x[2]`` → ``$x``."""
    return name.split("[", 1)[0].strip()


class _Index:
    def __init__(self, model: DocumentModel) -> None:
        self.model = model
        self.by_key: dict[str, VariableEntity] = {}

    def add(self, name: str, script_doc_id: Optional[str], use: VariableUse) -> None:
        name = _base_name(name)
        if not name.startswith("$") or name in ("$", "$$"):
            return
        is_global = name.startswith("$$")
        if not is_global and script_doc_id is None:
            return
        key = name.lower() if is_global else f"{script_doc_id}\0{name.lower()}"
        var = self.by_key.get(key)
        if var is None:
            if is_global:
                doc_id = f"variable:{name}"
            else:
                script = self.model.entities.scripts.get(script_doc_id)
                doc_id = f"variable:{script.name if script else script_doc_id}::{name}"
            var = VariableEntity(docId=doc_id, name=name, scope="global" if is_global else "local",
                                 scriptDocId=None if is_global else script_doc_id)
            self.by_key[key] = var
        var.uses.append(use)


def build_variables(model: DocumentModel) -> DocumentModel:
    """Populate ``model.entities.variables`` and each script's ``variables``."""
    index = _Index(model)
    ents = model.entities

    for script in ents.scripts.values():
        for step_doc_id in script.steps:
            step = ents.script_steps.get(step_doc_id)
            if step is None:
                continue
            targets = [p.get("name") for p in step.params if p.get("kind") == "variable" and p.get("name")]
            if not step.params and step.parameters.get("variable"):  # model.json from before params
                targets = [step.parameters["variable"]]
            for name in targets:
                index.add(name, script.doc_id, _step_use(step, script.doc_id, "set", step.name))
            for calc in step.calculations:
                for name, assigned in calc_variables(calc.text):
                    index.add(name, script.doc_id, _step_use(step, script.doc_id, "set" if assigned else "read",
                                                             "Let" if assigned else step.name))

    for source_doc_id, role, text in _other_calcs(model):
        for name, assigned in calc_variables(text):
            if name.startswith("$$"):
                index.add(name, None, VariableUse(sourceDocId=source_doc_id, access="set" if assigned else "read",
                                                  via="Let" if assigned else role))

    ents.variables = {v.doc_id: v for v in sorted(index.by_key.values(), key=lambda v: v.name.lower())}
    for script in ents.scripts.values():
        script.variables = []
    for var in ents.variables.values():
        for script_doc_id in dict.fromkeys(u.script_doc_id for u in var.uses if u.script_doc_id):
            script = ents.scripts.get(script_doc_id)
            if script is not None:
                script.variables.append(var.doc_id)
    return model


def _step_use(step, script_doc_id: str, access: str, via: str) -> VariableUse:
    return VariableUse(sourceDocId=step.doc_id, scriptDocId=script_doc_id, step=step.index + 1,
                       access=access, via=via)


def _other_calcs(model: DocumentModel) -> Iterable[tuple[str, str, str]]:
    """(entity docId, calc role, text) for every calculation outside script steps."""
    ents = model.entities
    for collection in (ents.fields, ents.layouts, ents.layout_objects, ents.custom_functions, ents.custom_menus):
        for entity in collection.values():
            for calc in getattr(entity, "calculations", None) or []:
                if calc.text:
                    yield entity.doc_id, calc.role, calc.text
