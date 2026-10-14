"""Command-line interface for fm-saxml."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from typer.core import TyperGroup


class _DefaultToBuildGroup(TyperGroup):
    """Let ``fm-saxml export.xml`` mean ``fm-saxml build export.xml``.

    Also makes drag-and-drop onto the executable work, since the OS passes
    the dropped file as the only argument.
    """

    def parse_args(self, ctx, args):
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = ["build", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    name="fm-saxml",
    cls=_DefaultToBuildGroup,
    help=(
        "Generate structured documentation from FileMaker Pro Save As XML exports.\n\n"
        "Quick start: fm-saxml MyExport.xml"
    ),
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"fm-saxml {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True, help="Show the version and exit"),
    ] = False,
) -> None:
    """Generate structured documentation from FileMaker Pro Save As XML exports."""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUT_DIR_NAME = "saxml2doc"
DEFAULT_OUT_DIR = Path(DEFAULT_OUT_DIR_NAME)

# Dropped into every output directory so we can tell our own output from
# an unrelated folder before offering to wipe it.
OUTPUT_MARKER = ".fm-saxml"


# ---------------------------------------------------------------------------
# Scrubbing options (shared by every command that writes output)
# ---------------------------------------------------------------------------

from .scrub.policy import ScrubLevel  # noqa: E402

DisableScrubbingOpt = Annotated[bool, typer.Option(
    "--disable-scrubbing",
    help="Don't redact credentials, internal hosts or personal data. The output will contain them as-is.",
)]
ScrubLevelOpt = Annotated[ScrubLevel, typer.Option(
    "--scrub-level", case_sensitive=False,
    help="secrets: credentials only. standard: also internal hosts, home-folder usernames, emails, card numbers. "
         "strict: also random-looking strings and account / modified-by names.",
)]
ScrubKeywordOpt = Annotated[Optional[list[str]], typer.Option(
    "--scrub-keyword", help="Extra credential keyword, e.g. 'licence' (repeatable)",
)]
ScrubAllowOpt = Annotated[Optional[list[str]], typer.Option(
    "--scrub-allow", help="Regex for values that must never be redacted (repeatable)",
)]


# Secret salt for fingerprint placeholders (stable across runs). An environment
# variable rather than a flag, so it doesn't land in shell history.
SALT_ENV = "FM_SAXML_SCRUB_SALT"

HtmlOpt = Annotated[bool, typer.Option(
    "--html",
    help="Also write index.html for browsing the docs in a web browser, straight from disk "
         "(adds one small .js file per page under _viewer/; the page needs internet access to load its renderer)",
)]

FailOnSecretsOpt = Annotated[bool, typer.Option(
    "--fail-on-secrets",
    help="Exit with status 1 if the export contains hardcoded credentials (redacted or flagged). For CI.",
)]


def _check_fail_on_secrets(enabled: bool, *summaries) -> None:
    """Run after all output is written, so the report is there to explain the failure."""
    if not enabled:
        return
    from .scrub.policy import CREDENTIAL_CATEGORIES

    if any(s is None or not s.applied for s in summaries):
        err_console.print("[yellow]--fail-on-secrets has no effect with --disable-scrubbing: nothing was checked.[/yellow]")
    found = [f for s in summaries if s is not None for f in s.findings
             if f.category in CREDENTIAL_CATEGORIES and f.action != "allowed"]
    if found:
        redacted = sum(1 for f in found if f.action == "redacted")
        err_console.print(
            f"[red]--fail-on-secrets: {redacted} hardcoded credential(s) redacted, "
            f"{len(found) - redacted} flagged for review.[/red]"
        )
        raise typer.Exit(1)


def _make_scrubber(disable: bool, level: ScrubLevel, keywords: Optional[list[str]], allow: Optional[list[str]]):
    if disable:
        err_console.print(
            "[bold red]Scrubbing disabled:[/bold red] credentials, internal hosts and personal data "
            "in the export will be written to the output as-is."
        )
        return None
    from .scrub import PlaceholderRegistry, ScrubPolicy, Scrubber
    from .scrub.placeholders import MIN_SALT_LENGTH

    try:
        policy = ScrubPolicy(level=level, extra_keywords=keywords or [], allow_patterns=allow or [])
    except ValueError as exc:
        _fail(str(exc))
    salt = os.environ.get(SALT_ENV) or None
    if salt and len(salt) < MIN_SALT_LENGTH:
        _fail(f"{SALT_ENV} must be at least {MIN_SALT_LENGTH} characters: a short salt would let "
              "fingerprints of weak passwords be brute-forced.")
    return Scrubber(policy, PlaceholderRegistry(salt))


def _guard_output(scrubber, *targets: Optional[Path]) -> None:
    """Fail the run if any value the scrubber redacted still appears in a written file."""
    if scrubber is None:
        return
    from .scrub import guard_output

    values = scrubber.guard_values()
    leaks = [leak for t in targets if t is not None for leak in guard_output(t, values)]
    if not leaks:
        return
    err_console.print(
        f"[bold red]Scrubbing guard failed:[/bold red] {len(leaks)} redacted value(s) still appear in the output."
    )
    for leak in leaks[:10]:
        # The path itself can hold the value (a page named after a script named after a password).
        err_console.print(f"  {scrubber.substitute(str(leak.path))}:{leak.line}  (the value behind {leak.placeholder})")
    if len(leaks) > 10:
        err_console.print(f"  ... and {len(leaks) - 10} more")
    err_console.print(
        "[dim]These files were written but are not safe to share. This is a bug in fm-saxml: please report it. "
        "If a match is a false positive, exclude the value with --scrub-allow.[/dim]"
    )
    raise typer.Exit(2)


def _default_out_dir(input_xml: Path) -> Path:
    """Default output: ``<input name>_docs`` next to the input file or folder."""
    return input_xml.parent / f"{input_xml.name if input_xml.is_dir() else input_xml.stem}_docs"


def _fail(message: str, hint: str | None = None) -> "typer.Exit":
    err_console.print(f"[red]Error:[/red] {message}")
    if hint:
        err_console.print(f"[dim]{hint}[/dim]")
    raise typer.Exit(1)


def _open_folder(path: Path) -> None:
    """Open ``path`` in the platform's file manager (best effort)."""
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# build: parse + render in one step
# ---------------------------------------------------------------------------

