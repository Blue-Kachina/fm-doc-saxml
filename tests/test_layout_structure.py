"""G4a: layout structure and geometry (width, parts, display styles, hide in find, button faces)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fm_saxml.cli import _run_pipeline
from fm_saxml.model.entities import DISPLAY_STYLES

ROOT = Path(__file__).parent.parent
BAGEL = ROOT / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
STYLES = ROOT / "samples" / "EverythingBagel_mac_run" / "display_styles" / "EverythingBagel_styles.saxml.xml"

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


@pytest.fixture(scope="module")
def bagel():
    return _run_pipeline(BAGEL)


def _objects(model, **match):
    return [o for o in model.entities.layout_objects.values()
            if all(getattr(o, k) == v for k, v in match.items())]


def test_layout_setup(bagel):
    lay = bagel.entities.layouts["layout:EverythingBagel"]
    assert (lay.width, lay.grid_style, lay.client_type, lay.hidden) == (1024, 5, 3, False)
    assert lay.options == 64708872193


def test_part_definitions_are_kept(bagel):
    parts = bagel.entities.layouts["layout:EverythingBagel"].parts
    assert [(p.type, p.definition_kind, p.absolute, p.options) for p in parts] == [
        ("Top Navigation", 12, 0, 0), ("Body", 4, 110, 0)]


def test_display_styles_by_name(bagel):
    [edit_box] = _objects(bagel, layout_doc_id="layout:EverythingBagel", object_id="2")
    assert (edit_box.display_style, edit_box.display_style_code) == ("editBox", 0)
    assert edit_box.options == 805306368
    assert {o.display_style for o in bagel.entities.layout_objects.values() if o.display_style} == {
        "editBox", "dropDownList", "popUpMenu", "dropDownCalendar"}


@pytest.mark.skipif(not STYLES.exists(), reason="Mac run display styles sample not present")
def test_every_known_display_style():
    model = _run_pipeline(STYLES)
    seen = {o.display_style_code: o.display_style for o in model.entities.layout_objects.values()
            if o.display_style_code is not None}
    assert seen == {code: DISPLAY_STYLES[code] for code in (0, 1, 2, 3, 4, 6, 7)}


def test_hide_condition_find_mode(bagel):
    hidden = [o for o in bagel.entities.layout_objects.values() if o.hide_in_find_mode is not None]
    assert [o.hide_in_find_mode for o in hidden] == [False]
    assert any(c.role == "hideCondition" for c in hidden[0].calculations)


def test_button_faces(bagel):
    [popover] = _objects(bagel, object_type="Popover Button")
    assert (popover.label_text, popover.icon_type) == ("Popover Button Text", 0)
    bar_buttons = [o for o in _objects(bagel, object_type="Button") if o.parent_object_doc_id]
    assert bar_buttons and all(o.icon_type == 4 and o.label_text is None for o in bar_buttons)
    assert all(any(c.role == "label" for c in o.calculations) for o in bar_buttons)  # their label is a calc
