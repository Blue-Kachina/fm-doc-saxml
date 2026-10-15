"""--webmcp: the model behind the HTML viewer's WebMCP tools, and the tools themselves.

The data shards are checked here directly. The tools run in a browser, so the last
tests drive the viewer with Playwright (skipped when Playwright or Chrome isn't
installed): ``uv run --with playwright pytest tests/test_webmcp.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fm_saxml.analyze.access import build_access
from fm_saxml.cli import _run_pipeline, app
from fm_saxml.model.document_model import DocumentModel, SourceInfo
from fm_saxml.model.entities import (
    AccountEntity, EntityCalculation, PrivilegeCategory, PrivilegeItem, PrivilegeSetEntity, ScriptEntity,
    TableEntity, LayoutEntity,
)
from fm_saxml.render.html import VIEWER_DIR
from fm_saxml.render.html.viewer import _js_literal
from fm_saxml.scrub.guard import guard_output

from .test_scrub_cli import SECRETS, _secret_xml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
MULTI = ROOT / "samples" / "multi_file_export" / "SaXML_no_separate_catalogue"
runner = CliRunner()


def _call_args(js: str, fn: str) -> list:
    prefix = f"FMDocs.{fn}("
    assert js.startswith(prefix) and js.endswith(");\n"), js[:80]
    return json.loads("[" + js[len(prefix):-3] + "]")


def _data(out: Path, key: str = "_") -> Path:
    return out / VIEWER_DIR / "data" / key


def _shard(out: Path, name: str, key: str = "_") -> list:
    fn = {"catalog": "catalog", "refs": "refs", "access": "access"}.get(name, "shard")
    return _call_args((_data(out, key) / f"{name}.js").read_text(encoding="utf-8"), fn)


def _manifest(out: Path) -> dict:
    return _call_args((out / VIEWER_DIR / "manifest.js").read_text(encoding="utf-8"), "manifest")[0]


def _build(tmp_path: Path, *extra: str, xml: Path = FIXTURES / "v2_sample.xml") -> Path:
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "-f", *extra])
    assert result.exit_code == 0, result.output
    return out


# ---------------------------------------------------------------------------
# Data shards
# ---------------------------------------------------------------------------

def test_html_without_webmcp_has_no_tools(tmp_path):
    out = _build(tmp_path, "--html")
    assert not (out / VIEWER_DIR / "webmcp.js").exists()
    assert not (out / VIEWER_DIR / "data").exists()
    assert "webmcp.js" not in (out / "index.html").read_text(encoding="utf-8")
    assert "webmcp" not in _manifest(out)


def test_webmcp_turns_on_the_viewer_and_lists_the_data(tmp_path):
    out = _build(tmp_path, "--webmcp")
    assert (out / "index.html").exists()
    assert '<script src="_viewer/webmcp.js"></script>' in (out / "index.html").read_text(encoding="utf-8")
    assert (out / VIEWER_DIR / "webmcp.js").exists()
    assert _manifest(out)["webmcp"]["files"] == [{"key": "_", "label": "TestSolution", "dir": ""}]


def test_every_entity_is_in_its_shard_with_a_page(tmp_path):
    out = _build(tmp_path, "--webmcp")
    model = _run_pipeline(FIXTURES / "v2_sample.xml")
    key, catalog = _shard(out, "catalog")
    assert key == "_"
    em = model.entities.model_dump(by_alias=True)
    expected = {doc_id: e["entityType"] for entity_map in em.values() for doc_id, e in entity_map.items()}
    found = {}
    for entity_type, count in catalog["counts"].items():
        _, shard_type, records = _shard(out, entity_type)
        assert shard_type == entity_type and len(records) == count
        for r in records:
            found[r["docId"]] = r["entityType"]
            assert "sourceXml" not in r
            assert r["path"] and (out / r["path"]).exists(), r["docId"]
    assert found == expected


def test_records_carry_the_derived_fields(tmp_path):
    out = _build(tmp_path, "--webmcp")
    fields = {r["name"]: r for r in _shard(out, "field")[2]}
    assert fields["ContactID"]["table"] == "Contact"
    assert fields["ContactID"]["indexed"] is True and fields["ContactID"]["global"] is False
    steps = _shard(out, "scriptStep")[2]
    assert [s["stepNumber"] for s in steps] == [1, 2]
    assert {s["path"] for s in steps} == {"Scripts/SendEmail.md"}
    assert all("params" not in s and "text" in s for s in steps)
    _, refs = _shard(out, "refs")
    cols = refs["cols"]
    rows = [dict(zip(cols, r)) for r in refs["rows"]]
    to_fields = [r for r in rows if r["targetType"] == "field"]
    assert to_fields and all(r["targetParent"] == "table:Contact" for r in to_fields)


def test_layout_objects_know_their_hide_condition_and_panel(tmp_path):
    from fm_saxml.model.entities import LayoutObjectEntity

    model = _run_pipeline(FIXTURES / "v2_sample.xml")
    layout = next(iter(model.entities.layouts))
    # A field in a popover that sits on a tab control's panel, with a hide condition.
    tab = LayoutObjectEntity(docId="layoutObject:L::90", layoutDocId=layout, objectId="90", objectType="Tab Control")
    panel = LayoutObjectEntity(docId="layoutObject:L::91", layoutDocId=layout, objectId="91", objectType="Panel",
                               parentObjectDocId=tab.doc_id)
    pop = LayoutObjectEntity(docId="layoutObject:L::92", layoutDocId=layout, objectId="92", objectType="PopoverPanel",
                             parentObjectDocId=panel.doc_id)
    target = LayoutObjectEntity(docId="layoutObject:L::93", layoutDocId=layout, objectId="93", objectType="Edit Box",
                                fieldDocId="field:Contact::Status", parentObjectDocId=pop.doc_id,
                                calculations=[EntityCalculation(role="hideCondition", text="IsEmpty ( Contact::Status )")])
    for o in (tab, panel, pop, target):
        model.entities.layout_objects[o.doc_id] = o

    from fm_saxml.render.html.webmcp import write_webmcp_data
    write_webmcp_data(model, tmp_path)
    records = {r["docId"]: r for r in _shard(tmp_path, "layoutObject")[2]}
    r = records[target.doc_id]
    assert r["hasHideCondition"] is True and r["hideCondition"] == "IsEmpty ( Contact::Status )"
    assert r["inPanel"] is True
    assert [c["kind"] for c in r["shownIn"]] == ["popover", "tabPanel"]
    assert r["isField"] is True and r["fieldName"] == "Contact::Status"
    assert records[tab.doc_id]["inPanel"] is False


def test_batch_writes_one_data_folder_per_file(tmp_path):
    if not MULTI.exists():
        pytest.skip("multi-file sample not present")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(MULTI), "-o", str(out), "-f", "--webmcp"])
    assert result.exit_code == 0, result.output
    files = _manifest(out)["webmcp"]["files"]
    assert sorted(f["key"] for f in files) == ["FileA", "FileB"]
    for f in files:
        assert f["dir"] == f["key"]
        _, catalog = _shard(out, "catalog", f["key"])
        for _, _, _, path in catalog["index"]:
            assert path.startswith(f["dir"] + "/") and (out / path).exists(), path
        _, refs = _shard(out, "refs", f["key"])
        # Targets in the other file resolve to that file's pages.
        for doc_id, (name, path) in refs["external"].items():
            if path:
                assert (out / path).exists(), (doc_id, path)


def test_shards_cannot_break_out_of_the_script(tmp_path):
    xml = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    xml = xml.replace('name="SendEmail"', 'name="Send &lt;/script&gt;&lt;script&gt;alert(1)//"')
    src = tmp_path / "Nasty.xml"
    src.write_text(xml, encoding="utf-8")
    out = _build(tmp_path, "--webmcp", xml=src)
    for js in _data(out).glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert "<" not in text and " " not in text, js.name
    names = [r["name"] for r in _shard(out, "script")[2]]
    assert "Send </script><script>alert(1)//" in names


def test_secrets_never_reach_the_webmcp_data(tmp_path):
    xml = _secret_xml(tmp_path)
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(xml), "-o", str(out), "-f", "--webmcp", "--scrub-level", "standard"])
    assert result.exit_code == 0, result.output  # the guard (which now reads .js) found nothing
    data = "\n".join(p.read_text(encoding="utf-8") for p in (out / VIEWER_DIR).rglob("*.js"))
    for secret in SECRETS:
        assert secret not in data and json.dumps(secret)[1:-1] not in data, secret
    assert "[REDACTED:password#1]" in data


def test_guard_finds_a_value_in_a_viewer_script(tmp_path):
    secret = "pa<ss w0rd!"
    (tmp_path / "x.js").write_text(f"FMDocs.shard('_','script',{_js_literal([{'name': secret}])});\n", encoding="utf-8")
    leaks = guard_output(tmp_path, {secret: "[REDACTED:password#1]"})
    assert [leak.placeholder for leak in leaks] == ["[REDACTED:password#1]"]


# ---------------------------------------------------------------------------
# Effective access
# ---------------------------------------------------------------------------

def _privilege_model() -> DocumentModel:
    m = DocumentModel(source=SourceInfo(fileName="t.xml", sourcePath="t.xml"))
    em = m.entities
    em.scripts = {d: ScriptEntity(docId=d, name=d.split(":")[1], fmpId=str(i)) for i, d in
                  enumerate(["script:A", "script:B", "script:C"])}
    em.layouts = {"layout:L": LayoutEntity(docId="layout:L", name="L", fmpId="1")}
    em.tables = {"table:T": TableEntity(docId="table:T", name="T", fmpId="1")}

    def item(kind, target, attrs=None, access=None, calcs=None):
        return PrivilegeItem(kind=kind, targetDocId=target, attributes=attrs or {}, access=access or {},
                             calculations=calcs or [])

    sets = [
        PrivilegeSetEntity(docId="privilegeSet:[Full Access]", name="[Full Access]", fmpId="1", builtIn=True),
        PrivilegeSetEntity(
            docId="privilegeSet:Custom", name="Custom", fmpId="2",
            scripts=PrivilegeCategory(summary="Custom", custom=[
                item("Script", "script:A", {"access": "ReadOnly"}),
                item("Script", "script:B", {"access": "NoAccess"}),
                item("Script", None, {"access": "ReadWrite"}),  # [Any new script]
            ]),
            layouts=PrivilegeCategory(summary="Custom", custom=[item("Layout", "layout:L", {"access": "ReadOnly", "records": "ReadWrite"})]),
            records=PrivilegeCategory(summary="Custom", custom=[item(
                "Table", "table:T", access={"View": "Calculation", "Edit": "ReadWrite", "Create": "NoAccess", "Delete": "NoAccess"},
                calcs=[EntityCalculation(role="View", text='Owner = Get ( AccountName )')])]),
        ),
        PrivilegeSetEntity(
            docId="privilegeSet:Blanket", name="Blanket", fmpId="3",
            scripts=PrivilegeCategory(summary="View only", settings={"View": "ReadOnly"}),
            layouts=PrivilegeCategory(summary="No access", settings={"Create": "False", "Edit": "False", "Delete": "False"}),
            records=PrivilegeCategory(summary="View only", settings={"View": "ReadOnly"}),
        ),
        PrivilegeSetEntity(
            docId="privilegeSet:Listed", name="Listed", fmpId="4",
            scripts=PrivilegeCategory(summary="Custom", custom=[item("Script", "script:A", {"access": "ReadWrite"})]),
        ),
    ]
    em.privilege_sets = {s.doc_id: s for s in sets}
    em.accounts = {
        "account:admin": AccountEntity(docId="account:admin", name="admin", fmpId="1", privilegeSetDocId="privilegeSet:[Full Access]"),
        "account:old": AccountEntity(docId="account:old", name="old", fmpId="2", enabled=False, privilegeSetDocId="privilegeSet:Custom"),
        "account:grp": AccountEntity(docId="account:grp", name="Sales", fmpId="3", accountType="Microsoft Azure Group",
                                     privilegeSetDocId="privilegeSet:Custom"),
    }
    return m


def _rows(access: dict, kind: str, doc_id: str) -> dict:
    return {row[0].split(":", 1)[1]: row[1:] for row in access["objects"][kind][doc_id]}


def test_access_reasons_for_scripts():
    access = build_access(_privilege_model())
    assert _rows(access, "script", "script:A") == {
        "[Full Access]": ["modifiable", "fullAccess"], "Custom": ["executable", "customRow"],
        "Blanket": ["executable", "blanket"], "Listed": ["modifiable", "customRow"]}
    b = _rows(access, "script", "script:B")
    assert b["Custom"] == ["none", "customRow"]
    c = _rows(access, "script", "script:C")
    assert c["Custom"] == ["modifiable", "newFallback"]
    assert c["Listed"] == ["none", "notListed"]


def test_access_for_layouts_and_records():
    access = build_access(_privilege_model())
    layout = _rows(access, "layout", "layout:L")
    assert layout["Custom"] == ["view", "modifiable", "customRow"]
    assert layout["Blanket"] == ["none", None, "blanket"]
    table = _rows(access, "table", "table:T")
    assert table["Custom"] == [{"view": "limited", "edit": "yes", "create": "no", "delete": "no"}, "customRow",
                               {"view": "Owner = Get ( AccountName )"}]
    assert table["Blanket"][0] == {"view": "yes", "edit": "no", "create": "no", "delete": "no"}


def test_access_lists_accounts_with_their_flags():
    sets = build_access(_privilege_model())["sets"]
    assert sets["privilegeSet:[Full Access]"]["fullAccess"] is True
    custom = {a["name"]: a for a in sets["privilegeSet:Custom"]["accounts"]}
    assert custom["old"]["enabled"] is False and custom["old"]["external"] is False
    assert custom["Sales"]["external"] is True


# ---------------------------------------------------------------------------
# The tools, in a browser
# ---------------------------------------------------------------------------

_STUB = """
window.__registered = [];
document.modelContext = {
  registerTool(t) { window.__registered.push(t.name); },
  unregisterTool(n) { window.__registered = window.__registered.filter((x) => x !== n); },
};
"""


@pytest.fixture(scope="module")
def viewer(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    out = _build(tmp_path_factory.mktemp("webmcp"), "--webmcp")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(_STUB)
        page.goto((out / "index.html").as_uri())
        try:
            page.wait_for_selector("body[data-rendered]", timeout=60000)
        except Exception as exc:  # the renderer comes from a CDN
            pytest.skip(f"viewer didn't render (offline?): {exc}")
        yield page, out, errors
        browser.close()


def _run(page, name: str, args: dict) -> dict:
    res = page.evaluate("([n, a]) => FMDocs.tools[n].execute(a)", [name, args])
    body = json.loads(res["content"][0]["text"])
    assert not res.get("isError"), body
    return body


def _await(page, value: str) -> None:
    page.wait_for_function(f"document.body.dataset.rendered === {json.dumps(value)}", timeout=30000)


def test_tools_register_through_webmcp(viewer):
    page, _, errors = viewer
    names = page.evaluate("window.__registered")
    for name in ("search_entities", "query_entities", "find_script_steps", "find_references", "find_unreferenced",
                 "traverse", "who_can_access", "what_can_access", "query", "describe_schema", "navigate_to"):
        assert name in names
    assert errors == []


def test_query_results_show_grouped_and_survive_a_reload(viewer):
    page, _, _ = viewer
    body = _run(page, "find_references", {"targetType": "field", "parentDocId": "table:Contact"})
    assert body["total"] >= 1
    _await(page, "results")
    groups = page.evaluate("[...document.querySelectorAll('.fm-group > summary')].map(s => s.textContent.trim())")
    assert groups and all(g.startswith("via Contact::") for g in groups)
    link = page.evaluate("location.href")
    page.goto("about:blank")
    page.goto(link)
    _await(page, "results")
    again = page.evaluate("[...document.querySelectorAll('.fm-group > summary')].map(s => s.textContent.trim())")
    assert again == groups


def test_access_and_query_tools(viewer):
    page, _, _ = viewer
    who = _run(page, "who_can_access", {"docId": "script:SendEmail", "display": False})
    assert "[Full Access]" in [i["name"] for i in who["items"]]
    q = _run(page, "query", {"display": False, "steps": [
        {"from": "field"}, {"where": [{"field": "indexed", "op": "eq", "value": True}]}, {"groupBy": "table", "agg": "count"}]})
    assert q["items"] == [{"table": "Contact", "count": q["items"][0]["count"]}]
    err = json.loads(page.evaluate(
        "FMDocs.tools.query_entities.execute({type: 'field', where: [{field: 'nope', op: 'eq', value: 1}], display: false})"
        ".then(r => r.content[0].text)"))
    assert "validFields" in err and "dataType" in err["validFields"]


def test_navigation_and_page_tools(viewer):
    page, _, _ = viewer
    _run(page, "navigate_to", {"docId": "table:Contact"})
    _await(page, "Tables/Contact.md")
    assert "list_fields_in_this_table" in page.evaluate("window.__registered")
    fields = _run(page, "list_fields_in_this_table", {"display": False})
    assert {i["name"] for i in fields["items"]} == {"ContactID", "FullName", "Status"}
    _run(page, "navigate_to", {"docId": "script:SendEmail"})
    _await(page, "Scripts/SendEmail.md")
    names = page.evaluate("window.__registered")
    assert "list_steps_in_this_script" in names and "list_fields_in_this_table" not in names


def test_a_step_result_opens_its_script_at_the_step(viewer):
    page, _, _ = viewer
    _run(page, "navigate_to", {"docId": "scriptStep:SendEmail:0001"})
    _await(page, "Scripts/SendEmail.md")
    hit = page.evaluate("(document.querySelector('.fm-step-hit') || {}).textContent || ''")
    assert hit.strip().startswith("2")


def test_search_box_groups_entity_names_by_type(viewer):
    page, _, _ = viewer
    page.fill("#search", "contact")
    page.wait_for_function("document.querySelectorAll('#side details summary').length > 0", timeout=15000)
    groups = page.evaluate("[...document.querySelectorAll('#side details > summary')].map(s => s.textContent)")
    assert any(g.startswith("Fields") for g in groups) and any(g.startswith("Tables") for g in groups)
    page.fill("#search", "")


# ---------------------------------------------------------------------------
# Serving over localhost, and the status badge
# ---------------------------------------------------------------------------

def _served(out: Path):
    """Start the docs server on a free port in a thread; returns (server, base url)."""
    import threading

    from fm_saxml.serve import make_server

    server = make_server(out, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _get(url: str, host: str | None = None):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None, b""


def test_serve_serves_the_folder_to_this_computer_only(tmp_path):
    out = _build(tmp_path, "--webmcp")
    server, base = _served(out)
    try:
        status, _, body = _get(base + "/index.html")
        assert status == 200 and b"webmcp.js" in body
        status, ctype, _ = _get(base + "/_viewer/webmcp.js")
        assert status == 200 and ctype.startswith("text/javascript")
        assert server.server_address[0] == "127.0.0.1"
        # A page on another site can't reach it by pointing its own host name at 127.0.0.1.
        assert _get(base + "/index.html", host="evil.example:80")[0] == 421
        assert _get(base + "/../../etc/passwd")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_serve_needs_a_webmcp_build(tmp_path):
    out = _build(tmp_path, "--html")
    result = runner.invoke(app, ["serve", str(out), "--no-open"])
    assert result.exit_code == 1 and "--webmcp" in result.output
    result = runner.invoke(app, ["build", str(FIXTURES / "v2_sample.xml"), "-o", str(tmp_path / "x"), "-f", "--html",
                                 "--serve"])
    assert result.exit_code == 1 and "--webmcp" in result.output


def _badge(browser, url: str, stub: bool) -> dict:
    context = browser.new_context()
    page = context.new_page()
    if stub:
        page.add_init_script(_STUB)
    page.goto(url)
    page.wait_for_selector("#webmcp-status", timeout=60000)
    state = page.evaluate("({state: document.getElementById('webmcp-status').dataset.state, "
                          "label: document.getElementById('webmcp-status').textContent, "
                          "help: FMDocs.webmcp.status().help})")
    context.close()
    return state


def test_status_badge_says_whether_webmcp_is_on(viewer):
    page, out, _ = viewer
    browser = page.context.browser
    on = _badge(browser, (out / "index.html").as_uri(), stub=True)
    assert on["state"] == "on" and on["label"].startswith("WebMCP · ")
    off = _badge(browser, (out / "index.html").as_uri(), stub=False)
    assert off["state"] == "off" and "disk" in off["label"]
    assert "fm-saxml serve" in off["help"] and out.name in off["help"]
    server, base = _served(out)
    try:
        served = _badge(browser, base + "/index.html", stub=False)
        assert served["state"] == "off" and "not in this browser" in served["label"]
        served_on = _badge(browser, base + "/index.html", stub=True)
        assert served_on["state"] == "on"
    finally:
        server.shutdown()
        server.server_close()


def test_tools_register_when_modelcontext_arrives_late(viewer):
    page, out, _ = viewer
    context = page.context.browser.new_context()
    late = context.new_page()
    late.add_init_script("setTimeout(() => {" + _STUB + "}, 300);")
    late.goto((out / "index.html").as_uri())
    late.wait_for_function("(window.__registered || []).includes('query_entities')", timeout=10000)
    assert late.evaluate("document.getElementById('webmcp-status').dataset.state") == "on"
    context.close()


# ---------------------------------------------------------------------------
# Agents without WebMCP: the #/agents guide, results by URL as JSON, llms.txt
# ---------------------------------------------------------------------------

def test_llms_txt_points_agents_at_the_tools(tmp_path):
    out = _build(tmp_path, "--webmcp")
    text = (out / "llms.txt").read_text(encoding="utf-8")
    assert "index.html#/agents" in text and "format=json" in text and "find_references" in text
    assert not (_build(tmp_path / "plain", "--html") / "llms.txt").exists()


def _plain_page(viewer, fragment: str):
    """A page without any WebMCP, like Claude in Chrome's browser."""
    page, out, _ = viewer
    context = page.context.browser.new_context()
    p = context.new_page()
    p.goto((out / "index.html").as_uri() + fragment)
    return context, p


