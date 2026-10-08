"""Phase 3 scrubbing: fingerprint placeholders, strict PII, the allow marker, `fm-saxml scrub`."""

import difflib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.parser.saxml_reader import RawModel
from fm_saxml.scrub import PLACEHOLDER_RE, PlaceholderRegistry, ScrubLevel, ScrubPolicy, Scrubber
from fm_saxml.scrub import placeholders

from .fake_keys import OPENAI, OPENAI_PUBLIC, OPENAI_REAL

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
SALT = "a-private-salt-of-decent-length"


# ---------------------------------------------------------------------------
# Fingerprint placeholders
# ---------------------------------------------------------------------------

def test_fingerprints_are_stable_across_registries_with_the_same_salt():
    a = PlaceholderRegistry(SALT).placeholder("hunter2!", "password")
    b = PlaceholderRegistry(SALT).placeholder("hunter2!", "password")
    c = PlaceholderRegistry("another-private-salt-value").placeholder("hunter2!", "password")
    assert a == b != c
    assert PLACEHOLDER_RE.fullmatch(a)
    assert "hunter2" not in a


def test_fingerprint_prefix_collisions_get_longer_labels(monkeypatch):
    monkeypatch.setattr(placeholders, "_FINGERPRINT_LENGTH", 1)
    reg = PlaceholderRegistry(SALT)
    labels = [reg.placeholder(f"value-{i}", "password") for i in range(40)]
    assert len(set(labels)) == 40


def test_numbered_is_the_default_style():
    reg = PlaceholderRegistry()
    assert reg.placeholder("x" * 8, "password") == "[REDACTED:password#1]"
    assert reg.style == "numbered" and reg.salt_id is None


def test_fingerprint_scrub_is_idempotent():
    s = Scrubber(registry=PlaceholderRegistry(SALT))
    once = s.scrub_calc(f'$apikey = "{OPENAI}" ; "jane@example.com"')
    assert s.scrub_calc(once) == once


def _xml(tmp_path, password):
    xml = (FIXTURES / "small_sample_v2.xml").read_text(encoding="utf-8").replace(
        "<Calculation>Active</Calculation>", f'<Calculation><![CDATA[$password = "{password}"]]></Calculation>')
    path = tmp_path / f"export-{len(list(tmp_path.glob('export-*.xml')))}.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_diff_warns_when_saved_models_were_numbered(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-one")), "-o", str(a)]).exit_code == 0
    assert runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-two")), "-o", str(b)]).exit_code == 0
    result = runner.invoke(app, ["diff", str(a), str(b)])
    assert "can't be compared" in result.output


def test_diff_with_a_shared_salt_compares_saved_models(tmp_path, monkeypatch):
    monkeypatch.setenv("FM_SAXML_SCRUB_SALT", SALT)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-one")), "-o", str(a)]).exit_code == 0
    assert runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-two")), "-o", str(b)]).exit_code == 0
    a_again = tmp_path / "a2.json"
    assert runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-one")), "-o", str(a_again)]).exit_code == 0
    report = tmp_path / "diff.md"
    result = runner.invoke(app, ["diff", str(a), str(b), "-o", str(report)])
    assert "can't be compared" not in result.output
    assert "Passw0rd" not in report.read_text(encoding="utf-8")

    def password_label(path):
        import orjson
        return {f["placeholder"] for f in orjson.loads(path.read_bytes())["scrubbing"]["findings"]
                if f["category"] == "password"}
    # Separate runs: the same value gets the same fingerprint, a changed one a different one.
    assert password_label(a) == password_label(a_again)
    assert password_label(a) != password_label(b)


def test_short_salt_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("FM_SAXML_SCRUB_SALT", "short")
    result = runner.invoke(app, ["parse", str(_xml(tmp_path, "Passw0rd-one")), "-o", str(tmp_path / "m.json")])
    assert result.exit_code == 1
    assert "at least 16" in result.output


# ---------------------------------------------------------------------------
# Strict-level personal data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "(415) 555-2671", "+44 20 7946 0958", "415.555.2671",
    "GB82 WEST 1234 5698 7654 32", "DE89370400440532013000",
    "123-45-6789", "130 692 544",
])
def test_strict_personal_data(value):
    source = f'"call {value} today"'
    assert Scrubber().scrub_calc(source) == source  # not at standard
    assert value not in Scrubber(ScrubPolicy(level=ScrubLevel.STRICT)).scrub_calc(source)


