"""What gets redacted and what survives, per detector.

Most cases are ported from the FileMaker XML Scrubber's test corpus
(https://github.com/andykear/FileMaker-XML-scrubber, CC BY 4.0).
"""

import pytest

from fm_saxml.scrub import PLACEHOLDER_RE, ScrubLevel, ScrubPolicy, Scrubber

from .fake_keys import (
    AWS_KEY_ID, GITHUB, JWT, JWT_HEADER, OPENAI, OTTO_ADMIN, OTTO_DATA, SLACK_WEBHOOK, SLACK_WEBHOOK_PATH,
    STRIPE_SHAPED_NAME,
)


def calc(text, **policy):
    return Scrubber(ScrubPolicy(**policy)).scrub_calc(text)


def text(value, **policy):
    return Scrubber(ScrubPolicy(**policy)).scrub_text(value)


# (calc, secrets that must disappear, context that must survive)
CALC_CASES = [
    pytest.param(
        r'''"--data '{\"username\":\"svc_integration\",\"password\":\"hunter2json\"}'"''',
        ["hunter2json"], ["svc_integration", r'\"password\":\"'], id="json-escaped-body"),
    pytest.param(f'"Authorization: Bearer " & "{OTTO_DATA}"', [OTTO_DATA], ["Authorization: Bearer"], id="ottofms-data-key"),
    pytest.param(f'"{OTTO_ADMIN}"', [OTTO_ADMIN], [], id="ottofms-admin-key"),
    pytest.param(f'Let([ $eq = 1 ; $password = "eqformpw333" ; $k = "{OPENAI}" ]; $k)',
                 ["eqformpw333", OPENAI], ["$password =", "$eq = 1", "]; $k)"], id="let-assignments"),
    pytest.param('smtp_pass = "plainword"', ["plainword"], ["smtp_pass ="], id="let-local-no-dollar"),
    pytest.param('/* $apikey = "commentedOut1" */ 1', ["commentedOut1"], ["$apikey ="], id="commented-out-code"),
    pytest.param('"-H \\"Authorization: Bearer abc.def.ghi\\""', ["abc.def.ghi"], ["Authorization: Bearer"], id="curl-escaped-header"),
    pytest.param('"--header \\"X-API-Key: k3yk3yk3y\\""', ["k3yk3yk3y"], ["X-API-Key"], id="api-key-header"),
    pytest.param('"Cookie: session=abcdef123456"', ["abcdef123456"], ["Cookie:"], id="cookie"),
    pytest.param('"--user svc_bot:Sup3rS3cret"', ["Sup3rS3cret"], ["svc_bot"], id="curl-user"),
    pytest.param('"https://bob:s3cr3tpw@api.example.com/x"', ["s3cr3tpw"], ["bob", "api.example.com"], id="url-userinfo"),
    pytest.param('"https://api.example.com/v1?api_key=abc123&page=2"', ["abc123"], ["page=2", "api.example.com"], id="query-param"),
    pytest.param('"Server=db;Uid=sa;Pwd=Hunter22;"', ["Hunter22"], ["Uid=sa"], id="connection-string"),
    pytest.param('"DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=bXlrZXk=;"', ["bXlrZXk="], ["AccountName=acct"], id="azure-account-key"),
    pytest.param('"Basic YWRtaW46aHVudGVyMg=="', ["YWRtaW46aHVudGVyMg=="], ["Basic"], id="base64-userpass"),
    pytest.param(f'"{JWT}"', [JWT_HEADER], [], id="jwt"),
    pytest.param(f'"{SLACK_WEBHOOK}"', [SLACK_WEBHOOK_PATH], ["hooks.slack.com"], id="slack-webhook"),
    pytest.param(f'"{AWS_KEY_ID}"', [AWS_KEY_ID], [], id="aws-key-id"),
    pytest.param(f'"{GITHUB}"', [GITHUB], [], id="github-token"),
    pytest.param('"-----BEGIN RSA PRIVATE KEY-----¶" & "MIIEowIBAAKCAQEA" & "¶-----END RSA PRIVATE KEY-----"',
                 ["MIIEowIBAAKCAQEA", "BEGIN RSA"], [" & "], id="pem-split-literals"),
    # standard level
    pytest.param('"fmnet:/fms.corp.local/CRM"', ["fms.corp.local"], ["fmnet:/", "/CRM"], id="fmnet-host"),
    pytest.param('"filewin://nas01.internal/share/file.txt"', ["nas01.internal"], ["/share/file.txt"], id="filewin-unc"),
    pytest.param('"\\\\\\\\SERVER01\\\\backups\\\\x"', ["SERVER01"], ["backups"], id="unc-path"),
    pytest.param('"/Users/jsmith/Desktop/out.csv"', ["jsmith"], ["/Users/", "/Desktop/out.csv"], id="mac-home"),
    pytest.param('"C:\\\\Users\\\\jsmith\\\\x"', ["jsmith"], ["Users"], id="windows-home"),
    pytest.param('"http://10.0.0.5:8080/x"', ["10.0.0.5"], [":8080/x"], id="private-ip"),
    pytest.param('"user:" & $pw & "@fms.corp.local/api"', ["fms.corp.local"], ["/api"], id="bare-internal-host"),
    pytest.param('"jane@intranet.corp"', ["jane@intranet.corp", "jane"], [], id="email-at-internal-host"),
    pytest.param('"cust: jane.doe@example.com"', ["jane.doe@example.com"], ["cust:"], id="email"),
    pytest.param('"mailto:jane.doe@example.com"', ["jane.doe@example.com"], ["mailto:"], id="mailto"),
    pytest.param('"card 4111 1111 1111 1111"', ["4111 1111 1111 1111"], ["card"], id="card-luhn"),
]


