"""The HTML viewer's sidebar: a layout's or script's folders sit under Layouts/Scripts, never directly under a file."""

from __future__ import annotations

import shutil

import pytest

from .test_webmcp import MULTI, app, runner


def test_multi_file_sidebar_nests_folders_under_the_section(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    if not MULTI.exists():
        pytest.skip("multi-file samples not present")
    src = tmp_path / "in"
    shutil.copytree(MULTI, src)
    a = src / "FileA.xml"
    text = a.read_text(encoding="utf-8")
    old = '<Layout id="1" name="FileA" width="1024">'
    assert old in text
    a.write_text(text.replace(old, '<Layout id="90" name="DEV" isFolder="True"/>' + old, 1), encoding="utf-8")
    out = tmp_path / "docs"
    result = runner.invoke(app, ["build", str(src), "-o", str(out), "-f", "--html"])
    assert result.exit_code == 0, result.output

    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as exc:  # no Chrome here
            pytest.skip(f"Chrome not available: {exc}")
        page = browser.new_page()
        page.goto((out / "index.html").as_uri())
        page.wait_for_selector("body[data-rendered]", timeout=60000)
        prefixes = page.evaluate("[...document.querySelectorAll('#side details')].map(d => d.getAttribute('data-prefix'))")
        browser.close()
    assert "FileA/Layouts/DEV/" in prefixes
    assert "FileA/DEV/" not in prefixes