@app.command()
def build(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file, or a folder of them (FileMaker 26 multi-file export)")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Markdown output directory (defaults to <input name>_docs next to the input)")] = None,
    model_out: Annotated[Optional[Path], typer.Option("--model-out", help="Path to write model.json")] = None,
    include_json: Annotated[bool, typer.Option("--include-json/--no-include-json", help="Write entities.json/references.json into docs dir")] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Exit non-zero if there are unresolved references")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output directory without prompting")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Assume yes to all interactive prompts")] = False,
    open_when_done: Annotated[bool, typer.Option("--open", help="Open the output folder when finished")] = False,
    html: HtmlOpt = False,
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.SECRETS,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Parse a FileMaker XML export and render Markdown documentation.

    Given a folder holding several exports (FileMaker 26 can save a copy as XML for
    many files at once), each file gets its own subfolder and references between
    the files become links.
    """
    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml, allow_dir=True)
    out = _normalize_path(out) if out else _default_out_dir(input_xml)
    scan, source = _resolve_input(input_xml)

    if scan is not None and scan.is_batch:
        if model_out:
            _fail("--model-out isn't supported when converting several files.",
                  "Each file's data is in entities.json and references.json inside its own folder.")
        scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
        _build_batch(scan, out, scrubber, include_json=include_json, strict=strict, force=force or yes,
                     html=html, fail_on_secrets=fail_on_secrets, open_when_done=open_when_done)
        return

    scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
    _confirm_output_directory(out, force=force or yes)
    if scan is not None:
        _print_manifest_check(scan)

    model = _run_pipeline(source.path, scrubber, source.fragments or None)

    if model_out:
        model_out = _normalize_path(model_out)
        from .render.json.writer import write_model_json
        write_model_json(model, model_out)
        console.print(f"[green]Model JSON written to {model_out}[/green]")

    _render_markdown_with_progress(model, out)
    console.print(f"[green]Markdown documentation written to {out}[/green]")

    if include_json:
        from .render.json.writer import write_split_json
        write_split_json(model, out)
        console.print(f"[dim]JSON data files written to {out}[/dim]")

    if html:
        _render_html_viewer(out)

    (out / OUTPUT_MARKER).write_text("Generated by fm-saxml. Safe to overwrite.\n", encoding="utf-8")

    _guard_output(scrubber, out, model_out)
    _print_summary(model)
    if model.warnings:
        console.print(f"[dim]See {out / 'Reports' / 'warnings.md'} for details.[/dim]")

    if strict:
        unresolved = sum(1 for r in model.references if r.confidence == "unresolved")
        if unresolved:
            err_console.print(f"[red]--strict: {unresolved} unresolved references found[/red]")
            raise typer.Exit(1)

    _check_fail_on_secrets(fail_on_secrets, model.scrubbing)

    if open_when_done:
        _open_folder(out)


# Folder names a file can't render into: the batch's own report folder and viewer files.
_RESERVED_BATCH_FOLDERS = {"reports", "_viewer"}


def _build_batch(scan, out: Path, scrubber, *, include_json: bool, strict: bool, force: bool,
                 html: bool, fail_on_secrets: bool, open_when_done: bool) -> None:
    """Convert every export in a folder into its own subfolder of ``out``, with cross-file links."""
    from .batch.links import link_batch
    from .batch.report import BatchResult, combined_scrubbing, write_batch_reports

    folders = _batch_folders(scan)
    _confirm_output_directory(out, force=force)
    files, failed, missing, extra = _analyze_batch(scan, scrubber, folders)

    links = link_batch(files)
    _render_batch_with_progress(files, links, out)
    if include_json:
        from .render.json.writer import write_split_json
        for f in files:
            write_split_json(f.model, out / f.folder)

    hosts = sorted({e.host for e in scan.manifest.entries if e.host}) if scan.manifest else []
    if scrubber is not None:
        hosts = [scrubber.scrub_text(h, "Summary.xml host") for h in hosts]
    write_batch_reports(BatchResult(scan=scan, files=files, links=links, failed=failed,
                                    manifest_missing=missing, manifest_extra=extra, manifest_hosts=hosts), out)
    console.print(f"[green]Markdown documentation for {len(files)} files written to {out}[/green]")

    if html:
        _render_html_viewer(out)
    (out / OUTPUT_MARKER).write_text("Generated by fm-saxml. Safe to overwrite.\n", encoding="utf-8")

    _guard_output(scrubber, out)
    _print_batch_summary(files, links)
    _print_scrubbing(combined_scrubbing(files) or files[0].model.scrubbing, report="Reports/redactions.md")

    if strict:
        problems = []
        unresolved = sum(1 for f in files for r in f.model.references if r.confidence == "unresolved")
        if unresolved:
            problems.append(f"{unresolved} unresolved references")
        if missing:
            problems.append(f"{len(missing)} file(s) listed in Summary.xml but not found")
        if scan.skipped:
            problems.append(f"{len(scan.skipped)} XML file(s) skipped")
        ambiguous = [p for p in links.pairings if p.reason.startswith("ambiguous")]
        if ambiguous:
            problems.append(f"{len(ambiguous)} ambiguous data source pairing(s)")
        not_found = [r for r in links.references if r.target is not None and not r.resolved]
        if not_found:
            problems.append(f"{len(not_found)} cross-file target(s) not found")
        if problems:
            err_console.print(f"[red]--strict: {'; '.join(problems)}[/red]")
            raise typer.Exit(1)

    _check_fail_on_secrets(fail_on_secrets, *(f.model.scrubbing for f in files))
    if failed:
        raise typer.Exit(1)
    if open_when_done:
        _open_folder(out)


def _batch_folders(scan) -> dict[str, str]:
    """Output subfolder for each export (by its name). Fails before anything is written on a clash."""
    from .normalize.names import safe_slug

    folders: dict[str, str] = {}
    seen: dict[str, Path] = {}
    for s in scan.solutions:
        folder = safe_slug(s.name)
        key = folder.casefold()
        if key in seen:
            _fail(f"Two exports would both be written to '{folder}/': {seen[key]} and {s.path}.",
                  "Remove one of them from the folder, or convert them separately.")
        if key in _RESERVED_BATCH_FOLDERS:
            _fail(f"'{s.path.name}' would be written to '{folder}/', which is reserved for the batch's own files.",
                  "Convert this file on its own instead.")
        seen[key] = s.path
        folders[s.name] = folder
    return folders


def _analyze_batch(scan, scrubber, folders: dict[str, str]):
    """Analyze each export on its own. Returns (files, failed, manifest missing, manifest extra)."""
    from .batch.links import BatchFile

    console.print(f"Found {len(scan.solutions)} FileMaker exports in {scan.root}")
    missing, extra = _print_manifest_check(scan)
    for s in scan.skipped:
        console.print(f"[yellow]Skipping {s.path.name}: {s.reason}[/yellow]")

    # Scrub every file before normalizing any: a value found in a later file must
    # also be redacted in the earlier ones, which only a second pass can do.
    scrubbed = []
    failed = []
    with _progress() as progress:
        task = progress.add_task("Reading and scrubbing", total=len(scan.solutions))
        for s in scan.solutions:
            progress.update(task, description=f"Reading {s.name}")
            try:
                parsed = _parse_and_scrub(s.path, scrubber, s.fragments or None, step=lambda _desc: None)
            except _InputProblem as exc:
                failed.append((s, str(exc)))
            else:
                scrubbed.append((s, parsed, len(scrubber.registry) if scrubber is not None else 0))
            progress.advance(task)

    files: list[BatchFile] = []
    with _progress() as progress:
        task = progress.add_task("Analyzing files", total=len(scrubbed))
        while scrubbed:
            s, (raw, summary, source_file, path), known = scrubbed.pop(0)
            progress.update(task, description=f"Analyzing {s.name}")
            if scrubber is not None and len(scrubber.registry) > known:
                # Pass-1 previews were taken before the later files' values were known.
                summary = scrubber.summary(scrubber.refresh(summary.findings) + scrubber.scrub_raw(raw).findings)
                source_file = scrubber.substitute(source_file)
            model = _normalize_scrubbed(raw, summary, source_file, path, step=lambda _desc: None)
            del raw  # keep only the models in memory
            files.append(BatchFile(folder=folders[s.name], name=s.name, model=model))
            progress.advance(task)
    for s, reason in failed:
        err_console.print(f"[red]Not converted:[/red] {reason}")
    if not files:
        _fail("None of the exports could be converted.", EXPORT_HINT)
    return files, failed, missing, extra


def _print_manifest_check(scan):
    """Compare a folder's Summary.xml with the exports found. Returns (missing, extra)."""
    from .parser.input_scan import manifest_mismatches

    missing, extra = manifest_mismatches(scan)
    for entry in missing:
        console.print(f"[yellow]Summary.xml lists {entry.fmp_file_name}, but no export for it was found.[/yellow]")
    for s in extra:
        console.print(f"[dim]{s.path.name} isn't listed in Summary.xml; converting it anyway.[/dim]")
    return missing, extra