def test_a_url_runs_a_tool_and_shows_json(viewer):
    q = json.dumps({"tool": "find_references", "args": {"targetType": "field", "parentDocId": "table:Contact"}})
    from urllib.parse import quote
    context, p = _plain_page(viewer, "#/results?q=" + quote(q) + "&format=json")
    p.wait_for_selector("#fm-result-json", timeout=60000)
    body = json.loads(p.inner_text("#fm-result-json"))
    assert body["total"] >= 1 and all(i["via"].startswith("field:Contact::") for i in body["items"])
    bad = quote(json.dumps({"tool": "query_entities", "args": {"type": "field", "where": [{"field": "nope"}]}}))
    p.goto(p.url.split("#")[0] + "#/results?q=" + bad + "&format=json")
    p.wait_for_function("document.querySelector('#fm-result-json') && document.querySelector('#fm-result-json').textContent.includes('error')")
    assert "validFields" in json.loads(p.inner_text("#fm-result-json"))
    context.close()


def test_agents_page_lists_every_tool_with_runnable_examples(viewer):
    context, p = _plain_page(viewer, "#/agents")
    p.wait_for_selector(".fm-agents h3", timeout=60000)
    names = p.evaluate("[...document.querySelectorAll('.fm-agents h3 code')].map(c => c.textContent)")
    assert {"describe_schema", "query_entities", "who_can_access", "query"} <= set(names)
    assert p.is_visible("#webmcp-agents")
    example = p.evaluate("[...document.querySelectorAll('.fm-agents a')].find(a => a.textContent === 'open as JSON'"
                         " && a.href.includes('who_can_access')).href")
    p.goto(example)
    p.wait_for_selector("#fm-result-json")
    assert json.loads(p.inner_text("#fm-result-json"))["total"] >= 1
    context.close()
