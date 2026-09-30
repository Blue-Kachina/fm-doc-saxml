"""Render a DiffResult as a standalone Markdown report."""

from __future__ import annotations

from pathlib import Path

from ...analyze.diff import DiffResult
from ...utils.file_writer import write_text
from .renderer import _make_jinja_env


def render_diff_markdown(result: DiffResult, out_path: Path) -> None:
    """Render ``result`` to a single Markdown file at ``out_path``."""
    from ...version import get_self_updated_at_display, REPO_URL, REPO_LABEL

    env = _make_jinja_env()
    template = env.get_template("diff.md.j2")
    content = template.render(
        old_source=result.old_source,
        new_source=result.new_source,
        types=result.types,
        script_step_diffs=result.script_step_diffs,
        total_added=result.total_added,
        total_removed=result.total_removed,
        total_changed=result.total_changed,
        has_changes=result.has_changes,
        fm_saxml_updated_at=get_self_updated_at_display(),
        fm_saxml_repo_url=REPO_URL,
        fm_saxml_repo_label=REPO_LABEL,
    )
    write_text(out_path, content)
