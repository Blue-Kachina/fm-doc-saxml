"""Cross-platform filename safety for safe_slug."""

import pytest

from fm_saxml.normalize.names import MAX_SLUG_LENGTH, safe_slug


@pytest.mark.parametrize("name", ["CON", "nul", "Aux", "COM1", "lpt9", "con.txt"])
def test_windows_reserved_names_are_prefixed(name):
    assert safe_slug(name).startswith("_")
    assert safe_slug(name).split(".")[0].upper() not in {"CON", "NUL", "AUX", "COM1", "LPT9"}


def test_normal_names_unchanged():
    assert safe_slug("Invoices") == "Invoices"
    assert safe_slug("Console") == "Console"


def test_invalid_characters_replaced():
    assert safe_slug('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_trailing_dots_and_spaces_stripped():
    assert safe_slug("name. . ") == "name"


def test_empty_becomes_underscore():
    assert safe_slug("...") == "_"


def test_long_names_truncated_but_distinct():
    a = safe_slug("x" * 300 + "A")
    b = safe_slug("x" * 300 + "B")
    assert len(a) <= MAX_SLUG_LENGTH
    assert a != b


def test_slug_is_deterministic():
    name = "y" * 200
    assert safe_slug(name) == safe_slug(name)
