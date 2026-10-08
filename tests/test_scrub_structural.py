"""Phase 2 scrubbing: structural rules, positional arguments, variable tracing, prose in comments."""

import json

import pytest
from lxml import etree

from fm_saxml.parser.extractors.scripts import _parse_step
from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.scrub import ScrubPolicy, Scrubber

from .test_step_calculations import SET_VARIABLE


def calc(text):
    return Scrubber().scrub_calc(text)


# ---------------------------------------------------------------------------
# Positional arguments, within one calc
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,secret", [
    ('JSONSetElement ( "{}" ; "apiKey" ; "jsonapikey9999" ; JSONString )', "jsonapikey9999"),
    ('JSONSetElement ( $j ; ["user"; "svc"; JSONString] ; ["client_secret"; "bracketsecret1"; JSONString] )', "bracketsecret1"),
    ('CryptEncrypt ( Table::Blob ; "cryptkey456" )', "cryptkey456"),
    ('CryptAuthCode ( $data ; "SHA256" ; "myHMACkey123" )', "myHMACkey123"),
    ('MBS ( "CURL.SetOptionPassword" ; $curl ; "sftpPass" )', "sftpPass"),
    ('MBS ( "CURL.SetOptionXOAuth2Bearer" ; $curl ; "ya29.tokenvalue" )', "ya29.tokenvalue"),
    ('MBS ( "Register" ; "Jane Dev" ; "Complete" ; "Yearly" ; 202612 ; "LICKEY-1234" )', "LICKEY-1234"),
    ('BE_Register ( "LicenseeName" ; "BE-KEY-9876" )', "BE-KEY-9876"),
    ('Let ( $pw = "letlocal42" ; MBS ( "CURL.SetOptionPassword" ; $curl ; $pw ) )', "letlocal42"),
    ('Let ( ~k = "localkey77" ; CryptDecrypt ( $blob ; ~k ) )', "localkey77"),
])
def test_positional_credentials(source, secret):
    out = calc(source)
    assert secret not in out
    assert "[REDACTED:" in out


@pytest.mark.parametrize("source", [
    'JSONSetElement ( "{}" ; "username" ; "svc_integration" ; JSONString )',
    'JSONGetElement ( $parameter ; "password" )',
    'CryptAuthCode ( $data ; "SHA256" ; $key )',            # unresolved here, nothing to redact
    'MBS ( "CURL.GetPassword" ; $curl )',
    'MBS ( "JSON.GetPathItem" ; $j ; "token" )',
])
def test_positional_leaves_non_secrets(source):
    assert calc(source) == source


def test_mbs_register_keeps_selector():
    out = calc('MBS ( "Register" ; "Jane Dev" ; "LICKEY-1234" )')
    assert out.startswith('MBS ( "Register" ;')


# ---------------------------------------------------------------------------
# Structural rules and tracing over a whole model
# ---------------------------------------------------------------------------

def step(index, name, calcs, step_id, variable=None, field=None):
    """A step dict shaped like the parser's output."""
    entries = [{"text": t, "parameter": p, "slot": s, "position": i} for i, (p, s, t) in enumerate(calcs)]
    joined = "\n".join(e["text"] for e in entries) or None
    field_refs = [{"name": field, "table": "Users", "id": "1"}] if field else []
    raw_text = f"{name} [ Users::{field} ]" if field else f"{name} [ {joined[:80]} ]" if joined else name
    return {"step_type_id": step_id, "index": index, "name": name, "enabled": True, "raw_text": raw_text,
            "layout_ref": None, "field_refs": field_refs, "script_ref": None, "value_list_refs": [],
            "calculation": joined, "calculations": entries, "variable": variable}


def set_var(index, var, value, rep="1"):
    return step(index, "Set Variable", [("Variable", "value", value), ("Variable", "repetition", rep)], "141", var)


def run(*scripts, **policy):
    raw = RawModel(file_name="t.xml")
    raw.scripts = [{"id": str(i), "name": name, "steps": steps} for i, (name, steps) in enumerate(scripts)]
    summary = Scrubber(ScrubPolicy(**policy)).scrub_raw(raw)
    return raw, summary


def dump(raw) -> str:
    return json.dumps(raw.scripts)


def test_relogin_password_parameter_is_redacted_in_every_copy():
    relogin = step(0, "Re-Login", [("Name", None, '"CreateModify"'), ("Password", None, '"abc"')], "138")
    raw, summary = run(("Login", [relogin]))
    s = raw.scripts[0]["steps"][0]
    assert '"abc"' not in dump(raw)  # short value: only the structural rule can know
    assert s["calculations"][1]["text"] == '"[REDACTED:password#1]"'
    assert s["calculation"] == '"CreateModify"\n"[REDACTED:password#1]"'
    assert s["raw_text"] == 'Re-Login [ "CreateModify"\n"[REDACTED:password#1]" ]'
    assert s["calculations"][0]["text"] == '"CreateModify"'  # account name kept
    assert [f.detector for f in summary.redactions] == ["password_parameter"]


def test_credential_named_variable():
    raw, _ = run(("S", [set_var(0, "$apiKey", '"plainvalue"'), set_var(1, "$apiKeyUrl", '"https://x.io"')]))
    steps = raw.scripts[0]["steps"]
    assert steps[0]["calculations"][0]["text"] == '"[REDACTED:api_key#1]"'
    assert steps[0]["calculations"][1]["text"] == "1"  # repetition untouched
    assert steps[1]["calculations"][0]["text"] == '"https://x.io"'


