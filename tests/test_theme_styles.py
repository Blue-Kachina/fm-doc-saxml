"""G2 (structured theme metadata) and G4b (each object's and part's style). The CSS text is deferred (B3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fm_saxml.cli import _make_scrubber, _run_pipeline
from fm_saxml.render.markdown.renderer import render_markdown

BAGEL = Path(__file__).parent.parent / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
VIBRANT_UUID = "F0797BE7-8F51-B644-A07C-D838BDD53F30"

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


@pytest.fixture(scope="module")
def bagel():
    return _run_pipeline(BAGEL)


def _themes(model):
    return {t.display_name: t for t in model.entities.themes.values()}


def test_two_custom_themes_with_their_metadata(bagel):
    themes = _themes(bagel)
    assert set(themes) == {"Vibrant Custom", "Apex Blue Copy"}
    vibrant = themes["Vibrant Custom"]
    assert vibrant.default_theme and not themes["Apex Blue Copy"].default_theme
    assert (vibrant.uuid, vibrant.base_name, vibrant.base_version) == (
        VIBRANT_UUID, "com.filemaker.theme.vibrant", "6")
    assert (vibrant.version, vibrant.platform, vibrant.locale) == ("6", "1", "en")
    assert len(vibrant.named_styles) == 53 and vibrant.named_styles["title_text_1"] == "Title Text 1"
    assert list(vibrant.color_palette) == [f"swatch{n}" for n in range(1, 10)]
    assert vibrant.color_palette["swatch9"] == "#dd0058"
    assert vibrant.layout_builder["kHeaderMinSize"] == "50"
    assert vibrant.charting == {"colorScheme": "FileMaker Apps"}


def test_layout_keeps_its_theme_uuid_and_base(bagel):
    lay = bagel.entities.layouts["layout:EverythingBagel"]
    assert (lay.theme_uuid, lay.theme_base) == (VIBRANT_UUID, "com.filemaker.theme.vibrant")


def test_object_styles_name_the_theme_style(bagel):
    themes = {t.name: t for t in bagel.entities.themes.values()}
    styled = [o for o in bagel.entities.layout_objects.values()
              if o.local_style and o.local_style.type == "ThemeCustomStyle"]
    assert styled
    for o in styled:
        theme = themes[bagel.entities.layouts[o.layout_doc_id].theme]
        assert theme.named_styles[o.local_style.name] == o.local_style.display_name
    assert "centered_text" in {o.local_style.display_name for o in styled}  # a custom named style


def test_scrubbing_leaves_theme_metadata_and_styles_alone(bagel):
    scrubbed = _run_pipeline(BAGEL, _make_scrubber(False, "standard", None, None))
    for doc_id, theme in bagel.entities.themes.items():
        other = scrubbed.entities.themes[doc_id]
        assert (other.named_styles, other.color_palette, other.layout_builder) == (
            theme.named_styles, theme.color_palette, theme.layout_builder)
    assert {d: o.local_style for d, o in scrubbed.entities.layout_objects.items()} == {
        d: o.local_style for d, o in bagel.entities.layout_objects.items()}


def test_theme_and_object_pages(bagel, tmp_path):
    render_markdown(bagel, tmp_path)
    theme_pages = {p.read_text(encoding="utf-8") for p in (tmp_path / "Themes").glob("*.md") if p.name != "index.md"}
    vibrant = next(t for t in theme_pages if "# Theme: Vibrant Custom" in t)
    assert "| swatch9 | `#dd0058` |" in vibrant and "| `title_text_1` | Title Text 1 |" in vibrant
    assert "| Based On | `com.filemaker.theme.vibrant` (version 6) |" in vibrant
    pages = [p.read_text(encoding="utf-8") for p in (tmp_path / "LayoutObjects").rglob("*.md")]
    assert any("| Style | centered_text |" in p for p in pages)