def _render_batch_with_progress(files, links, out: Path) -> None:
    from .render.markdown.link_resolver import LinkResolver
    from .render.markdown.renderer import render_markdown
    from .utils.file_writer import on_write

    total = sum(LinkResolver(f.model).page_count + 25 for f in files)
    written = 0
    with _progress() as progress:
        task = progress.add_task("Writing pages", total=total)

        def tick(_path: Path) -> None:
            nonlocal written
            written += 1
            progress.update(task, completed=written, total=max(total, written))

        with on_write(tick):
            for f in files:
                progress.update(task, description=f"Writing {f.name}")
                render_markdown(f.model, out / f.folder, links.cross_file.get(f.folder))
        progress.update(task, completed=written, total=written, description=f"Wrote {written} pages")


def _print_batch_summary(files, links) -> None:
    tbl = Table(title="Files", show_header=True)
    tbl.add_column("File", style="cyan")
    for col in ("Tables", "Fields", "Layouts", "Scripts", "Unresolved", "Warnings"):
        tbl.add_column(col, justify="right", style="green")
    for f in files:
        em = f.model.entities
        unresolved = sum(1 for r in f.model.references if r.confidence == "unresolved")
        tbl.add_row(f.name, str(len(em.tables)), str(len(em.fields)), str(len(em.layouts)),
                    str(len(em.scripts)), str(unresolved), str(len(f.model.warnings)))
    console.print(tbl)

    xrefs = links.references
    resolved = sum(1 for r in xrefs if r.resolved)
    console.print(f"[dim]Cross-file references: {len(xrefs)} total, {resolved} resolved, "
                  f"{len(xrefs) - resolved} unresolved[/dim]")
    for p in links.unpaired:
        console.print(f"[dim]  {p.source}: data source '{p.data_source}' not paired ({p.reason})[/dim]")