@pytest.mark.parametrize("value", [
    "2026-10-08", "GB82 WEST 1234 5698 7654 33", "000-12-3456", "046 454 287", "1.2.3.4567",
])
def test_strict_personal_data_negatives(value):
    source = f'"ref {value}"'
    assert Scrubber(ScrubPolicy(level=ScrubLevel.STRICT)).scrub_calc(source) == source


# ---------------------------------------------------------------------------
# fm-saxml:allow
# ---------------------------------------------------------------------------

def _run(*calcs):
    raw = RawModel(file_name="t.xml")
    raw.custom_functions = [{"id": str(i), "name": f"CF{i}", "calculation": c} for i, c in enumerate(calcs)]
    summary = Scrubber().scrub_raw(raw)
    return [cf["calculation"] for cf in raw.custom_functions], summary


def test_allow_marker_leaves_the_calc_and_its_values_alone():
    key = OPENAI_PUBLIC
    allowed = f'/* fm-saxml:allow - documented public test key */ "{key}"'
    out, summary = _run(allowed, f'"{key}"', f'"{OPENAI_REAL}"')
    assert out[0] == allowed
    assert out[1] == f'"{key}"'  # same value elsewhere: allowed too
    assert "REALSECRETKEY" not in out[2]
    assert [f.action for f in summary.allowed] == ["allowed"]


def test_allow_marker_must_be_in_a_comment():
    out, summary = _run(f'"fm-saxml:allow" & "{OPENAI_REAL}"')
    assert "REALSECRETKEY" not in out[0]
    assert not summary.allowed


# ---------------------------------------------------------------------------
# fm-saxml scrub
# ---------------------------------------------------------------------------

RELOGIN = """            <Step hash="CCCC" index="2" id="138" name="Re-Login" enable="True">
              <UUID>00000000-0000-0000-CCCC-000000000001</UUID>
              <OwnerID></OwnerID>
              <Options>0</Options>
              <DDRREF kind="StepText" hash="DDDD">_RELOGIN</DDRREF>
              <ParameterValues membercount="3">
                <Parameter type="Boolean">
                  <Boolean type="With dialog" id="128" value="False"></Boolean>
                </Parameter>
                <Parameter type="Name">
                  <Calculation datatype="1" position="0">
                    <Calculation>
                      <DDRREF kind="ChunkList" hash="EEEE">_RELOGIN_0</DDRREF>
                      <Text><![CDATA["svc"]]></Text>
                    </Calculation>
                  </Calculation>
                </Parameter>
                <Parameter type="Password">
                  <Calculation datatype="1" position="1">
                    <Calculation>
                      <DDRREF kind="ChunkList" hash="FFFF">_RELOGIN_1</DDRREF>
                      <Text><![CDATA["ab1"]]></Text>
                    </Calculation>
                  </Calculation>
                </Parameter>
              </ParameterValues>
            </Step>
"""

DDR_INFO = """  <DDR_INFO>
    <Calculation>
      <ObjectList>
        <_RELOGIN_0 hash="EEEE" datatype="ChunkList">
          <ChunkList hash="EEEE">
            <Chunk type="NoRef">&quot;svc&quot;</Chunk>
          </ChunkList>
        </_RELOGIN_0>
        <_RELOGIN_1 hash="FFFF" datatype="ChunkList">
          <ChunkList hash="FFFF">
            <Chunk type="NoRef">&quot;ab1&quot;</Chunk>
          </ChunkList>
        </_RELOGIN_1>
      </ObjectList>
    </Calculation>
    <StepText>
      <ObjectList>
        <_RELOGIN hash="DDDD" datatype="StepText">Re-Login [ Account Name: &quot;svc&quot;; Password: &quot;ab1&quot; ]</_RELOGIN>
      </ObjectList>
    </StepText>
    <Binary>
      <Stream name="FNAM" type="Hex" size="16">4111 1111 1111 1111</Stream>
    </Binary>
  </DDR_INFO>
"""


