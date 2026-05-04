"""Command-line interface for fm-saxml."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="fm-saxml",
    help="Generate structured documentation from FileMaker Pro Save As XML exports.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUT_DIR_NAME = "saxml2doc"
DEFAULT_OUT_DIR = Path(DEFAULT_OUT_DIR_NAME)


# ---------------------------------------------------------------------------
# build: parse + render in one step
# ---------------------------------------------------------------------------

@app.command()
def build(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file to process")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Markdown output directory (defaults to ./saxml2doc)")] = DEFAULT_OUT_DIR,
    model_out: Annotated[Optional[Path], typer.Option("--model-out", help="Path to write model.json")] = None,
    include_json: Annotated[bool, typer.Option("--include-json/--no-include-json", help="Write entities.json/references.json into docs dir")] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Exit non-zero if there are unresolved references")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output directory without prompting")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Assume yes to all interactive prompts")] = False,
) -> None:
    """Parse a FileMaker XML export and render Markdown documentation."""
    input_xml = _normalize_path(input_xml)
    out = _normalize_path(out)

    _validate_input(input_xml)
    _confirm_output_directory(out, force=force or yes)

    model = _run_pipeline(input_xml)

    if model_out:
        model_out = _normalize_path(model_out)
        from .render.json.writer import write_model_json
        write_model_json(model, model_out)
        console.print(f"[green]Model JSON written to {model_out}[/green]")

    from .render.markdown.renderer import render_markdown
    render_markdown(model, out)
    console.print(f"[green]Markdown documentation written to {out}[/green]")

    if include_json:
        from .render.json.writer import write_split_json
        write_split_json(model, out)
        console.print(f"[dim]JSON data files written to {out}[/dim]")

    _print_summary(model)

    if strict:
        unresolved = sum(1 for r in model.references if r.confidence == "unresolved")
        if unresolved:
            err_console.print(f"[red]--strict: {unresolved} unresolved references found[/red]")
            raise typer.Exit(1)


# ---------------------------------------------------------------------------
# parse: XML → model.json
# ---------------------------------------------------------------------------

@app.command()
def parse(
    input_xml: Annotated[Path, typer.Argument(help="FileMaker SaveAsXML file")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output model.json path")] = Path("./build/model.json"),
) -> None:
    """Parse a FileMaker XML export and save the normalized model as JSON."""
    input_xml = _normalize_path(input_xml)
    out = _normalize_path(out)

    _validate_input(input_xml)
    model = _run_pipeline(input_xml)

    from .render.json.writer import write_model_json
    write_model_json(model, out)
    console.print(f"[green]Model JSON written to {out}[/green]")
    _print_summary(model)


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
) -> None:
    """Render an existing model.json into documentation."""
    model_json = _normalize_path(model_json)
    out = _normalize_path(out)

    if not model_json.exists():
        err_console.print(f"[red]Model file not found: {model_json}[/red]")
        raise typer.Exit(1)

    _confirm_output_directory(out, force=force or yes)

    import orjson
    from .model.document_model import DocumentModel

    raw = orjson.loads(model_json.read_bytes())
    model = DocumentModel.model_validate(raw)

    if format.lower() == "markdown":
        from .render.markdown.renderer import render_markdown
        render_markdown(model, out)
        console.print(f"[green]Markdown documentation written to {out}[/green]")
    else:
        err_console.print(f"[red]Unknown format '{format}'. Supported: markdown[/red]")
        raise typer.Exit(1)


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
    model = _run_pipeline(input_xml)
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
    model = _run_pipeline(input_xml)

    error_warnings = [w for w in model.warnings if w.code not in ("UNUSED_FIELD_CANDIDATE",)]
    if error_warnings:
        console.print(f"[yellow]Validation found {len(error_warnings)} issue(s):[/yellow]")
        for w in error_warnings:
            console.print(f"  [{w.code}] {w.message}")
        raise typer.Exit(1)
    else:
        console.print("[green]Validation passed — no critical issues found.[/green]")


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


def _run_pipeline(input_xml: Path):
    from .parser.saxml_reader import parse_savexml
    from .normalize.normalize import normalize
    from .normalize.references import resolve_references
    from .analyze.backlinks import generate_backlinks
    from .analyze.warnings import generate_warnings
    from .model.validation import validate_model

    console.print(f"[dim]Parsing {input_xml}...[/dim]")
    raw = parse_savexml(input_xml)

    console.print("[dim]Normalizing...[/dim]")
    model = normalize(raw, source_file=str(input_xml), source_path=input_xml)

    console.print("[dim]Resolving references...[/dim]")
    model = resolve_references(model)

    console.print("[dim]Generating backlinks...[/dim]")
    model = generate_backlinks(model)

    console.print("[dim]Generating warnings...[/dim]")
    model = generate_warnings(model)

    console.print("[dim]Validating model...[/dim]")
    model = validate_model(model)

    return model


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
    console.print(f"[dim]References: {len(model.references)} total, {unresolved} unresolved[/dim]")
    console.print(f"[dim]Warnings: {len(model.warnings)}[/dim]")

    if verbose and model.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        from collections import Counter
        by_code = Counter(w.code for w in model.warnings)
        for code, count in by_code.most_common():
            console.print(f"  {code}: {count}")
