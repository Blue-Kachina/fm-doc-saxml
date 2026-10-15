"""Combined index and batch summary for a multi-file build."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..model.document_model import ScrubSummary
from ..parser.input_scan import InputScan, ManifestEntry, SolutionSource
from ..render.markdown.renderer import _make_jinja_env
from ..utils.file_writer import write_text
from .links import BatchFile, BatchLinks

REPORTS_DIR = "Reports"
SUMMARY_PAGE = f"{REPORTS_DIR}/batch-summary.md"
REDACTIONS_PAGE = f"{REPORTS_DIR}/redactions.md"


@dataclass
class BatchResult:
    scan: InputScan
    files: list[BatchFile]
    links: BatchLinks
    failed: list[tuple[SolutionSource, str]] = field(default_factory=list)
    manifest_missing: list[ManifestEntry] = field(default_factory=list)
    manifest_extra: list[SolutionSource] = field(default_factory=list)
    manifest_hosts: list[str] = field(default_factory=list)  # already scrubbed


def write_batch_reports(result: BatchResult, out: Path) -> None:
    env = _make_jinja_env()
    ctx = _context(result)
    write_text(out / "index.md", env.get_template("batch_index.md.j2").render(**ctx))
    write_text(out / SUMMARY_PAGE, env.get_template("reports/batch_summary.md.j2").render(**ctx))
    write_text(out / REDACTIONS_PAGE, env.get_template("reports/batch_redactions.md.j2").render(**ctx))


def combined_scrubbing(files: list[BatchFile]) -> ScrubSummary | None:
    """Every file's findings as one summary; None when scrubbing was disabled."""
    summaries = [f.model.scrubbing for f in files]
    if not summaries or any(s is None or not s.applied for s in summaries):
        return None
    findings = [finding for s in summaries for finding in s.findings]
    counts = Counter(cat for _ph, cat in {(f.placeholder, f.category) for f in findings if f.action == "redacted"})
    first = summaries[0]
    return ScrubSummary(
        applied=True, level=first.level, engineVersion=first.engine_version,
        placeholderStyle=first.placeholder_style, saltId=first.salt_id,
        counts=dict(sorted(counts.items())), findings=findings,
    )


# Credentials first, then infrastructure, then personal data
_KIND_ORDER = ["Secret", "Infrastructure", "Personal data"]


def category_kind(category: str) -> str:
    from ..scrub.policy import CREDENTIAL_CATEGORIES

    if category in CREDENTIAL_CATEGORIES:
        return "Secret"
    if "host" in category or category.endswith("_ip"):
        return "Infrastructure"
    return "Personal data"


