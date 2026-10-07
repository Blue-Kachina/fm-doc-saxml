# fm-saxml-converter

Generate structured, navigable documentation from FileMaker Pro **Save a Copy as XML** exports.

`fm-saxml-converter` turns a FileMaker `SaveAsXML` file into a normalized JSON model of the solution and a folder of cross-linked Markdown pages — one file per table, field, layout, layout object, script, relationship, custom function, and value list. The JSON model is the canonical output; Markdown is the first of several planned renderers (HTML/Vue, search index, AI corpus, diff reports).

The CLI is exposed as `fm-saxml`.

## Why this exists

A FileMaker `SaveAsXML` export contains everything about a solution, but the raw XML is not readable, not navigable, and not stable across FileMaker versions. This project produces a documentation layer that is:

- **Human-readable** — Markdown pages with consistent headings, summary tables, and per-entity backlinks.
- **AI-readable** — predictable structure, machine-parseable front matter, and JSON sidecars for indexing.
- **Linkable** — every reference between entities (script step → field, layout → table occurrence, calculation → custom function) becomes a first-class record with a stable `docId`.
- **Renderer-agnostic** — extraction is separated from presentation, so the same model can drive Markdown, a Vue site, a search index, or a diff report.

## Pipeline

```text
FileMaker SaveAsXML.xml
        ↓
   XML Parser / Extractors
        ↓
   Normalized JSON model
        ↓
   Reference + backlink analysis
        ↓
   Renderers (Markdown today; HTML/JSON/diff later)
```

## Project status

Early development. The full design is captured in [`fm-saxml-converter-plan.md`](./fm-saxml-converter-plan.md). The MVP targets:

1. Parse base tables, fields, scripts, and script steps.
2. Build a normalized JSON model with stable `docId` values.
3. Render Markdown pages for tables, fields, layouts, layout objects, and scripts with table↔field links.
4. Emit `summary.md`, `warnings.md`, and `unresolved-references.md` reports.

Reference-graph analysis (layouts, table occurrences, relationships, backlinks) is in place, along with a dead-code check (`UNUSED_FIELD_CANDIDATE`: fields with no *usage* references — a field's structural link to its own table doesn't count) and a `diff` command for comparing two exports. HTML/Vue rendering has not been started; `src/fm_saxml/render/html/` does not exist yet.

## Requirements

- Python 3.11+
- A FileMaker Pro `Save a Copy as XML` export (UTF-16 LE encoded)

## Quick start

1. In FileMaker Pro: **Tools → Save a Copy as XML…**
2. Run the converter on that file:

   ```bash
   fm-saxml MySolution.xml
   ```

   (On Windows you can also drag the XML file onto `fm-saxml.exe`.)
3. Open the new `MySolution_docs` folder that appears next to your XML file.

Add `--open` to have the folder opened for you. Run `fm-saxml doctor` if something doesn't work and include its output in any bug report.

## Installation

**Easiest — no Python needed:** download the `fm-saxml` executable for Windows, macOS or Linux from the project's Releases page.

**With Python 3.11+:**

```bash
pipx install fm-saxml-converter      # or: uvx fm-saxml-converter MySolution.xml
```

*(Requires the package to be published to PyPI; until then, use one of the source installs below.)*

### From source

The project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management.

```bash
git clone <repo-url> fm-saxml-converter
cd fm-saxml-converter
uv sync
```

Or with plain `pip`:

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # macOS/Linux
pip install -e ".[dev]"
```

## Usage

The CLI is exposed as `fm-saxml`. `fm-saxml file.xml` is shorthand for `fm-saxml build file.xml`. The `--out` option is **optional** — for `build`, output defaults to `<input name>_docs` next to the input file; for `render` (which starts from a `model.json`), it defaults to `./saxml2doc`.

If the output directory already exists and is non-empty, you'll be prompted to overwrite or cancel (with an extra warning if the folder wasn't created by `fm-saxml`); pass `--force` (or `-f`) to skip the prompt in non-interactive contexts.

Errors are shown as a single readable line. Set `FM_SAXML_DEBUG=1` to get the full traceback.

Paths are platform-flexible — Windows drive letters and UNC paths, macOS, and Linux paths all work. `~` and environment variables (`$HOME`, `%USERPROFILE%`) are expanded automatically.

```bash
# One-shot: parse and render. Output goes to ./saxml2doc by default.
fm-saxml build ./MySolution.xml

