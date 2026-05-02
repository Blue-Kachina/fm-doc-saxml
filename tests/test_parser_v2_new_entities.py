"""Tests for v2 FMSaveAsXML parser — new entity types: accounts, extended privileges,
custom menus, custom menu sets, themes, file references."""

from pathlib import Path
import pytest
from fm_docgen.parser.saxml_reader import parse_savexml

FIXTURE = Path(__file__).parent / "fixtures" / "v2_sample.xml"


@pytest.fixture
def raw():
    return parse_savexml(FIXTURE)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def test_account_count(raw):
    assert len(raw.accounts) == 1


def test_account_name_from_child_element(raw):
    assert raw.accounts[0]["name"] == "admin"


def test_account_type(raw):
    assert raw.accounts[0]["account_type"] == "FileMaker"


def test_account_enabled(raw):
    assert raw.accounts[0]["enabled"] is True


def test_account_privilege_set(raw):
    assert raw.accounts[0]["privilege_set_name"] == "[Full Access]"


def test_account_description(raw):
    assert raw.accounts[0]["description"] == "Default admin account"


# ---------------------------------------------------------------------------
# Extended Privileges
# ---------------------------------------------------------------------------

def test_extended_privilege_count(raw):
    assert len(raw.extended_privileges) == 2


def test_extended_privilege_names(raw):
    names = {ep["name"] for ep in raw.extended_privileges}
    assert "fmwebdirect" in names
    assert "fmapp" in names


def test_extended_privilege_description(raw):
    fmwebdirect = next(ep for ep in raw.extended_privileges if ep["name"] == "fmwebdirect")
    assert fmwebdirect["description"] == "Access via FileMaker WebDirect"


def test_extended_privilege_with_ps_refs(raw):
    fmwebdirect = next(ep for ep in raw.extended_privileges if ep["name"] == "fmwebdirect")
    assert len(fmwebdirect["privilege_set_refs"]) == 1
    assert fmwebdirect["privilege_set_refs"][0]["name"] == "[Full Access]"


def test_extended_privilege_no_ps_refs(raw):
    fmapp = next(ep for ep in raw.extended_privileges if ep["name"] == "fmapp")
    assert fmapp["privilege_set_refs"] == []


# ---------------------------------------------------------------------------
# Custom Menus
# ---------------------------------------------------------------------------

def test_custom_menu_count(raw):
    assert len(raw.custom_menus) == 2


def test_custom_menu_names(raw):
    names = {cm["name"] for cm in raw.custom_menus}
    assert "EditMenu" in names
    assert "EmptyMenu" in names


def test_custom_menu_base_name(raw):
    edit_menu = next(cm for cm in raw.custom_menus if cm["name"] == "EditMenu")
    assert edit_menu["base_menu_name"] == "Edit"


def test_custom_menu_modes(raw):
    edit_menu = next(cm for cm in raw.custom_menus if cm["name"] == "EditMenu")
    assert edit_menu["browse_mode"] is True
    assert edit_menu["find_mode"] is True
    assert edit_menu["preview_mode"] is False


def test_custom_menu_items(raw):
    edit_menu = next(cm for cm in raw.custom_menus if cm["name"] == "EditMenu")
    assert len(edit_menu["items"]) == 2
    item_names = {item["name"] for item in edit_menu["items"]}
    assert "Undo" in item_names
    assert "Redo" in item_names


def test_custom_menu_empty_items(raw):
    empty_menu = next(cm for cm in raw.custom_menus if cm["name"] == "EmptyMenu")
    assert empty_menu["items"] == []


# ---------------------------------------------------------------------------
# Custom Menu Sets
# ---------------------------------------------------------------------------

def test_custom_menu_set_count(raw):
    assert len(raw.custom_menu_sets) == 1


def test_custom_menu_set_name(raw):
    assert raw.custom_menu_sets[0]["name"] == "DefaultMenuSet"


def test_custom_menu_set_menu_refs(raw):
    refs = raw.custom_menu_sets[0]["menu_refs"]
    assert len(refs) == 2
    names = {r["name"] for r in refs}
    assert "EditMenu" in names
    assert "EmptyMenu" in names


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

def test_theme_count(raw):
    assert len(raw.themes) == 1


def test_theme_name(raw):
    assert raw.themes[0]["name"] == "com.filemaker.theme.minimalist_touch"


def test_theme_display_name(raw):
    assert raw.themes[0]["display_name"] == "Minimalist Touch"


def test_theme_group(raw):
    assert raw.themes[0]["group"] == "FileMaker"


def test_theme_default(raw):
    assert raw.themes[0]["default_theme"] is True


# ---------------------------------------------------------------------------
# File References
# ---------------------------------------------------------------------------

def test_file_reference_count(raw):
    assert len(raw.file_references) == 1


def test_file_reference_display_name(raw):
    assert raw.file_references[0]["display_name"] == "TestSolution"


def test_file_reference_type(raw):
    assert raw.file_references[0]["ref_type"] == "Local"


def test_file_reference_is_self(raw):
    assert raw.file_references[0]["is_self"] is True
