"""Scrubber invariants and whole-model runs."""

import random

import pytest

from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.scrub import PLACEHOLDER_RE, PlaceholderRegistry, ScrubLevel, ScrubPolicy, Scrubber
from fm_saxml.scrub.calc_lexer import COMMENT, STRING, tokenize

from .fake_keys import OPENAI, OPENAI_OTHER

from .test_scrub_detectors import CALC_CASES, SURVIVES

SOURCES = [p.values[0] for p in CALC_CASES] + [p.values[0] for p in SURVIVES]


def _skeleton(calc: str) -> list[tuple[str, str]]:
    """The token stream with string / comment contents blanked out."""
    return [(t.kind, "" if t.kind in (STRING, COMMENT) else t.text) for t in tokenize(calc)]


def _mixed_calcs(n=200, seed=7):
    rng = random.Random(seed)
    for _ in range(n):
        parts = rng.sample(SOURCES, k=rng.randint(1, 4))
        yield rng.choice([" & ", " ; ", "\n", " // trailing\n"]).join(parts)


@pytest.mark.parametrize("source", SOURCES + list(_mixed_calcs()))
def test_only_string_and_comment_contents_change(source):
    out = Scrubber().scrub_calc(source)
    assert _skeleton(out) == _skeleton(source)


@pytest.mark.parametrize("source", SOURCES + list(_mixed_calcs(50, seed=3)))
def test_scrubbing_is_idempotent(source):
    s = Scrubber()
    once = s.scrub_calc(source)
    assert s.scrub_calc(once) == once


def test_same_value_same_placeholder_everywhere():
    s = Scrubber()
    a = s.scrub_calc(f'$apikey = "{OPENAI}"')
    b = s.scrub_calc(f'"Bearer {OPENAI}"')
    c = s.scrub_calc(f'"{OPENAI_OTHER}"')
    ph = PLACEHOLDER_RE.search(a).group()
    assert ph in b
    assert ph not in c


def test_shared_registry_spans_scrubbers():
    registry = PlaceholderRegistry()
    a = Scrubber(registry=registry).scrub_calc(f'"{OPENAI}"')
    b = Scrubber(registry=registry).scrub_calc(f'"{OPENAI}"')
    assert a == b


def _raw() -> RawModel:
    raw = RawModel(file_name="t.xml")
    raw.tables = [{"id": "1", "name": "Users"}]
    raw.fields = [{
        "id": "1", "name": "Password", "table_name": "Users",
        "comment": "Owner: jane.doe@example.com", "uuid": "A1B2C3D4-0001-0001-0001-000000000101",
        "modified": {"user_name": "Jane Doe", "account_name": "jdoe", "timestamp": "2026-01-01T00:00:00"},
    }]
    calc = '$password = "Hunter2Secret!" ; "and again Hunter2Secret! here" & "' + "x" * 80 + '"'
    raw.scripts = [{
        "id": "1", "name": "Login",
        "steps": [
            {"step_type_id": "141", "index": 0, "name": "Set Variable", "calculation": calc,
             "calculations": [{"text": calc, "parameter": "Variable"}],
             "raw_text": f"Set Variable [ {calc[:80]} ]", "field_refs": []},
            {"step_type_id": "89", "index": 1, "name": "Show Custom Dialog",
             "calculation": '"Call Hunter2Secret! support"',
             "calculations": [{"text": '"Call Hunter2Secret! support"'}],
             "raw_text": "Show Custom Dialog [ Login ]", "field_refs": []},
        ],
    }]
    raw.accounts = [{"id": "1", "name": "jdoe"}, {"id": "2", "name": "[Guest]"}]
    raw.value_lists = [{"id": "1", "name": "Hosts", "values": ["fms.corp.local", "Public"]}]
    return raw


def test_raw_model_scrub_reaches_every_copy():
    raw = _raw()
    summary = Scrubber().scrub_raw(raw)
    step = raw.scripts[0]["steps"][0]
    assert "Hunter2Secret!" not in step["calculation"]
    assert "Hunter2Secret!" not in step["calculations"][0]["text"]
    # raw_text is re-derived from the scrubbed calc, not left holding the truncated original
    assert step["raw_text"].startswith("Set Variable [ $password = \"[REDACTED:password#1]\"")
    assert "Hunter2Secret" not in step["raw_text"]
    # pass 2: the same value elsewhere is replaced too
    assert raw.scripts[0]["steps"][1]["calculation"] == '"Call [REDACTED:password#1] support"'
    assert raw.fields[0]["comment"] == "Owner: [EMAIL#1]"
    assert raw.value_lists[0]["values"] == ["[HOST#1]", "Public"]
    # names and ids untouched; modified-by names kept below strict
    assert raw.fields[0]["name"] == "Password"
    assert raw.fields[0]["modified"]["user_name"] == "Jane Doe"
    assert raw.accounts[0]["name"] == "jdoe"
    assert summary.applied and summary.counts == {"email": 1, "host": 1, "password": 1}


def test_findings_never_contain_values():
    raw = _raw()
    summary = Scrubber().scrub_raw(raw)
    blob = summary.model_dump_json()
    for secret in ("Hunter2Secret", "jane.doe@example.com", "fms.corp.local"):
        assert secret not in blob
    locations = {f.location for f in summary.findings}
    assert "Script 'Login' › Step 1: Set Variable" in locations  # index 0 is step 1, as on the page
    assert "Field Users::Password" in locations


def test_strict_scrubs_people_but_not_builtin_accounts():
    raw = _raw()
    Scrubber(ScrubPolicy(level=ScrubLevel.STRICT)).scrub_raw(raw)
    assert raw.fields[0]["modified"]["user_name"] == "[PERSON#1]"
    assert raw.accounts[0]["name"] == "[PERSON#2]"
    assert raw.accounts[1]["name"] == "[Guest]"


def test_model_json_scrub():
    data = {
        "schemaVersion": "0.1.0",
        "source": {"fileName": "C:\\Users\\jsmith\\exports\\App.xml"},
        "entities": {"scriptSteps": {"s1": {
            "name": "Set Variable", "rawText": 'Set Variable [ $token = "abc123token" ]',
            "calculation": '$token = "abc123token"', "calculations": [{"text": '$token = "abc123token"'}],
        }}},
    }
    summary = Scrubber().scrub_model_data(data)
    step = data["entities"]["scriptSteps"]["s1"]
    assert "abc123token" not in str(step)
    assert data["source"]["fileName"] == "C:\\Users\\[USER#1]\\exports\\App.xml"
    assert data["scrubbing"]["applied"] is True
    assert {f.category for f in summary.findings} == {"token", "user"}


def test_guard_values_exclude_ordinary_words():
    s = Scrubber()
    s.scrub_calc('$password = "password" ; $pwd = "Xy7#kL9!m"')
    values = s.guard_values()
    assert "password" not in values  # too ordinary to hunt for everywhere
    assert "Xy7#kL9!m" in values