# Just parse XML into the normalized JSON model.
fm-saxml parse ./MySolution.xml

# Render Markdown from a previously parsed model.
fm-saxml render markdown --model ./build/model.json

# Print entity counts and warnings without writing any files.
fm-saxml inspect ./MySolution.xml

# Validate the model and exit non-zero if there are critical issues
# (UNUSED_FIELD_CANDIDATE warnings don't count as critical).
fm-saxml validate ./MySolution.xml
```

### Custom output location

Use `--out` (or `-o`) to write somewhere other than `<input name>_docs`:

```bash
fm-saxml build ./MySolution.xml --out ./docs/MySolution
```

### Other `build` / `render` options

| Flag | Command | Purpose |
|---|---|---|
| `--model-out <path>` | `build` | Also write the intermediate `model.json` alongside the Markdown output |
| `--include-json` / `--no-include-json` | `build` | Write `entities.json`/`references.json` into the output dir (default: on) |
| `--strict` | `build` | Exit non-zero if any reference is left `unresolved` after resolution |
| `--yes` / `-y` | `build`, `render` | Same as `--force`/`-f` — skip the overwrite-confirmation prompt |
| `--open` | `build` | Open the output folder when finished |

### Comparing two exports (`diff`)

```bash
# Compare two SaveAsXML exports (or model.json files — either input can be either format)
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml

# Write a Markdown diff report
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml --out ./diff-report.md

# Exit non-zero if anything differs (useful in CI to catch unreviewed schema drift)
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml --strict
```

`diff` compares every entity type (tables, fields, layouts, scripts, relationships, etc.) by its stable `docId`, which is derived from names rather than FileMaker's internal numeric/UUID identifiers — so the same field is recognized as "the same" across two independent exports as long as it wasn't renamed. It reports:

- **Added** / **Removed** entities per type.
- **Changed** entities — any scalar field that differs (old → new value, truncated for long text), and any list-of-references field whose *membership* changed (shown as a `+N/-M` delta, not just a raw count, so a same-size swap doesn't look unchanged).
- **Script step changes**, separately — script step `docId`s are position-based (`script + index`), so a raw added/removed diff on them would show a wall of unrelated churn whenever a single step is inserted or removed mid-script. Instead, each script's step list is compared by content (name + enabled + raw text) using a sequence alignment, and reported as a single `+added/-removed` count per script.

`--strict` exits with status 1 if the diff found any difference at all (added, removed, changed, or script step changes).

## Output layout

```text
saxml2doc/
├─ index.md
├─ entities.json
├─ references.json
├─ Tables/
├─ Fields/
│  └─ <TableName>/
├─ TableOccurrences/
├─ Relationships/
├─ Layouts/
├─ LayoutObjects/
│  └─ <LayoutName>/
├─ Scripts/
├─ CustomFunctions/
├─ ValueLists/
└─ Reports/
   ├─ summary.md
   ├─ warnings.md
   └─ unresolved-references.md