# ---------------------------------------------------------------------------
# parse: XML → model.json
# ---------------------------------------------------------------------------

@app.command()
def parse(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output model.json path")] = Path("./build/model.json"),
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.SECRETS,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Parse a FileMaker XML export and save the normalized model as JSON."""
    input_xml = _normalize_path(input_xml)
    out = _normalize_path(out)

    _validate_input(input_xml)
    scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
    model = _run_pipeline(input_xml, scrubber)

    from .render.json.writer import write_model_json
    write_model_json(model, out)
    console.print(f"[green]Model JSON written to {out}[/green]")
    _guard_output(scrubber, out)
    _print_summary(model)
    _check_fail_on_secrets(fail_on_secrets, model.scrubbing)


# ---------------------------------------------------------------------------
# render: model.json → Markdown
# ---------------------------------------------------------------------------

@app.command()
def render(
    format: Annotated[str, typer.Argument(help="Output format: 'markdown'")] = "markdown",
    model_json: Annotated[Path, typer.Option("--model", "-m", help="Path to model.json")] = Path("./build/model.json"),
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory (defaults to ./saxml2doc)")] = DEFAULT_OUT_DIR,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output directory without prompting")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Assume yes to all interactive prompts")] = False,
    html: HtmlOpt = False,
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.SECRETS,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Render an existing model.json into documentation."""
    model_json = _normalize_path(model_json)
    out = _normalize_path(out)

    if not model_json.exists():
        err_console.print(f"[red]Model file not found: {model_json}[/red]")
        raise typer.Exit(1)
    if format.lower() != "markdown":
        err_console.print(f"[red]Unknown format '{format}'. Supported: markdown[/red]")
        raise typer.Exit(1)

    scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
    _confirm_output_directory(out, force=force or yes)

    model = _load_model_json(model_json, scrubber)
    _render_markdown_with_progress(model, out)
    console.print(f"[green]Markdown documentation written to {out}[/green]")
    if html:
        _render_html_viewer(out)
    _guard_output(scrubber, out)
    _check_fail_on_secrets(fail_on_secrets, model.scrubbing)


# ---------------------------------------------------------------------------
# inspect: print counts and warnings
# ---------------------------------------------------------------------------

@app.command()
def inspect(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file, or a folder of them")],
) -> None:
    """Parse a FileMaker XML export and print entity counts and warnings."""
    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml, allow_dir=True)
    scan, source = _resolve_input(input_xml)
    scrubber = _make_scrubber(False, ScrubLevel.SECRETS, None, None)
    if scan is not None and scan.is_batch:
        from .batch.links import link_batch

        files, failed, _missing, _extra = _analyze_batch(scan, scrubber, _batch_folders(scan))
        _print_batch_summary(files, link_batch(files))
        if failed:
            raise typer.Exit(1)
        return
    model = _run_pipeline(source.path, scrubber, source.fragments or None)
    _print_summary(model, verbose=True)


# ---------------------------------------------------------------------------
# validate: check model consistency
# ---------------------------------------------------------------------------

@app.command()
def validate(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file, or a folder of them")],
) -> None:
    """Parse and validate a FileMaker XML export, reporting any issues."""
    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml, allow_dir=True)
    scan, source = _resolve_input(input_xml)
    scrubber = _make_scrubber(False, ScrubLevel.SECRETS, None, None)
    if scan is not None and scan.is_batch:
        from .batch.links import link_batch

        files, failed, missing, _extra = _analyze_batch(scan, scrubber, _batch_folders(scan))
        links = link_batch(files)
        issues = [f"{f.name}: [{w.code}] {w.message}" for f in files for w in f.model.warnings
                  if w.code not in ("UNUSED_FIELD_CANDIDATE",)]
        issues += [f"{p.source}: data source '{p.data_source}' {p.reason}" for p in links.pairings
                   if p.reason.startswith("ambiguous")]
        issues += [f"{r.source}: {r.reason}" for r in links.references if r.target is not None and not r.resolved]
        issues += [f"Summary.xml lists {m.fmp_file_name}, but no export for it was found" for m in missing]
        issues += [f"{s.path.name}: {reason}" for s, reason in failed]
    else:
        model = _run_pipeline(source.path, scrubber, source.fragments or None)
        issues = [f"[{w.code}] {w.message}" for w in model.warnings if w.code not in ("UNUSED_FIELD_CANDIDATE",)]

    if issues:
        console.print(f"[yellow]Validation found {len(issues)} issue(s):[/yellow]")
        for issue in issues:
            console.print(f"  {issue}")
        raise typer.Exit(1)
    else:
        console.print("[green]Validation passed — no critical issues found.[/green]")


