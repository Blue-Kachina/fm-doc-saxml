"""Folders of layouts and scripts in the WebMCP data and tools (inFolder op, folder parts on rows)."""

from __future__ import annotations

import pytest

from .test_webmcp import FIXTURES, _STUB, _build, _run, _shard

SCRIPT = '<Script id="1" name="SendEmail">'
LAYOUT = '<Layout id="1" name="ContactDetail" width="1024">'


def _foldered(dest):
    """v2_sample with its one script in Utils/Old and its one layout in DEV (a name with a slash, to keep it honest)."""
    text = (FIXTURES / "v2_sample.xml").read_text(encoding="utf-8")
    text = text.replace(SCRIPT, '<Script id="90" name="Utils" isFolder="True"/><Script id="91" name="Old" isFolder="True"/>' + SCRIPT, 1)
    text = text.replace("        </Script>\n      </ScriptCatalog>", '        </Script><Script id="92" name="--" isFolder="Marker"/><Script id="93" name="--" isFolder="Marker"/>\n      </ScriptCatalog>', 1)
    text = text.replace(LAYOUT, '<Layout id="90" name="DEV/Old" isFolder="True"/>' + LAYOUT, 1)
    assert 'name="Utils" isFolder' in text and 'name="DEV/Old" isFolder' in text
    dest.write_text(text, encoding="utf-8")
    return dest


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("folder_webmcp")
    return _build(tmp, "--webmcp", xml=_foldered(tmp / "v2_folders.xml"))


def test_shards_carry_folder_parts(built):
    script = _shard(built, "script")[2][0]
    layout = _shard(built, "layout")[2][0]
    assert script["folderPathParts"] == ["Utils", "Old"] and script["folderPath"] == "Utils/Old"
    assert layout["folderPathParts"] == ["DEV/Old"]  # one folder, whose name holds a slash
    step = _shard(built, "scriptStep")[2]
    if step:
        assert step[0]["scriptFolderParts"] == ["Utils", "Old"]


@pytest.fixture(scope="module")
def viewer(built):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page()
        page.add_init_script(_STUB)
        page.goto((built / "index.html").as_uri())
        page.wait_for_selector("body[data-rendered]", timeout=60000)
        yield page
        browser.close()


def test_in_folder_matches_a_folder_and_what_is_below_it(viewer):
    def names(value, type_="script"):
        body = _run(viewer, "query_entities", {"type": type_, "where": [{"field": "folderPathParts", "op": "inFolder", "value": value}],
                                               "display": False})
        return [i["name"] for i in body["items"]]

    assert names("Utils") == ["SendEmail"]
    assert names("utils/old") == ["SendEmail"]
    assert names(["Utils", "Old"]) == ["SendEmail"]
    assert names("Utils › Old") == ["SendEmail"]
    assert names("Old") == []  # a folder is matched from the top, not anywhere in the path
    assert names("Utils/Old/Deeper") == []
    assert names("DEV/Old", "layout") == []  # nested A > B, not the one folder named "DEV/Old"
    assert names(["DEV/Old"], "layout") == ["ContactDetail"]


def test_summary_shows_the_folder(viewer):
    body = _run(viewer, "query_entities", {"type": "script", "display": False})
    assert body["items"][0]["detail"] == "Utils › Old"