@pytest.mark.parametrize("source,gone,kept", CALC_CASES)
def test_calc_redaction(source, gone, kept):
    out = calc(source)
    for secret in gone:
        assert secret not in out
    for context in kept:
        assert context in out
    assert PLACEHOLDER_RE.search(out)


SURVIVES = [
    pytest.param('"https://api.example.com/v2/ok"', id="public-url"),
    pytest.param('"notcard 4111 1111 1111 1112"', id="fails-luhn"),
    pytest.param('"eyJhbGciOiJIUzI1NiJ9"', id="lone-jwt-segment"),
    pytest.param('"task-management-dashboard-config"', id="sk-inside-a-word"),
    pytest.param('$tokenUrl = "https://auth.example.com/token"', id="token-url-name"),
    pytest.param('$passwordHint = "first pet"', id="password-hint-name"),
    pytest.param('$token = "Bearer "', id="bare-auth-scheme"),
    pytest.param('_searchToken = "¶" & _label', id="delimiter-in-token-named-local"),
    pytest.param('$tokenSep = "|"', id="short-separator"),
    pytest.param('Get ( AccountName ) & "admin@"', id="not-an-email"),
    pytest.param('"version 10.2.3"', id="three-part-version"),
    pytest.param('"255.255.255.0"', id="netmask"),
    pytest.param('"http://localhost:3000"', id="localhost"),
    pytest.param('"filemac:/Macintosh HD/Shared/x"', id="file-volume-not-host"),
    pytest.param('Users::Password & $password', id="references-in-code"),
    pytest.param('"C:\\\\Users\\\\Public\\\\x"', id="public-home"),
]


@pytest.mark.parametrize("source", SURVIVES)
def test_not_redacted(source):
    assert calc(source) == source


def test_code_outside_literals_is_never_touched():
    # A field literally named like a key, outside any string, stays.
    source = f'{STRIPE_SHAPED_NAME} & "x"'
    assert calc(source) == source


def test_plain_json_form_in_free_text():
    out = text('{"client_secret": "abc123xyz", "token_type": "Bearer"}')
    assert "abc123xyz" not in out
    assert '"token_type": "Bearer"' in out


def test_secrets_level_keeps_hosts_and_emails():
    source = f'"https://intranet.corp/x" & "jane@example.org" & "{OPENAI}"'
    out = calc(source, level=ScrubLevel.SECRETS)
    assert "intranet.corp" in out and "jane@example.org" in out
    assert OPENAI not in out


def test_strict_level_redacts_random_literals():
    random = '"Zx8Qw2Lp9Rt4Vb7Nm1Kc3Hd6"'
    assert calc(random) == random
    assert "Zx8Qw2Lp9Rt4Vb7Nm1Kc3Hd6" not in calc(random, level=ScrubLevel.STRICT)
    uuid = '"A1B2C3D4-0001-0001-0001-000000000101"'
    assert calc(uuid, level=ScrubLevel.STRICT) == uuid


def test_extra_keyword():
    source = '$licence = "ABCD-1234"'
    assert calc(source) == source
    assert "ABCD-1234" not in calc(source, extra_keywords=["licence"])


def test_allow_pattern():
    source = '"https://bob:s3cr3tpw@api.example.com/x"'
    assert calc(source, allow_patterns=["s3cr3tpw"]) == source


def test_invalid_allow_pattern_is_a_clear_error():
    with pytest.raises(ValueError, match="--scrub-allow"):
        ScrubPolicy(allow_patterns=["("])


def test_no_key_shaped_literals_in_the_repo():
    """Fake keys live in fake_keys.py, split at the prefix. A complete key shape in the
    source would get the push blocked by secret scanning, however fake it is."""
    import re
    from pathlib import Path

    from fm_saxml.scrub.detectors.known_keys import KNOWN_KEYS

    root = Path(__file__).resolve().parents[1]
    patterns = [(det, re.compile(p)) for det, p, _ in KNOWN_KEYS]
    files = [*root.joinpath("src").rglob("*.py"), *root.joinpath("tests").rglob("*.py"),
             *root.joinpath("tests").rglob("*.xml"), *root.glob("*.md")]
    hits = [
        f"{path.relative_to(root)}:{n}: {det}"
        for path in files
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
        for det, pattern in patterns
        if pattern.search(line)
    ]
    assert not hits, "Key-shaped literal(s); build them in tests/fake_keys.py instead:\n" + "\n".join(hits)