# ---------------------------------------------------------------------------
# diff: compare two exports (XML or model.json)
# ---------------------------------------------------------------------------

@app.command()
def diff(
    old_input: Annotated[Path, typer.Argument(help="Baseline: a SaveAsXML file or a previously-saved model.json")],
    new_input: Annotated[Path, typer.Argument(help="Comparison: a SaveAsXML file or a previously-saved model.json")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Write a Markdown diff report to this path")] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit non-zero if any difference is found")] = False,
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.SECRETS,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Compare two FileMaker exports and report what changed between them."""
    old_input = _normalize_path(old_input)
    new_input = _normalize_path(new_input)
    _validate_input(old_input)
    _validate_input(new_input)

    # One scrubber for both sides: a value present in both gets the same
    # placeholder, so an unchanged secret doesn't show as a change and a
    # changed one shows as a different placeholder.
    scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
    old_model = _load_model_for_diff(old_input, label="baseline", scrubber=scrubber)
    new_model = _load_model_for_diff(new_input, label="comparison", scrubber=scrubber)
    if scrubber is not None:
        _warn_incomparable_placeholders(old_input, old_model, new_input, new_model)

    from .analyze.diff import compute_diff
    result = compute_diff(old_model, new_model)

    _print_diff_summary(result)

    if out:
        out = _normalize_path(out)
        from .render.markdown.diff_renderer import render_diff_markdown
        render_diff_markdown(result, out)
        console.print(f"[green]Diff report written to {out}[/green]")
        _guard_output(scrubber, out)

    _check_fail_on_secrets(fail_on_secrets, old_model.scrubbing, new_model.scrubbing)

    if strict and result.has_changes:
        err_console.print("[red]--strict: differences were found[/red]")
        raise typer.Exit(1)


def _load_model_for_diff(path: Path, *, label: str, scrubber=None):
    if path.suffix.lower() == ".json":
        console.print(f"[dim]Loading {label} model from {path}...[/dim]")
        return _load_model_json(path, scrubber)
    return _run_pipeline(path, scrubber)


@app.command()
def scrub(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker Save a Copy as XML export to scrub")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Scrubbed copy (defaults to <input name>.scrubbed.xml next to the input)")] = None,
    report: Annotated[Optional[Path], typer.Option("--report", help="Also write a Markdown redaction report here")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output file without prompting")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Assume yes to all interactive prompts")] = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.SECRETS,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Write a copy of a Save a Copy as XML export with credentials and personal data redacted.

    Use it to share the raw XML itself (with an AI tool, another developer, a bug report).
    Every copy of each value is replaced: the calculation, its tokenized ChunkList and the
    rendered step text in DDR_INFO. Content hashes of changed elements are removed.
    """
    from .scrub.xml_writer import UnsupportedFormat, scrub_xml_file

    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml)
    out = _normalize_path(out) if out else input_xml.with_name(f"{input_xml.stem}.scrubbed{input_xml.suffix}")
    if out.resolve() == input_xml.resolve():
        _fail("The output would overwrite the input export.", "Choose another path with --out.")
    if out.exists() and not (force or yes):
        if not typer.confirm(f"{out} already exists. Overwrite it?", default=False):
            console.print("[yellow]Cancelled. No files were written.[/yellow]")
            raise typer.Exit(0)

    scrubber = _make_scrubber(False, scrub_level, scrub_keyword, scrub_allow)
    with console.status(f"Scrubbing {input_xml.name}"):
        try:
            result = scrub_xml_file(input_xml, out, scrubber)
        except UnsupportedFormat as exc:
            _fail(f"'{input_xml.name}': {exc}", EXPORT_HINT)
        except ValueError as exc:
            _fail(f"'{input_xml.name}' is {exc}.", EXPORT_HINT)

    console.print(
        f"[green]Scrubbed copy written to {out}[/green] "
        f"[dim]({result.nodes_changed} element(s) changed, {result.hashes_removed} content hash(es) removed)[/dim]"
    )
    if result.reformatted:
        console.print("[yellow]Note: some edits couldn't be patched into the original text exactly, so the file was "
                      "re-serialized. It's equivalent XML, but formatting differs from the input, so a plain "
                      "diff will show more than the redactions.[/yellow]")
    if report:
        report = _normalize_path(report)
        from .render.markdown.renderer import _make_jinja_env
        from .utils.file_writer import write_text

        write_text(report, _make_jinja_env().get_template("reports/redactions.md.j2").render(scrubbing=result.summary))
        console.print(f"[dim]Redaction report written to {report}[/dim]")

    if result.leaks:
        # Same failure as the build guard, for the file we just wrote.
        _guard_output(scrubber, out)
    _guard_output(scrubber, report)
    _print_scrubbing(result.summary, report=str(report) if report else "")
    _check_fail_on_secrets(fail_on_secrets, result.summary)