def heading_anchor(text: str) -> str:
    """The id GitHub-style renderers (and the --html viewer) give a heading with this text."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text.strip().lower()))


def _coverage_cell(model) -> str | None:
    from ..analyze.coverage import build_coverage

    report = build_coverage(model)
    if not report.available:
        return None  # built without --coverage, or a v1 export
    if report.ok:
        return "complete"
    parts = []
    if report.problems:
        parts.append(f"{len(report.problems)} check(s) to look at")
    if report.unrecognised:
        parts.append(f"{report.unrecognised_count} unrecognised")
    return "**" + ", ".join(parts) + "**"


def _natural(placeholder: str) -> tuple:
    """[EMAIL#9] before [EMAIL#10]."""
    m = re.search(r"#(\d+)\]$", placeholder)
    return (placeholder[: m.start()], int(m.group(1))) if m else (placeholder, 0)


def _redaction_context(files: list[BatchFile]) -> dict:
    combined = combined_scrubbing(files)
    if combined is None:
        return {"scrubbing": None}
    # One row per placeholder: the same value gets the same placeholder in every file
    by_placeholder: dict[str, dict] = {}
    for f in files:
        for finding in f.model.scrubbing.redactions:
            row = by_placeholder.setdefault(finding.placeholder, {
                "placeholder": finding.placeholder, "category": finding.category, "places": 0, "files": {},
            })
            row["places"] += 1
            row["files"].setdefault(f.folder, f.name)
    placeholders = sorted(by_placeholder.values(), key=lambda r: (-len(r["files"]), _natural(r["placeholder"])))
    groups: dict[str, dict] = {}
    for row in placeholders:
        g = groups.setdefault(row["category"], {
            "category": row["category"], "anchor": heading_anchor(row["category"]),
            "kind": category_kind(row["category"]), "rows": [], "places": 0, "files": set(), "shared": 0,
        })
        g["rows"].append(row)
        g["places"] += row["places"]
        g["files"].update(row["files"])
        g["shared"] += len(row["files"]) > 1
    categories = sorted(groups.values(), key=lambda g: (_KIND_ORDER.index(g["kind"]), g["category"]))
    return {
        "scrubbing": combined,
        "categories": categories,
        "shared_count": sum(1 for r in placeholders if len(r["files"]) > 1),
        "flagged": [(f, finding) for f in files for finding in f.model.scrubbing.flagged],
        "allowed": [(f, finding) for f in files for finding in f.model.scrubbing.allowed],
        "per_file": [
            {"name": f.name, "folder": f.folder, "distinct": f.model.scrubbing.distinct_values,
             "places": len(f.model.scrubbing.redactions), "flagged": len(f.model.scrubbing.flagged)}
            for f in files
        ],
    }


def _context(result: BatchResult) -> dict:
    from ..version import REPO_LABEL, REPO_URL, get_self_updated_at_display

    names = {f.folder: f.name for f in result.files}
    refs_to = result.links.references_between()
    refs_from: dict[str, set[str]] = {}
    for src, targets in refs_to.items():
        for t in targets:
            refs_from.setdefault(t, set()).add(src)

    def rel(path: Path) -> str:
        try:
            return path.relative_to(result.scan.root).as_posix() or path.name
        except ValueError:
            return path.name

    rows = []
    for f in result.files:
        em = f.model.entities
        rows.append({
            "folder": f.folder,
            "href": quote(f.folder) + "/index.md",
            "name": f.name,
            "source": rel(next((s.path for s in result.scan.solutions if s.name == f.name), Path(f.name))),
            "fm_version": f.model.source.file_maker_version,
            "tables": len(em.tables),
            "fields": len(em.fields),
            "layouts": len(em.layouts),
            "scripts": len(em.scripts),
            "refs_to": sorted(names[t] for t in refs_to.get(f.folder, ())),
            "refs_from": sorted(names[s] for s in refs_from.get(f.folder, ())),
            "unresolved": sum(1 for r in f.model.references if r.confidence == "unresolved"),
            "redactions": len(f.model.scrubbing.redactions) if f.model.scrubbing and f.model.scrubbing.applied else None,
            "coverage": _coverage_cell(f.model),
        })

    xrefs = result.links.references
    return {
        "title": result.scan.root.name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fm_saxml_updated_at": get_self_updated_at_display(),
        "fm_saxml_repo_url": REPO_URL,
        "fm_saxml_repo_label": REPO_LABEL,
        "manifest_created": result.scan.manifest.created if result.scan.manifest else "",
        "manifest_hosts": result.manifest_hosts,
        "files": rows,
        "show_coverage": any(r["coverage"] is not None for r in rows),
        "split_count": sum(1 for s in result.scan.solutions if s.is_split),
        "pairings": [
            {"source": names.get(p.source, p.source), "data_source": p.data_source,
             "paths": ", ".join(p.paths), "target": names.get(p.target, "") if p.target else "",
             "match": p.match, "reason": p.reason}
            for p in result.links.pairings
        ],
        "unpaired": [p for p in result.links.pairings if p.target is None],
        "names": names,
        "xref_total": len(xrefs),
        "xref_resolved": sum(1 for r in xrefs if r.resolved),
        "missing_targets": [
            {"source": names[r.source], "ref": r.ref, "reason": r.reason}
            for r in xrefs if r.target is not None and not r.resolved
        ],
        "failed": [{"source": rel(s.path), "reason": reason} for s, reason in result.failed],
        "skipped": [{"source": rel(s.path), "reason": s.reason} for s in result.scan.skipped],
        "manifest_missing": result.manifest_missing,
        "manifest_extra": [rel(s.path) for s in result.manifest_extra],
        "summary_page": SUMMARY_PAGE,
        "redactions_page": REDACTIONS_PAGE,
        **_redaction_context(result.files),
    }
