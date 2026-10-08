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
    """Default output: ``<input name>_docs`` next to the input file."""
    return input_xml.parent / f"{input_xml.stem}_docs"


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
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file to process")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Markdown output directory (defaults to <input name>_docs next to the input file)")] = None,
    model_out: Annotated[Optional[Path], typer.Option("--model-out", help="Path to write model.json")] = None,
    include_json: Annotated[bool, typer.Option("--include-json/--no-include-json", help="Write entities.json/references.json into docs dir")] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Exit non-zero if there are unresolved references")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output directory without prompting")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Assume yes to all interactive prompts")] = False,
    open_when_done: Annotated[bool, typer.Option("--open", help="Open the output folder when finished")] = False,
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.STANDARD,
    scrub_keyword: ScrubKeywordOpt = None,
    scrub_allow: ScrubAllowOpt = None,
    fail_on_secrets: FailOnSecretsOpt = False,
) -> None:
    """Parse a FileMaker XML export and render Markdown documentation."""
    input_xml = _normalize_path(input_xml)
    out = _normalize_path(out) if out else _default_out_dir(input_xml)

    _validate_input(input_xml)
    scrubber = _make_scrubber(disable_scrubbing, scrub_level, scrub_keyword, scrub_allow)
    _confirm_output_directory(out, force=force or yes)

    model = _run_pipeline(input_xml, scrubber)

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


# ---------------------------------------------------------------------------
# parse: XML → model.json
# ---------------------------------------------------------------------------

@app.command()
def parse(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output model.json path")] = Path("./build/model.json"),
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.STANDARD,
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
    disable_scrubbing: DisableScrubbingOpt = False,
    scrub_level: ScrubLevelOpt = ScrubLevel.STANDARD,
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
    _guard_output(scrubber, out)
    _check_fail_on_secrets(fail_on_secrets, model.scrubbing)


# ---------------------------------------------------------------------------
# inspect: print counts and warnings
# ---------------------------------------------------------------------------

@app.command()
def inspect(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file")],
) -> None:
    """Parse a FileMaker XML export and print entity counts and warnings."""
    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml)
    model = _run_pipeline(input_xml, _make_scrubber(False, ScrubLevel.STANDARD, None, None))
    _print_summary(model, verbose=True)


# ---------------------------------------------------------------------------
# validate: check model consistency
# ---------------------------------------------------------------------------

@app.command()
def validate(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file")],
) -> None:
    """Parse and validate a FileMaker XML export, reporting any issues."""
    input_xml = _normalize_path(input_xml)
    _validate_input(input_xml)
    model = _run_pipeline(input_xml, _make_scrubber(False, ScrubLevel.STANDARD, None, None))

    error_warnings = [w for w in model.warnings if w.code not in ("UNUSED_FIELD_CANDIDATE",)]
    if error_warnings:
        console.print(f"[yellow]Validation found {len(error_warnings)} issue(s):[/yellow]")
        for w in error_warnings:
            console.print(f"  [{w.code}] {w.message}")
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
    scrub_level: ScrubLevelOpt = ScrubLevel.STANDARD,
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
    scrub_level: ScrubLevelOpt = ScrubLevel.STANDARD,
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


def _validate_input(path: Path) -> None:
    if not path.exists():
        err_console.print(f"[red]Input file not found: {path}[/red]")
        raise typer.Exit(1)
    if not path.is_file():
        err_console.print(f"[red]Not a file: {path}[/red]")
        raise typer.Exit(1)


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


def _run_pipeline(input_xml: Path, scrubber=None):
    """Parse → scrub → normalize → resolve → analyze. ``scrubber=None`` means scrubbing is disabled."""
    from .parser.saxml_reader import parse_savexml
    from .normalize.normalize import normalize
    from .normalize.references import resolve_references
    from .analyze.backlinks import generate_backlinks
    from .analyze.warnings import generate_warnings
    from .model.document_model import ScrubSummary
    from .model.validation import validate_model

    with _progress() as progress:
        task = progress.add_task(f"Parsing {input_xml.name}", total=7)
        raw = parse_savexml(input_xml)

        xml_errors = [w for w in raw.parse_warnings if w.startswith("XML parse error")]
        if xml_errors:
            _fail(f"'{input_xml.name}' is not valid XML ({xml_errors[0]}).", EXPORT_HINT)
        if not (raw.tables or raw.scripts or raw.layouts or raw.fields):
            _fail(f"'{input_xml.name}' doesn't contain any FileMaker tables, scripts or layouts.", EXPORT_HINT)

        # Scrub the raw records before normalization copies their strings into
        # entities, references and warnings.
        progress.update(task, advance=1, description="Scrubbing secrets")
        source_file = str(input_xml)
        if scrubber is not None:
            source_file = scrubber.scrub_text(source_file, "Source file")
            scrub_summary = scrubber.scrub_raw(raw)
        else:
            scrub_summary = ScrubSummary(applied=False)

        progress.update(task, advance=1, description="Normalizing")
        model = normalize(raw, source_file=source_file, source_path=input_xml)
        model.scrubbing = scrub_summary

        progress.update(task, advance=1, description="Resolving references")
        model = resolve_references(model)

        progress.update(task, advance=1, description="Generating backlinks")
        model = generate_backlinks(model)

        progress.update(task, advance=1, description="Generating warnings")
        model = generate_warnings(model)

        progress.update(task, advance=1, description="Validating model")
        model = validate_model(model)

        progress.update(task, advance=1, description=f"Analyzed {input_xml.name}")

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
        ("File References", len(em.file_references)),
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