def _warn_incomparable_placeholders(old_path: Path, old_model, new_path: Path, new_model) -> None:
    """A model.json scrubbed in an earlier run numbered its placeholders on its own,
    so [REDACTED:password#1] on each side may be different values (or the same one)."""
    if old_path.suffix.lower() != ".json" and new_path.suffix.lower() != ".json":
        return  # both scrubbed just now, by one shared registry
    a, b = old_model.scrubbing, new_model.scrubbing
    same_salt = (a and b and a.placeholder_style == b.placeholder_style == "fingerprint"
                 and a.salt_id and a.salt_id == b.salt_id)
    if not same_salt:
        console.print(
            "[yellow]Note: at least one side is a saved model.json, so redacted values on the two sides "
            f"can't be compared: a changed secret may show as unchanged, or the reverse. Set {SALT_ENV} "
            "to the same private value for every run to get comparable fingerprint placeholders.[/yellow]"
        )


def _load_model_json(path: Path, scrubber):
    """Load a saved model, scrubbing it first if it was saved unscrubbed or by an older engine."""
    import orjson
    from .model.document_model import DocumentModel

    data = orjson.loads(path.read_bytes())
    previous = data.get("scrubbing") or {}
    if scrubber is not None:
        from .scrub import ENGINE_VERSION

        if not previous.get("applied") or previous.get("engineVersion") != ENGINE_VERSION:
            reason = "was saved without scrubbing" if not previous.get("applied") else "was scrubbed by an older version"
            console.print(f"[dim]{path.name} {reason}; scrubbing it now.[/dim]")
            scrubber.scrub_model_data(data)
            if previous.get("applied"):
                data["scrubbing"]["findings"] = previous.get("findings", []) + data["scrubbing"]["findings"]
    return DocumentModel.model_validate(data)