def test_variable_built_by_a_function_keeps_its_key_names():
    raw, summary = run(("S", [set_var(0, "$password", 'JSONGetElement ( $parameter ; "password" )')]))
    assert raw.scripts[0]["steps"][0]["calculations"][0]["text"] == 'JSONGetElement ( $parameter ; "password" )'
    assert not summary.findings


def test_variable_traced_to_its_set_variable():
    use = step(1, "Set Variable", [("Variable", "value", 'MBS ( "CURL.SetOptionPassword" ; $curl ; $pw )')], "141", "$r")
    raw, summary = run(("S", [set_var(0, "$pw", '"tracedPw1"'), use]))
    assert "tracedPw1" not in dump(raw)
    assert any(f.detector == "mbs_credential_traced" for f in summary.redactions)


def test_trace_uses_the_nearest_earlier_assignment_only():
    use = step(2, "Set Variable", [("Variable", "value", 'CryptEncrypt ( $d ; $k )')], "141", "$r")
    raw, _ = run(("S", [set_var(0, "$k", '"oldKey111"'), set_var(1, "$k", '"newKey222"'), use, set_var(3, "$k", '"later333"')]))
    text = dump(raw)
    assert "newKey222" not in text
    assert "oldKey111" in text and "later333" in text


def test_global_traced_across_scripts():
    setup = ("Startup", [set_var(0, "$$cfg", '"globalPw77"')])
    use = ("Encrypt", [step(0, "Set Variable", [("Variable", "value", "CryptEncrypt ( $d ; $$cfg )")], "141", "$x")])
    raw, _ = run(setup, use)
    assert "globalPw77" not in dump(raw)


def test_unresolved_variable_and_field_reference_are_flagged():
    raw, summary = run(("S", [
        step(0, "Set Variable", [("Variable", "value", "CryptEncrypt ( $d ; $missing )")], "141", "$x"),
        step(1, "Re-Login", [("Name", None, '"svc"'), ("Password", None, "Users::Password")], "138"),
    ]))
    notes = [f.note for f in summary.flagged]
    assert any("$missing" in n and "no Set Variable" in n for n in notes)
    assert any("Users::Password" in n for n in notes)
    assert not summary.redactions


def test_set_field_into_credential_field():
    raw, _ = run(("S", [step(0, "Set Field", [("Calculation", None, '"temp123"')], "76", field="Password"),
                        step(1, "Set Field", [("Calculation", None, '"Active"')], "76", field="Status")]))
    steps = raw.scripts[0]["steps"]
    assert "temp123" not in dump(raw)
    assert steps[1]["calculations"][0]["text"] == '"Active"'


def test_set_field_by_name_with_credential_target():
    sfbn = step(0, "Set Field By Name", [("Calculation", None, '"Users::ApiKey"'), ("Calculation", None, '"zzz111"')], "147")
    raw, _ = run(("S", [sfbn]))
    texts = [c["text"] for c in raw.scripts[0]["steps"][0]["calculations"]]
    assert texts[0] == '"Users::ApiKey"' and "zzz111" not in texts[1]


def test_configure_ai_account():
    ai = step(0, "Configure AI Account", [("Calculation", None, '"myAccount"'), ("Calculation", None, '"plainKeyValue"')], "212")
    raw, _ = run(("S", [ai]))
    assert "plainKeyValue" not in dump(raw)


# ---------------------------------------------------------------------------
# Prose in comments
# ---------------------------------------------------------------------------

def test_prose_value_that_looks_secret_is_redacted():
    out = calc('/* temp password is swordfish99 until go-live */ 1')
    assert "swordfish99" not in out
    assert out.startswith("/* temp password is [REDACTED:password#")
    assert out.endswith(" until go-live */ 1")


def test_prose_plain_word_is_flagged_not_changed():
    raw, summary = run(("S", [set_var(0, "$x", "/* the admin password is marmalade */ 1")]))
    assert raw.scripts[0]["steps"][0]["calculations"][0]["text"] == "/* the admin password is marmalade */ 1"
    assert [f.detector for f in summary.flagged] == ["comment_review"]
    assert "marmalade" not in summary.model_dump_json()  # masked in the preview


@pytest.mark.parametrize("prose", [
    "/* password is required */ 1",
    "/* see the API key: Preferences::apiKey */ 1",
    '"Authorization: Bearer " & $token',
])
def test_ordinary_prose_is_left_alone(prose):
    raw, summary = run(("S", [set_var(0, "$x", prose)]))
    assert not summary.findings


# ---------------------------------------------------------------------------
# Names, parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,secret", [
    ("privateKey_g", True), ("$apiKey", True), ("SMTP_PASSWORD", True),
    ("tokenUri_g", False), ("oAuthScope_g", False), ("apiKey_id", False), ("$passwordHint", False),
])
def test_credential_names(name, secret):
    assert ScrubPolicy().is_credential_name(name) is secret


def test_parser_captures_set_variable_name():
    assert _parse_step(etree.fromstring(SET_VARIABLE), 0)["variable"] == "$x"
