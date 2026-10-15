"""A tolerant parser for FileMaker calculations, for name tracing (analyze/indirection.py).

It is not a FileMaker evaluator. It only needs to see the shape of a calculation:
string literals, ``&`` concatenation, function calls and their ``;`` arguments,
variables, field references (``Table::Field``, names may contain spaces), ``Let``
bindings, ``[ ... ]`` brackets and comparisons. Anything else becomes an ``Other``
node that still carries its children, so a sink nested anywhere is still found.

Built on the lossless lexer used by scrubbing (``scrub/calc_lexer.py``): comments
never produce nodes, and string contents are never mistaken for names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator, Optional, Union

from ..scrub.calc_lexer import COMMENT, NAME, NUMBER, OP, STRING, VAR, WS, Token, tokenize

_WORD_OPS = {"and", "or", "not", "xor"}
_COMPARE_CHARS = set("<>=≤≥≠")
# Characters that end a field name written after "::" (anything else, spaces included, is part of it)
_FIELD_STOP = set(";()&=≠<>≤≥+-*/^[]¶,{}\"")


@dataclass(eq=False)
class Node:
    start: int
    end: int

    def children(self) -> list["Node"]:
        return []


@dataclass(eq=False)
class Str(Node):
    value: str = ""


@dataclass(eq=False)
class Num(Node):
    text: str = ""


@dataclass(eq=False)
class Var(Node):
    name: str = ""


@dataclass(eq=False)
class Name(Node):
    """A bare identifier: a Let variable, a custom function parameter, a field of the current table."""
    name: str = ""


@dataclass(eq=False)
class FieldRef(Node):
    table: str = ""
    field: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.table}::{self.field}"


@dataclass(eq=False)
class Call(Node):
    name: str = ""
    args: list[Node] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.name.casefold()

    def children(self) -> list[Node]:
        return list(self.args)


@dataclass(eq=False)
class Concat(Node):
    parts: list[Node] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.parts)


@dataclass(eq=False)
class Bin(Node):
    """Terms joined by operators other than (only) ``&``: ``items`` alternates node, op, node, ..."""
    items: list[Union[Node, str]] = field(default_factory=list)

    def children(self) -> list[Node]:
        return [i for i in self.items if isinstance(i, Node)]

    def ops(self) -> list[str]:
        return [i for i in self.items if isinstance(i, str)]


@dataclass(eq=False)
class Bracket(Node):
    items: list[Node] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.items)


@dataclass(eq=False)
class Other(Node):
    parts: list[Node] = field(default_factory=list)

    def children(self) -> list[Node]:
        return list(self.parts)


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks = [t for t in tokenize(text) if t.kind != COMMENT]
        self.i = 0

    # -- token helpers (whitespace is skipped by peek / take, but kept for field names) --
    def _skip_ws(self) -> None:
        while self.i < len(self.toks) and self.toks[self.i].kind == WS:
            self.i += 1

    def peek(self) -> Optional[Token]:
        self._skip_ws()
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> Token:
        self._skip_ws()
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def at_op(self, char: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == OP and tok.text == char

    def _end_pos(self) -> int:
        return self.toks[self.i - 1].end if self.i else 0

    # -- grammar --
    def parse(self) -> Node:
        nodes = []
        while self.peek() is not None:
            before = self.i
            nodes.append(self.expr())
            if self.i == before:  # stray ) ] ; at top level
                self.take()
        if len(nodes) == 1:
            return nodes[0]
        start = nodes[0].start if nodes else 0
        return Other(start, len(self.text), parts=nodes)

    def expr(self) -> Node:
        first = self.term()
        items: list[Union[Node, str]] = [first]
        while True:
            op = self._binary_op()
            if op is None:
                break
            items.append(op)
            items.append(self.term())
        if len(items) == 1:
            return first
        start = first.start
        end = self._end_pos()
        if all(op == "&" for op in items[1::2]):
            return Concat(start, end, parts=[n for n in items[0::2]])
        return Bin(start, end, items=items)

    def _binary_op(self) -> Optional[str]:
        tok = self.peek()
        if tok is None:
            return None
        if tok.kind == NAME and tok.text.casefold() in ("and", "or", "xor"):
            self.take()
            return tok.text.casefold()
        if tok.kind != OP or tok.text in "();[]{}":
            return None
        self.take()
        op = tok.text
        if op in _COMPARE_CHARS:
            nxt = self.peek()
            while nxt is not None and nxt.kind == OP and nxt.text in _COMPARE_CHARS and nxt.start == self._end_pos():
                op += self.take().text
                nxt = self.peek()
        return op

    def term(self) -> Node:
        tok = self.peek()
        if tok is None:
            return Other(len(self.text), len(self.text))
        if tok.kind == STRING:
            self.take()
            return Str(tok.start, tok.end, value=_unquote(tok.text))
        if tok.kind == NUMBER:
            self.take()
            return Num(tok.start, tok.end, text=tok.text)
        if tok.kind == VAR:
            self.take()
            node = Var(tok.start, tok.end, name=tok.text)
            self._repetition()
            return node
        if tok.kind == OP and tok.text == "(":
            self.take()
            inner = self.expr()
            while self.peek() is not None and not self.at_op(")"):
                before = self.i
                self.expr()
                if self.i == before:
                    self.take()
            if self.at_op(")"):
                self.take()
            return inner
        if tok.kind == OP and tok.text == "[":
            return self._bracket()
        if tok.kind == OP and tok.text in "-+":
            self.take()
            inner = self.term()
            return Other(tok.start, inner.end, parts=[inner])
        if tok.kind == NAME and tok.text.casefold() == "not":
            self.take()
            inner = self.term()
            return Other(tok.start, inner.end, parts=[inner])
        if tok.kind == OP and tok.text in "#@":
            nxt_i = self.i + 1
            if nxt_i < len(self.toks) and self.toks[nxt_i].kind == NAME:
                self.take()
                name_tok = self.take()
                return self._after_name(tok.start, tok.text + name_tok.text)
        if tok.kind == NAME:
            field_ref = self._field_ref()
            if field_ref is not None:
                return field_ref
            self.take()
            return self._after_name(tok.start, tok.text)
        if tok.kind == OP and tok.text in ");]":
            return Other(tok.start, tok.start)  # caller handles the closer
        self.take()
        return Other(tok.start, tok.end)

    def _after_name(self, start: int, name: str) -> Node:
        if self.at_op("("):
            self.take()
            args: list[Node] = []
            if self.at_op(")"):
                self.take()
                return Call(start, self._end_pos(), name=name, args=args)
            while True:
                args.append(self.expr())
                if self.at_op(";"):
                    self.take()
                    continue
                if self.at_op(")"):
                    self.take()
                    break
                if self.peek() is None:
                    break
                self.take()  # unexpected token inside the call: skip it
            return Call(start, self._end_pos(), name=name, args=args)
        node = Name(start, self._end_pos(), name=name)
        self._repetition()
        return node

    def _bracket(self) -> Node:
        start = self.take().start
        items: list[Node] = []
        while self.peek() is not None and not self.at_op("]"):
            before = self.i
            items.append(self.expr())
            if self.at_op(";"):
                self.take()
            elif self.i == before:
                self.take()
        if self.at_op("]"):
            self.take()
        return Bracket(start, self._end_pos(), items=items)

    def _repetition(self) -> None:
        """Drop ``[n]`` right after a variable or field (no whitespace needed)."""
        if self.at_op("["):
            self._bracket()

    def _field_ref(self) -> Optional[FieldRef]:
        """``Table name::Field name`` starting at the current NAME token, or None."""
        self._skip_ws()
        j = self.i
        toks = self.toks
        # table half: NAME / NUMBER / WS tokens up to "::"
        while j < len(toks) and (toks[j].kind in (NAME, NUMBER, WS)):
            if toks[j].kind == NAME and toks[j].text.casefold() in _WORD_OPS and j != self.i:
                return None
            j += 1
        if not (j + 1 < len(toks) and toks[j].kind == OP and toks[j].text == ":"
                and toks[j + 1].kind == OP and toks[j + 1].text == ":"):
            return None
        table = self.text[toks[self.i].start:toks[j].start].strip()
        k = j + 2
        end = k
        while k < len(toks):
            tok = toks[k]
            if tok.kind in (STRING, VAR):
                break
            if tok.kind == OP and (tok.text in _FIELD_STOP or tok.text in _COMPARE_CHARS):
                break
            if tok.kind == NAME and tok.text.casefold() in _WORD_OPS:
                break
            k += 1
            if tok.kind != WS:
                end = k
        if end == j + 2:
            return None
        start_pos = toks[self.i].start
        end_pos = toks[end - 1].end
        self.i = end
        node = FieldRef(start_pos, end_pos, table=table, field=self.text[toks[j + 2].start:end_pos].strip())
        self._repetition()
        return node


def _unquote(token_text: str) -> str:
    """A STRING token's value: no quotes, ``\\"`` -> ``"``, ``\\\\`` -> ``\\``, ``¶`` -> newline."""
    inner = token_text[1:-1] if len(token_text) >= 2 and token_text.endswith('"') else token_text[1:]
    out = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            out.append(inner[i + 1])
            i += 2
            continue
        out.append("\n" if ch == "¶" else ch)
        i += 1
    return "".join(out)


@lru_cache(maxsize=20000)
def parse(text: str) -> Node:
    return _Parser(text).parse()


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children()))


def let_bindings(call: Call) -> list[tuple[str, Node]]:
    """``(name, expression)`` for each binding of a ``Let`` call, in order."""
    if not call.args:
        return []
    decl = call.args[0]
    items = decl.items if isinstance(decl, Bracket) else [decl]
    out = []
    for item in items:
        if isinstance(item, Bin) and len(item.items) >= 3 and item.items[1] == "=":
            target = item.items[0]
            name = target.name if isinstance(target, (Var, Name)) else None
            if name:
                rest = item.items[2:]
                value = rest[0] if len(rest) == 1 else _rebuild(rest)
                out.append((name, value))
    return out


def _rebuild(items: list) -> Node:
    nodes = [i for i in items if isinstance(i, Node)]
    start, end = nodes[0].start, nodes[-1].end
    if all(op == "&" for op in items[1::2]):
        return Concat(start, end, parts=nodes)
    return Bin(start, end, items=list(items))