def _print_diff_summary(result) -> None:
    tbl = Table(title="Diff Summary", show_header=True)
    tbl.add_column("Entity Type", style="cyan")
    tbl.add_column("Added", justify="right", style="green")
    tbl.add_column("Removed", justify="right", style="red")
    tbl.add_column("Changed", justify="right", style="yellow")
    for t in result.types:
        if t.has_changes:
            tbl.add_row(t.label, str(len(t.added)), str(len(t.removed)), str(len(t.changed)))
    console.print(tbl)

    if result.script_step_diffs:
        console.print(f"[dim]Scripts with step changes: {len(result.script_step_diffs)}[/dim]")

    if not result.has_changes:
        console.print("[green]No differences detected.[/green]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_path(path: Path) -> Path:
    """Expand ~ and env vars and return an absolute Path.

    Works uniformly across Windows (drive letters, UNC paths like
    ``\\\\server\\share\\...``), macOS, and Linux because ``pathlib.Path`` is
    platform-aware: on Windows it's a ``WindowsPath``, on POSIX systems it's
    a ``PosixPath``. We avoid ``str.replace`` on separators or any
    platform-specific manipulation here.
    """
    if path is None:
        return path
    # Expand environment variables (e.g. %USERPROFILE%, $HOME) and ~
    import os
    expanded = os.path.expandvars(str(path))
    p = Path(expanded).expanduser()
    # Don't resolve() because it would fail on not-yet-created output dirs;
    # absolute() preserves intent without requiring the path to exist.
    if not p.is_absolute():
        try:
            p = p.absolute()
        except OSError:
            pass
    return p


def _validate_input(path: Path, allow_dir: bool = False) -> None:
    if not path.exists():
        err_console.print(f"[red]Input file not found: {path}[/red]")
        raise typer.Exit(1)
    if path.is_dir() and allow_dir:
        return
    if not path.is_file():
        err_console.print(f"[red]Not a file: {path}[/red]")
        raise typer.Exit(1)


def _resolve_input(path: Path):
    """What to convert: ``(scan, source)`` for a file or folder input.

    ``scan`` is set for a folder (``scan.is_batch`` when it holds several exports);
    ``source`` is the one export to convert in single-file mode.
    """
    from .parser.input_scan import SolutionSource, scan_input, sniff_root

    if path.is_file():
        root = sniff_root(path)
        if not isinstance(root, str) and root.is_manifest:
            _fail(f"'{path.name}' is the summary of a multi-file export, not an export itself.",
                  f"Pass the folder that contains it instead: {path.parent}")
        if not isinstance(root, str) and root.is_fragment:
            _fail(f"'{path.name}' is one catalog of a \"separate catalogs\" export.",
                  f"Pass the folder that contains it instead: {path.parent}")
        return None, SolutionSource(path=path)

    scan = scan_input(path)
    if not scan.solutions:
        _fail(f"No FileMaker Save a Copy as XML exports found in {path}.", EXPORT_HINT)
    return scan, (None if scan.is_batch else scan.solutions[0])


EXPORT_HINT = "In FileMaker Pro: Tools > Save a Copy as XML..., then run fm-saxml on that file."


def _confirm_output_directory(out_dir: Path, force: bool = False) -> None:
    """Ensure the output directory is empty, or get explicit user consent.

    Behavior:
    - If ``out_dir`` doesn't exist, do nothing (the renderer will create it).
    - If ``out_dir`` exists but is empty, do nothing.
    - If ``out_dir`` exists and is non-empty, prompt the user to overwrite
      (which clears the directory) or cancel. ``--force``/``--yes`` skip the
      prompt and overwrite.
    - If ``out_dir`` exists but is a file (not a directory), refuse.
    """
    if not out_dir.exists():
        return

    if out_dir.is_file():
        err_console.print(f"[red]Output path exists and is a file, not a directory: {out_dir}[/red]")
        raise typer.Exit(1)

    # Directory exists — check if empty
    try:
        is_empty = not any(out_dir.iterdir())
    except OSError as exc:
        err_console.print(f"[red]Cannot read output directory {out_dir}: {exc}[/red]")
        raise typer.Exit(1)

    if is_empty:
        return

    if force:
        _wipe_directory(out_dir)
        return

    console.print(f"[yellow]Output directory already exists and is not empty:[/yellow] {out_dir}")
    if not (out_dir / OUTPUT_MARKER).exists():
        console.print(
            "[bold red]Warning:[/bold red] this folder was not created by fm-saxml. "
            "Overwriting will delete everything in it."
        )
    choice = typer.prompt(
        "Overwrite contents (o), cancel (c)?",
        default="c",
        show_default=True,
    ).strip().lower()

    if choice in ("o", "overwrite", "y", "yes"):
        _wipe_directory(out_dir)
    else:
        console.print("[yellow]Cancelled. No files were written.[/yellow]")
        raise typer.Exit(0)


def _wipe_directory(out_dir: Path) -> None:
    """Remove every entry inside ``out_dir`` (the directory itself is preserved)."""
    for child in out_dir.iterdir():
        if child.is_symlink() or child.is_file():
            try:
                child.unlink()
            except OSError as exc:
                err_console.print(f"[red]Could not remove {child}: {exc}[/red]")
                raise typer.Exit(1)
        else:
            try:
                shutil.rmtree(child)
            except OSError as exc:
                err_console.print(f"[red]Could not remove {child}: {exc}[/red]")
                raise typer.Exit(1)


class _InputProblem(Exception):
    """An input that isn't a usable export. Ends a single-file run; skips the file in a batch."""


def _run_pipeline(input_xml: Path, scrubber=None, fragments: Optional[list[Path]] = None):
    """Parse → scrub → normalize → resolve → analyze. ``scrubber=None`` means scrubbing is disabled."""
    with _progress() as progress:
        task = progress.add_task(f"Parsing {input_xml.name}", total=7)
        try:
            return _analyze(
                input_xml, scrubber, fragments,
                step=lambda desc: progress.update(task, advance=1, description=desc),
            )
        except _InputProblem as exc:
            _fail(str(exc), EXPORT_HINT)


def _analyze(input_xml: Path, scrubber, fragments: Optional[list[Path]], step):
    """The pipeline itself. ``step(description)`` is called as each of its 7 stages finishes.

    ``input_xml`` may be a separate-catalogs folder; ``fragments`` then lists its catalog XMLs.
    """
    return _normalize_scrubbed(*_parse_and_scrub(input_xml, scrubber, fragments, step), step)


def _parse_and_scrub(input_xml: Path, scrubber, fragments: Optional[list[Path]], step):
    """Stages 1-2. Returns what ``_normalize_scrubbed`` needs: (raw, scrub summary, source file, path)."""
    from .parser.saxml_reader import parse_savexml
    from .model.document_model import ScrubSummary

    raw = parse_savexml(input_xml, fragments)

    xml_errors = [w for w in raw.parse_warnings if w.startswith("XML parse error")]
    if xml_errors:
        raise _InputProblem(f"'{input_xml.name}' is not valid XML ({xml_errors[0]}).")
    if not (raw.tables or raw.scripts or raw.layouts or raw.fields):
        raise _InputProblem(f"'{input_xml.name}' doesn't contain any FileMaker tables, scripts or layouts.")

    # Scrub the raw records before normalization copies their strings into
    # entities, references and warnings.
    step("Scrubbing secrets")
    source_file = str(input_xml)
    if scrubber is not None:
        source_file = scrubber.scrub_text(source_file, "Source file")
        scrub_summary = scrubber.scrub_raw(raw)
    else:
        scrub_summary = ScrubSummary(applied=False)
    return raw, scrub_summary, source_file, input_xml


def _normalize_scrubbed(raw, scrub_summary, source_file: str, input_xml: Path, step):
    """Stages 3-7, on a raw model that has already been scrubbed."""
    from .normalize.normalize import normalize
    from .normalize.references import resolve_references
    from .analyze.backlinks import generate_backlinks
    from .analyze.warnings import generate_warnings
    from .model.validation import validate_model

    step("Normalizing")
    model = normalize(raw, source_file=source_file, source_path=input_xml)
    model.scrubbing = scrub_summary

    step("Resolving references")
    model = resolve_references(model)

    step("Generating backlinks")
    model = generate_backlinks(model)

    step("Generating warnings")
    model = generate_warnings(model)

    step("Validating model")
    model = validate_model(model)

    step(f"Analyzed {input_xml.name}")
    return model


def _progress() -> Progress:
    """Spinner + bar + elapsed time. Rich degrades gracefully when output is piped."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def _render_markdown_with_progress(model, out: Path) -> None:
    """Render Markdown, advancing a progress bar once per page written."""
    from .render.markdown.link_resolver import LinkResolver
    from .render.markdown.renderer import render_markdown
    from .utils.file_writer import on_write

    # Entity pages plus a rough allowance for section indexes and reports.
    total = LinkResolver(model).page_count + 25
    written = 0

    with _progress() as progress:
        task = progress.add_task("Writing pages", total=total)

        def tick(_path: Path) -> None:
            nonlocal written
            written += 1
            progress.update(task, completed=written, total=max(total, written))

        with on_write(tick):
            render_markdown(model, out)
        progress.update(task, completed=written, total=written, description=f"Wrote {written} pages")


def _render_html_viewer(out: Path) -> None:
    from .render.html import render_html_viewer

    pages = render_html_viewer(out)
    console.print(f"[green]HTML viewer written to {out / 'index.html'}[/green] [dim]({pages} pages)[/dim]")


def _print_summary(model, verbose: bool = False) -> None:
    em = model.entities
    tbl = Table(title="Entity Counts", show_header=True)
    tbl.add_column("Entity Type", style="cyan")
    tbl.add_column("Count", justify="right", style="green")
    rows = [
        ("Tables", len(em.tables)),
        ("Fields", len(em.fields)),
        ("Table Occurrences", len(em.table_occurrences)),
        ("Relationships", len(em.relationships)),
        ("Layouts", len(em.layouts)),
        ("Layout Objects", len(em.layout_objects)),
        ("Scripts", len(em.scripts)),
        ("Script Steps", len(em.script_steps)),
        ("Custom Functions", len(em.custom_functions)),
        ("Value Lists", len(em.value_lists)),
        ("Privilege Sets", len(em.privilege_sets)),
        ("Accounts", len(em.accounts)),
        ("Extended Privileges", len(em.extended_privileges)),
        ("Custom Menus", len(em.custom_menus)),
        ("Custom Menu Sets", len(em.custom_menu_sets)),
        ("Themes", len(em.themes)),
        ("File Access", len(em.file_references)),
    ]
    for name, count in rows:
        tbl.add_row(name, str(count))
    console.print(tbl)

    unresolved = sum(1 for r in model.references if r.confidence == "unresolved")
    external = sum(1 for r in model.references if r.confidence == "external")
    console.print(f"[dim]References: {len(model.references)} total, {unresolved} unresolved, {external} external[/dim]")
    console.print(f"[dim]Warnings: {len(model.warnings)}[/dim]")

    _print_scrubbing(model.scrubbing)

    if verbose and model.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        from collections import Counter
        by_code = Counter(w.code for w in model.warnings)
        for code, count in by_code.most_common():
            console.print(f"  {code}: {count}")


def _print_scrubbing(scrubbing, report: str = "Reports/redactions.md") -> None:
    if scrubbing is not None and scrubbing.applied:
        if scrubbing.redactions:
            by_category = ", ".join(f"{n} {cat}" for cat, n in scrubbing.counts.items())
            console.print(
                f"[cyan]Scrubbed {scrubbing.distinct_values} value(s) in {len(scrubbing.redactions)} place(s) "
                f"({by_category}).{f' See {report}.' if report else ''}[/cyan]"
            )
        elif not scrubbing.flagged:
            console.print("[dim]Scrubbing: nothing needed redacting.[/dim]")
        if scrubbing.flagged:
            console.print(
                f"[yellow]{len(scrubbing.flagged)} possible credential(s) flagged for review "
                f"(left unchanged).{f' See {report}.' if report else ''}[/yellow]"
            )
        if scrubbing.allowed:
            console.print(f"[dim]{len(scrubbing.allowed)} item(s) marked fm-saxml:allow were left as written.[/dim]")
    elif scrubbing is not None:
        console.print("[bold yellow]Scrubbing was disabled: output may contain credentials and personal data.[/bold yellow]")


# ---------------------------------------------------------------------------
# doctor: environment self-check
# ---------------------------------------------------------------------------

@app.command()
def doctor() -> None:
    """Print environment details useful for troubleshooting."""
    import platform
    import tempfile

    from lxml import etree

    console.print(f"fm-saxml     : {_package_version()}")
    console.print(f"Python       : {platform.python_version()} ({platform.python_implementation()})")
    console.print(f"Platform     : {platform.platform()}")
    console.print(f"lxml         : {etree.LXML_VERSION}")
    console.print(f"stdout enc.  : {sys.stdout.encoding}")
    console.print(f"Working dir  : {Path.cwd()}")
    try:
        with tempfile.TemporaryDirectory(dir=Path.cwd()):
            console.print("[green]Working directory is writable.[/green]")
    except OSError as exc:
        console.print(f"[red]Working directory is NOT writable: {exc}[/red]")
        raise typer.Exit(1)


def _package_version() -> str:
    from . import __version__

    return __version__


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _tolerate_unencodable_output() -> None:
    """Print '?' instead of crashing when the output encoding can't represent a character.

    On Windows, NUL (``> NUL``, ``subprocess.DEVNULL``) reports itself as a terminal with a
    cp1252 encoding, so Rich animates its spinner and the braille frames raised
    UnicodeEncodeError, failing the whole command in CI or scripted runs.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a TextIOWrapper (e.g. replaced by a test harness)
            pass


def main() -> None:
    """Console entry point: friendly one-line errors instead of tracebacks."""
    from . import __version__
    from .utils import update_check
    from .version import REPO_URL

    _tolerate_unencodable_output()
    notifier = update_check.start(__version__, REPO_URL)
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("FM_SAXML_DEBUG"):
            raise
        err_console.print(f"[red]Error:[/red] {exc}")
        err_console.print("[dim]Set FM_SAXML_DEBUG=1 for the full traceback.[/dim]")
        sys.exit(1)
    finally:
        # Runs after normal exits too (Typer exits via SystemExit).
        if notifier and sys.exc_info()[0] in (None, SystemExit):
            notice = notifier.message()
            if notice:
                err_console.print(f"[dim]{notice}[/dim]")
                err_console.print("[dim]Set FM_SAXML_NO_UPDATE_CHECK=1 to stop these checks.[/dim]")


if __name__ == "__main__":
    main()
