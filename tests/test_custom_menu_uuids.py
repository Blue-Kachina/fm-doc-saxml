"""G3a: custom menu and menu set UUIDs in the model, entities.json and the pages (for menu-lookup).

menu-lookup reports four UUIDs before a paste: the CustomMenuCatalog, the CustomMenu, the
CustomMenuSetCatalog and the CustomMenuSet. The values below are read from the F0 export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from fm_saxml.cli import _make_scrubber, _run_pipeline
from fm_saxml.render.json.writer import write_split_json
from fm_saxml.render.markdown.renderer import render_markdown

BAGEL = Path(__file__).parent.parent / "samples" / "by_type" / "whole" / "EverythingBagel.xml"

MENU_UUID = "4B4D221B-C372-2D48-A740-DBC9A2913258"
MENU_CATALOG_UUID = "F0D02DB4-BAD4-304F-A1F5-BE97F56A225E"
SET_UUID = "4629F04A-F682-3448-A37F-2D33ED047415"
SET_CATALOG_UUID = "BFA80551-FDB7-3D44-9B03-648D46B61ACB"
STANDARD_MENUS_UUID = "2C8E1610-3EFB-354E-B6B5-D099E62B1FF7"  # per file, not a constant (Q13)

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """F0 built with scrubbing on, so the test also shows the scrubber leaves UUIDs alone."""
    model = _run_pipeline(BAGEL, _make_scrubber(False, "standard", None, None))
    out = tmp_path_factory.mktemp("menus")
    render_markdown(model, out)
    write_split_json(model, out)
    return model, out


def _front_matter(page: Path) -> dict[str, str]:
    lines = page.read_text(encoding="utf-8").split("---")[1].strip().splitlines()
    return {k.strip(): v.strip().strip('"') for k, v in (line.split(":", 1) for line in lines)}


def test_menu_page_front_matter(built):
    _, out = built
    fm = _front_matter(out / "CustomMenus" / "Custom Custom Menu.md")
    assert fm["fmpId"] == "25" and fm["uuid"] == MENU_UUID and fm["catalogUuid"] == MENU_CATALOG_UUID
    assert fm["itemCount"] == "1"


def test_menu_set_page_front_matter_and_menu_uuids(built):
    _, out = built
    page = out / "CustomMenuSets" / "Custom Menu Set.md"
    fm = _front_matter(page)
    assert fm["fmpId"] == "2" and fm["uuid"] == SET_UUID and fm["catalogUuid"] == SET_CATALOG_UUID
    assert f"`{MENU_UUID}`" in page.read_text(encoding="utf-8")


def test_entities_json_has_the_uuids(built):
    _, out = built
    e = json.loads((out / "entities.json").read_text(encoding="utf-8"))
    menu = e["customMenus"]["customMenu:Custom Custom Menu"]
    assert (menu["uuid"], menu["catalogUuid"]) == (MENU_UUID, MENU_CATALOG_UUID)
    assert menu["items"][0]["uuid"] == "F4499B88-6E8F-E942-A6B6-305F3316AC9A"
    menu_set = e["customMenuSets"]["customMenuSet:Custom Menu Set"]
    assert (menu_set["uuid"], menu_set["catalogUuid"]) == (SET_UUID, SET_CATALOG_UUID)
    fo = e["fileOptions"]
    assert (fo["defaultMenuSet"], fo["defaultMenuSetId"], fo["defaultMenuSetUuid"]) == (
        "[Standard FileMaker Menus]", "1", STANDARD_MENUS_UUID)


def test_layout_keeps_its_menu_set_uuid(built):
    model, _ = built
    uses = {lay.menu_set: lay.menu_set_uuid for lay in model.entities.layouts.values() if lay.menu_set}
    assert uses.get("Custom Menu Set") == SET_UUID


def test_item_count_matches_the_export(built):
    model, _ = built
    root = etree.parse(str(BAGEL)).getroot()
    declared = {m.get("name"): int(m.find("MenuItemList").get("membercount"))
                for m in root.iter("CustomMenu") if m.find("MenuItemList") is not None}
    assert declared
    for name, count in declared.items():
        assert len(model.entities.custom_menus[f"customMenu:{name}"].items) == count, name
