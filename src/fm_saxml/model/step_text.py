"""Script step text as FileMaker's Script Workspace shows it, built from a step's ``params``.

    Set Variable [ $TASK_NAME ; Value: Get ( ScriptName ) ]
    Set Field [ CATALOGUE::description ; $value ]
    Perform Script [ "Generic - Centre Card Window" ; Parameter: $id ]
    # Start, End Context: Any, Any

Nothing is truncated. Calcs are looked up by index in the step's ``calculations``, so
the text is always built from the scrubbed calcs. Steps without ``params`` (v1 exports,
older model.json files) fall back to the parser's ``raw_text`` preview.

Works on ``ScriptStepEntity`` objects and on the parser's raw step dicts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

COMMENT_STEP = "# (comment)"

# Block structure, for indentation: steps that open, continue or close a block.
_OPENS = {"If", "Loop", "Open Transaction"}
_CONTINUES = {"Else", "Else If"}
_CLOSES = {"End If", "End Loop", "Commit Transaction"}

_NEWLINES = re.compile(r"\r\n|\r|\n")


@dataclass
class StepLine:
    """One script step, ready to print: ``depth`` is its block nesting level."""

    number: int          # 1-based, as in FileMaker
    depth: int
    enabled: bool
    lines: list[str]     # the step text; more than one when a calc or comment spans lines


def _get(step: Any, name: str, default: Any = None) -> Any:
    if isinstance(step, dict):
        return step.get(name, default)
    return getattr(step, name, default)


def _calc_text(step: Any, index: Any) -> str | None:
    if not isinstance(index, int):
        return None
    calcs = _get(step, "calculations") or []
    if not 0 <= index < len(calcs):
        return None
    calc = calcs[index]
    text = calc.get("text") if isinstance(calc, dict) else getattr(calc, "text", None)
    return text if isinstance(text, str) else None


def _with_repetition(step: Any, name: str, rep_index: Any) -> str:
    rep = _calc_text(step, rep_index)
    return f"{name}[{rep}]" if rep and rep.strip() != "1" else name


def _labelled(label: Any, value: str) -> str:
    return f"{label}: {value}" if label else value


def format_param(step: Any, item: dict) -> str | None:
    """One ``params`` item as text, or None when it has nothing to show."""
    kind = item.get("kind")
    label = item.get("label")
    if kind == "calc":
        text = _calc_text(step, item.get("calc"))
        if text is None or (label == "Repetition" and text.strip() == "1"):
            return None
        return _labelled(label, text)
    if kind in ("field", "variable"):
        name = item.get("name") or ""
        return _labelled(label, _with_repetition(step, name, item.get("repetition"))) if name else None
    if kind == "script":
        text = f'"{item.get("name", "")}"'
        if item.get("dataSource"):
            text += f' from file: "{item["dataSource"]}"'
        return _labelled(label, text)
    if kind in ("layout", "valueList", "menuSet", "privilegeSet"):
        return _labelled(label, f'"{item.get("name", "")}"')
    if kind in ("to", "file"):
        return _labelled(label, item.get("name", ""))
    if kind == "option":
        value = item.get("value")
        return _labelled(label, value) if value else None
    if kind == "text":
        text = item.get("text")
        return _labelled(label, text) if text else None
    return None


def step_text(step: Any) -> str:
    """The full text of one step. May contain newlines (multi-line calcs and comments)."""
    name = _get(step, "name") or ""
    params = _get(step, "params") or []
    if name == COMMENT_STEP:
        comment = next((p.get("text") for p in params if p.get("kind") == "comment"), None)
        if comment is None and not params:
            return _get(step, "raw_text") or name
        lines = _NEWLINES.split(comment or "")
        return "\n".join(f"# {ln}".rstrip() for ln in lines) if comment else ""
    if not params:
        return _get(step, "raw_text") or name
    parts = [p for p in (format_param(step, item) for item in params) if p]
    return f"{name} [ {' ; '.join(parts)} ]" if parts else name


def script_lines(steps: Iterable[Any]) -> list[StepLine]:
    """Each step's text with its block depth (If / Loop / Open Transaction nesting)."""
    out: list[StepLine] = []
    depth = 0
    for step in steps:
        name = _get(step, "name") or ""
        if name in _CLOSES or name in _CONTINUES:
            depth = max(depth - 1, 0)
        text = step_text(step)
        out.append(StepLine(
            number=int(_get(step, "index", 0) or 0) + 1,
            depth=depth,
            enabled=bool(_get(step, "enabled", True)),
            lines=_NEWLINES.split(text) if text else [""],
        ))
        if name in _OPENS or name in _CONTINUES:
            depth += 1
    return out


def render_script_block(steps: Iterable[Any], indent: str = "    ") -> str:
    """A script's steps as plain text: step numbers, indented blocks, ``//`` on disabled steps.

    Continuation lines of a multi-line step line up under the start of its text.
    """
    lines = script_lines(steps)
    width = len(str(max((ln.number for ln in lines), default=0)))
    rendered: list[str] = []
    for ln in lines:
        lead = indent * ln.depth + ("" if ln.enabled else "// ")
        rendered.append(f"{ln.number:>{width}}  {lead}{ln.lines[0]}".rstrip())
        pad = " " * (width + 2) + " " * len(lead) + indent
        rendered.extend(f"{pad}{cont}".rstrip() for cont in ln.lines[1:])
    return "\n".join(rendered)


def code_fence(content: str) -> str:
    """A backtick fence longer than any backtick run inside ``content``."""
    longest = max((len(m) for m in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)
