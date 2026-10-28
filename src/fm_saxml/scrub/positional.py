"""Credentials passed as function arguments, identified by the function, not the value.

``JSONSetElement ( $j ; "apiKey" ; "zK9m…" ; JSONString )``, ``CryptEncrypt ( data ; key )``
and ``MBS ( "CURL.SetOptionPassword" ; $curl ; $pw )`` carry a secret in a fixed position
that no keyword or key shape reveals. Each argument is classified as a literal (redact it),
a variable (trace it back to where it was set), a field reference (flag it: the secret lives
in data, not in this file) or an expression (redact its literals).

A plugin function exported without its plugin installed is written as
``<Function Missing> ( "smtp.example.com" ; 587 ; "user@example.com" ; "pw" )``: the name
is gone, so no argument position is known. Every string argument is treated as a possible
secret, except those shaped like a number, email, hostname or plain URL; those are left to
the level's own detectors (``[EMAIL#n]``, ``[HOST#n]``), which keeps the call readable.

Function list adapted from the FileMaker XML Scrubber (Andrew Kear, CC BY 4.0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .calc_lexer import COMMENT, NAME, OP, STRING, VAR, WS, Token
from .policy import ScrubPolicy, category_from_name

# Built-in functions whose key argument (zero-based) is the secret itself.
CRYPT_KEY_ARGS = {
    "cryptencrypt": (1,), "cryptdecrypt": (1,),
    "cryptencryptbase64": (1,), "cryptdecryptbase64": (1,),
    "cryptauthcode": (2,),
    "cryptgeneratesignature": (2, 3),  # private key, key password
}
# MBS("<selector>"; …): selectors that *set* a secret pass it as the last argument.
_MBS_SECRET_SELECTOR_RE = re.compile(r"password|passphrase|bearer|token|secret|api_?key|privatekey|licen[cs]e", re.I)
_PLUGIN_REGISTER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_Register$")
_PREFILTER_RE = re.compile(r"JSONSetElement|Crypt|MBS|_Register|Missing\s*>", re.I)

MISSING_FUNCTION = "missing_function"
# Argument shapes that describe where a secret goes rather than being one.
_NOT_SECRET_SHAPE_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?"                                           # number
    r"|[^\s@\"]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"                 # email
    r"|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?"                   # hostname
    r"|\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?"                            # IPv4
    r"|[a-z][a-z0-9+.-]*://[^\s@?#\"]+",                            # URL without userinfo or query
    re.I,
)


def secret_shaped(value: str) -> bool:
    """Whether a ``<Function Missing>`` string argument could be the secret."""
    return not _NOT_SECRET_SHAPE_RE.fullmatch(value.strip())


@dataclass
class Call:
    name: str
    args: list[list[Token]]  # significant tokens of each argument


@dataclass
class Use:
    """A credential-bearing argument and what kind of thing it is."""

    kind: str               # literal | expr | var | field | name
    tokens: list[Token]
    category: str
    detector: str
    via: str                # human description, e.g. 'CryptEncrypt key'

    @property
    def ref(self) -> str:
        return "".join(t.text for t in self.tokens)


def _code_tokens(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.kind not in (WS, COMMENT)]


def find_calls(tokens: list[Token]) -> list[Call]:
    """Every ``Name ( a ; b ; … )`` call, nested ones included. ``[k ; v]`` groups stay one argument.

    A ``<Function Missing> ( … )`` call is named ``<Function Missing>``.
    """
    sig = _code_tokens(tokens)
    calls = []
    for i in range(len(sig) - 1):
        if sig[i + 1].kind != OP or sig[i + 1].text != "(":
            continue
        if sig[i].kind == NAME:
            name = sig[i].text
        else:
            name = _missing_marker(sig, i)
            if name is None:
                continue
        args: list[list[Token]] = []
        cur: list[Token] = []
        depth = 0
        for tok in sig[i + 1:]:
            if tok.kind == OP and tok.text in "([":
                depth += 1
                if depth == 1:
                    continue
            elif tok.kind == OP and tok.text in ")]":
                depth -= 1
                if depth == 0:
                    break
            elif tok.kind == OP and tok.text in ";," and depth == 1:
                args.append(cur)
                cur = []
                continue
            cur.append(tok)
        args.append(cur)
        calls.append(Call(name, args))
    return calls


def _missing_marker(sig: list[Token], i: int) -> Optional[str]:
    """``<Function Missing>`` ending at ``sig[i]`` (the ``>``), as one name."""
    if sig[i].text != ">" or i < 2 or sig[i - 1].kind != NAME or sig[i - 1].text.lower() != "missing":
        return None
    j = i - 2
    while j >= 0 and sig[j].kind == NAME:
        j -= 1
    if j < 0 or j == i - 2 or sig[j].text != "<":
        return None
    return "<" + " ".join(t.text for t in sig[j + 1:i]) + ">"


def classify(tokens: list[Token]) -> str:
    toks = _code_tokens(tokens)
    if not toks:
        return "empty"
    if len(toks) == 1 and toks[0].kind == STRING:
        return "literal"
    if toks[0].kind == VAR and (len(toks) == 1 or (toks[1].text == "[" and toks[-1].text == "]")):
        return "var"
    if len(toks) == 1 and toks[0].kind == NAME:
        return "name"
    if (len(toks) == 4 and toks[0].kind == NAME and toks[1].text == ":" and toks[2].text == ":"
            and toks[3].kind == NAME):
        return "field"
    return "expr"


def string_content(tok: Token, text: str) -> str:
    start, end = tok.content_span
    return text[start:end]


def _group(tokens: list[Token]) -> Optional[list[list[Token]]]:
    """Split a ``[ key ; value ; type ]`` argument into its parts."""
    if len(tokens) < 2 or tokens[0].text != "[" or tokens[-1].text != "]":
        return None
    parts: list[list[Token]] = [[]]
    depth = 0
    for tok in tokens[1:-1]:
        if tok.kind == OP and tok.text in "([":
            depth += 1
        elif tok.kind == OP and tok.text in ")]":
            depth -= 1
        elif tok.kind == OP and tok.text in ";," and depth == 0:
            parts.append([])
            continue
        parts[-1].append(tok)
    return parts


def credential_uses(tokens: list[Token], text: str, policy: ScrubPolicy) -> list[Use]:
    if not _PREFILTER_RE.search(text):
        return []
    uses: list[Use] = []
    for call in find_calls(tokens):
        lname = call.name.lower()
        args = call.args

        if lname == "jsonsetelement":
            pairs = []
            groups = [g for g in (_group(a) for a in args[1:]) if g]
            if groups:
                pairs = [(g[0], g[1]) for g in groups if len(g) >= 2]
            elif len(args) >= 3:
                pairs = [(args[1], args[2])]
            for key, value in pairs:
                if classify(key) != "literal":
                    continue
                key_name = string_content(_code_tokens(key)[0], text)
                if policy.is_credential_name(key_name):
                    uses.append(Use(classify(value), value, category_from_name(key_name), "json_set_element",
                                    f'JSONSetElement key "{key_name}"'))

        elif lname in CRYPT_KEY_ARGS:
            for idx in CRYPT_KEY_ARGS[lname]:
                if idx < len(args):
                    uses.append(Use(classify(args[idx]), args[idx], "secret", "crypt_key", f"{call.name} key"))

        elif lname == "mbs" and args and classify(args[0]) == "literal":
            selector = string_content(_code_tokens(args[0])[0], text)
            if selector.lower() == "register":
                for a in args[1:]:
                    uses.append(Use(classify(a), a, "license", "plugin_register", 'MBS("Register")'))
            elif len(args) >= 2 and _MBS_SECRET_SELECTOR_RE.search(selector) and ".get" not in selector.lower():
                category = "license" if re.search(r"licen[cs]e", selector, re.I) else category_from_name(selector)
                uses.append(Use(classify(args[-1]), args[-1], category, "mbs_credential", f'MBS("{selector}")'))

        elif _PLUGIN_REGISTER_RE.match(call.name):
            for a in args:
                uses.append(Use(classify(a), a, "license", "plugin_register", call.name))

        elif call.name.startswith("<"):
            for a in args:
                uses.append(Use(classify(a), a, "secret", MISSING_FUNCTION, call.name))
    return uses


def local_assignment(tokens: list[Token], name: str) -> Optional[Token]:
    """The STRING assigned to ``name`` inside this calc (``Let ( $pw = "x" ; … )``), if any."""
    sig = _code_tokens(tokens)
    target = name.lower()
    for i in range(len(sig) - 2):
        if (sig[i].kind in (VAR, NAME) and sig[i].text.lower() == target and sig[i + 1].text == "="
                and sig[i + 2].kind == STRING):
            return sig[i + 2]
    return None
