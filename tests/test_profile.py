"""Reports/profile.md: the solution profile (data model, scripts, layouts, integrations, unused)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fm_saxml.analyze.profile import EXTERNAL_STEPS, build_profile
from fm_saxml.cli import _run_pipeline
from fm_saxml.render.markdown.renderer import render_markdown

ROOT = Path(__file__).parent.parent
BAGEL = ROOT / "samples" / "by_type" / "whole" / "EverythingBagel.xml"

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


@pytest.fixture()
def model():
    return _run_pipeline(BAGEL)


def test_data_model(model):
    p = build_profile(model)
    assert p.tables == [{"name": "EverythingBagel", "fields": 8,
                         "data_types": [("Number", 3), ("Text", 1), ("Date", 1), ("Time", 1), ("Timestamp", 1), ("Binary", 1)],
                         "field_types": [("Normal", 6), ("Calculated", 1), ("Summary", 1)]}]
    assert p.relationships == {"total": 1, "operators": [("=", 1)], "multi_predicate": 0, "self_joins": 1,
                               "cascade": {"create": {"left": 0, "right": 0}, "delete": {"left": 0, "right": 0}},
                               "sorted_sides": 0}
    assert (p.graph["tos"], p.graph["max_degree"], p.graph["isolated_tos"], p.graph["disconnected_tables"]) == (
        3, 1, ["Empty"], [])


def test_scripts_layouts_and_integrations(model):
    p = build_profile(model)
    assert (p.scripts["total"], p.scripts["steps"], p.scripts["max_steps"]) == (2, 208, 207)
    assert p.scripts["largest"] == [("OneOfEverything", 207), ("Just Beep", 1)]
    assert p.scripts["entry_points"] == [("Just Beep", ["button or object trigger"])]
    assert p.layouts["portals"] == [("EverythingBagel", "EverythingBagel__EVERYTHINGBAGEL__selfJoin")]
    assert p.layouts["by_base_to"] == [("EverythingBagel", 2)]
    assert p.value_lists["by_type"] == [("customValues", 1), ("field", 1)]
    # OneOfEverything holds one of every step, so each external step shows up once, in step order
    assert [c["step"] for c in p.external_calls] == list(EXTERNAL_STEPS)
    assert all(c["count"] == 1 and c["scripts"] == ["OneOfEverything"] for c in p.external_calls)


def test_unused_candidates(model):
    assert build_profile(model).unused == {
        "fields": [], "scripts": ["OneOfEverything"], "layouts": ["CustomMenuSetLayout", "EverythingBagel"],
        "value_lists": ["ValuesFromField"], "custom_functions": ["Test"]}


def test_cascades_are_counted_per_side(model):
    rel = next(iter(model.entities.relationships.values()))
    rel.options.right.delete = True
    rel.options.right.allow_create = True
    assert build_profile(model).relationships["cascade"] == {"create": {"left": 0, "right": 1},
                                                             "delete": {"left": 0, "right": 1}}


def test_use_from_another_file_is_an_entry_point_not_unused(model):
    model.backlinks.setdefault("script:OneOfEverything", []).append(
        {"sourceDocId": "xfile:Other/scriptStep:Start:0003", "sourceEntityType": "scriptStep",
         "relationshipType": "usesScript", "role": "callee", "confidence": "exact"})
    p = build_profile(model)
    assert ("OneOfEverything", ["another file"]) in p.scripts["entry_points"]
    assert "OneOfEverything" not in p.unused["scripts"]


def test_default_layout_counts_as_navigated(model):
    model.file_options.default_layout = "layout:EverythingBagel"
    p = build_profile(model)
    assert p.layouts["not_navigated"] == ["CustomMenuSetLayout"]
    assert p.unused["layouts"] == ["CustomMenuSetLayout"]


def test_report_is_rendered_and_linked(model, tmp_path):
    render_markdown(model, tmp_path)
    page = (tmp_path / "Reports" / "profile.md").read_text(encoding="utf-8")
    assert page.startswith("---\ntitle: Solution Profile\n---")
    assert "| EverythingBagel | 8 | Number: 3, Text: 1" in page
    assert "| Just Beep | button or object trigger |" in page
    assert "| Self-joins (both sides on one table) | 1 |" in page
    assert "\n\n### Script Folders" in page            # every table ends before the next heading
    assert "[profile.md](profile.md)" in (tmp_path / "Reports" / "summary.md").read_text(encoding="utf-8")
