"""G1 (the part not deferred): each script step keeps its own UUID."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fm_saxml.cli import _make_scrubber, _run_pipeline

BAGEL = Path(__file__).parent.parent / "samples" / "by_type" / "whole" / "EverythingBagel.xml"
UUID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")

pytestmark = pytest.mark.skipif(not BAGEL.exists(), reason="samples/by_type fixture not present")


def test_every_step_has_its_uuid_after_scrubbing():
    model = _run_pipeline(BAGEL, _make_scrubber(False, "standard", None, None))
    steps = list(model.entities.script_steps.values())
    assert steps
    assert all(s.uuid and UUID_RE.match(s.uuid) for s in steps)
    assert len({s.uuid for s in steps}) == len(steps)