def _export(tmp_path: Path, encoding="utf-8", newline="\n", bom=b"") -> Path:
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace('<Comment value="Send the email"></Comment>',
                      '<Comment value="Send the email. temp password is swordfish99"></Comment>')
    xml = xml.replace('<ObjectList membercount="2">\n            <Step hash="AAAA"',
                      '<ObjectList membercount="3">\n            <Step hash="AAAA"')
    xml = xml.replace("          </ObjectList>\n        </Script>\n      </StepsForScripts>",
                      RELOGIN + "          </ObjectList>\n        </Script>\n      </StepsForScripts>")
    xml = xml.replace("</FMSaveAsXML>", DDR_INFO + "</FMSaveAsXML>")
    if encoding != "utf-8":
        xml = xml.replace('<?xml version="1.0" encoding="UTF-8"?>', '<?xml version="1.0"?>')
    xml = xml.replace("\n", newline)
    path = tmp_path / "Export.xml"
    path.write_bytes(bom + xml.encode(encoding))
    return path


def _scrub(tmp_path, src, *args):
    out = tmp_path / "out.xml"
    result = runner.invoke(app, ["scrub", str(src), "-o", str(out), "-f", *args])
    assert result.exit_code == 0, result.output
    return out, result


def test_scrub_replaces_every_copy_and_drops_hashes(tmp_path):
    src = _export(tmp_path)
    out, result = _scrub(tmp_path, src)
    text = out.read_text(encoding="utf-8")

    assert "ab1" not in text and "swordfish99" not in text
    assert text.count("[REDACTED:password#1]") == 3   # calc, ChunkList chunk, StepText
    assert '<Text><![CDATA["[REDACTED:password#1]"]]></Text>' in text  # CDATA kept
    assert "&quot;[REDACTED:password#1]&quot;" in text                 # entity style kept
    assert '"svc"' in text                                              # account name kept
    for h in ("CCCC", "DDDD", "FFFF", "AAAA"):                          # changed: digests gone
        assert f'hash="{h}"' not in text
    assert 'hash="BBBB"' in text and 'hash="EEEE"' in text              # unchanged: kept
    assert "4111 1111 1111 1111" in text                                # binary stream untouched
    assert "re-serialized" not in result.output


def test_scrub_output_differs_only_where_it_redacted(tmp_path):
    src = _export(tmp_path)
    out, _ = _scrub(tmp_path, src)
    before = src.read_text(encoding="utf-8").splitlines()
    after = out.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert 0 < len(changed) <= 12
    for a, b in changed:
        assert PLACEHOLDER_RE.search(b) or ("hash=" in a and "hash=" not in b)


def test_scrub_keeps_utf16_bom_and_crlf(tmp_path):
    src = _export(tmp_path, encoding="utf-16-le", newline="\r\n", bom=b"\xff\xfe")
    out, _ = _scrub(tmp_path, src)
    data = out.read_bytes()
    assert data.startswith(b"\xff\xfe<\x00?\x00x\x00m\x00l\x00")
    text = data[2:].decode("utf-16-le")
    assert text.count("\r\n") == text.count("\n")
    assert "ab1" not in text and "[REDACTED:password#1]" in text


def test_rescrubbing_the_output_finds_nothing_new(tmp_path):
    out, _ = _scrub(tmp_path, _export(tmp_path))
    again = tmp_path / "again.xml"
    result = runner.invoke(app, ["scrub", str(out), "-o", str(again), "-f"])
    assert result.exit_code == 0, result.output
    assert again.read_bytes() == out.read_bytes()


def test_scrub_report_and_fail_on_secrets(tmp_path):
    src = _export(tmp_path)
    report = tmp_path / "report.md"
    result = runner.invoke(app, ["scrub", str(src), "-o", str(tmp_path / "o.xml"), "-f",
                                 "--report", str(report), "--fail-on-secrets"])
    assert result.exit_code == 1
    assert "[REDACTED:password#1]" in report.read_text(encoding="utf-8")


def test_scrub_refuses_other_formats(tmp_path):
    snippet = tmp_path / "clip.xml"
    snippet.write_text('<fmxmlsnippet type="FMObjectList"><Step id="141" name="Set Variable"/></fmxmlsnippet>',
                       encoding="utf-8")
    result = runner.invoke(app, ["scrub", str(snippet)])
    assert result.exit_code == 1
    assert "clipboard XML" in result.output


def test_scrub_refuses_to_overwrite_its_input(tmp_path):
    src = _export(tmp_path)
    result = runner.invoke(app, ["scrub", str(src), "-o", str(src), "-f"])
    assert result.exit_code == 1
    assert "overwrite the input" in result.output
