"""Combined index and batch summary for a multi-file build."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..parser.input_scan import InputScan, ManifestEntry, SolutionSource
from ..render.markdown.renderer import _make_jinja_env
from ..utils.file_writer import write_text
from .links import BatchFile, BatchLinks

REPORTS_DIR = "Reports"
SUMMARY_PAGE = f"{REPORTS_DIR}/batch-summary.md"


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
    }