```

File names are safe on Windows, macOS and Linux: invalid characters and Windows reserved names (`CON`, `NUL`, …) are replaced, long names are truncated with a short hash, and names that would collide on a case-insensitive file system (`Invoices` vs `invoices`, or an entity named `index`) get a `-2`, `-3`… suffix. Links always point at the final file names.

Every Markdown page carries YAML front matter with `docId`, `entityType`, and source metadata so the output is friendly to static site generators and AI indexers. The top-level `index.md` records two timestamps for clarity: **XML Created At** (mtime of the source export) and **Support Documentation Created At** (when the docs were generated).

### Provenance / self-versioning

Every generated `index.md` and `Reports/summary.md` also records **which build of `fm-saxml` produced it** (see `src/fm_saxml/version.py`). When running from a git checkout, this is the current commit hash and commit timestamp (e.g. `2026-05-04 20:01 UTC (commit b114c6a)`); when running from an installed package with no reachable `.git`, it falls back to the `__version__` string (e.g. `v0.1.0`). This is best-effort and never fails the build.

## Repository structure

```text
src/fm_saxml/
├─ cli.py               # Typer CLI entry point (fm-saxml)
├─ version.py           # Self-version detection (git commit or package version) for doc provenance
├─ parser/              # XML parsing and per-entity extractors
│  ├─ saxml_reader.py
│  ├─ version_detector.py   # Detects the *FileMaker* export version (v1/v2), unrelated to version.py above
│  └─ extractors/
├─ model/               # Pydantic models, references, validation
├─ normalize/           # Naming, docId assignment, path generation
├─ analyze/             # Calculation parsing, backlinks, warnings (incl. UNUSED_FIELD_CANDIDATE), diff.py
├─ render/
│  ├─ markdown/         # Jinja2 templates and renderer (incl. diff_renderer.py)
│  └─ json/             # JSON sidecar writer
└─ utils/

tests/
├─ fixtures/
└─ test_*.py
```

## Development

Run tests with pytest:

```bash
uv run pytest
# or
pytest
```

Fixture-based and snapshot tests live under `tests/`. New extractors should ship with a small XML fixture and an expected-model snapshot.

## Design principles

The full rationale lives in the plan, but the headline rules are:

- **Separate extraction from presentation.** Don't generate Markdown directly from XML — go through the JSON model.
- **Treat FileMaker XML as an input format, not a source of truth.** The internal model should outlive any FileMaker version change.
- **Link aggressively.** Every reference between entities becomes a first-class record with a `confidence` rating (`exact`, `parsed`, `inferred`, `unresolved`).
- **Optimize for both humans and AI agents.** Use predictable headings, machine-readable front matter, and chunkable per-entity files.

## FileMaker XML notes

A few quirks worth knowing about:

- `SaveAsXML` files are encoded as **UTF-16 LE**. Always open in binary mode and let `lxml` read the encoding declaration.
- In FileMaker 22+, embedded layout images are duplicated inside every `<LayoutObject>` (rather than shared via `<LibraryCatalog>`), which can dramatically inflate file size. The layout extractor skips `<StreamList>` image data by default.
- Layout objects in modern (v2) `SaveAsXML` files appear as `<LayoutObject>` inside `<Part><ObjectList>`. Older v1 exports use `<Object type="FieldObj">`. Both are parsed.
- Relationship names, script folder paths, and script step display labels are **derived during normalization**, not read directly from the XML.

## Known limitations

- **`UNUSED_FIELD_CANDIDATE` only sees references this tool already extracts** — relationships, layouts, layout objects, script steps, and custom-function calculations. It does **not** yet parse the calculation text of a field's own `Calculation` (e.g. a `FullName` calc field referencing `FirstName`/`LastName`) — fields referenced only from inside another field's formula will currently show up as false-positive unused candidates. Treat it as a lead to investigate, not a guarantee.
- **`diff`'s script-step comparison is content-based, not line-by-line.** It tells you how many steps were added/removed per script, not exactly which ones or where — open the two `Scripts/<name>.md` pages side by side for that level of detail.

## Roadmap

Major milestones from the plan:

1. **Phase 1** — POC: tables, fields, scripts, basic Markdown output.
2. **Phase 2** — Reference graph: layouts, layout objects, table occurrences, relationships, backlinks.
3. **Phase 3** — Markdown polish: Jinja templates, front matter, indexes, reports.
4. **Phase 4** — Analysis: dependency graph, dead-code detection, server-compatibility checks.
5. **Phase 5** — HTML/Vue interactive renderer over the same JSON model. *(not started)*
6. **Phase 6** — `fm-saxml diff` for version comparison between two exports. *(done)*

## License

[MIT](./LICENSE)
