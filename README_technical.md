# fm-saxml-converter — technical README

Details for developers, CI setups and anyone who wants to know how the converter works. For everyday use, start with the [README](./README.md).

## Pipeline

```text
FileMaker SaveAsXML.xml
        ↓
   XML Parser / Extractors
        ↓
   Secret / PII scrubbing
        ↓
   Normalized JSON model
        ↓
   Reference + backlink analysis
        ↓
   Renderers (Markdown, HTML viewer, JSON sidecars, diff reports)
```

The JSON model is the canonical output. Every renderer works from it, never from the XML directly.

## Design principles

The full rationale lives in [`fm-saxml-converter-plan.md`](./fm-saxml-converter-plan.md), but the headline rules are:

- **Separate extraction from presentation.** Don't generate Markdown directly from XML — go through the JSON model.
- **Treat FileMaker XML as an input format, not a source of truth.** The internal model should outlive any FileMaker version change.
- **Link aggressively.** Every reference between entities becomes a first-class record with a stable `docId` and a `confidence` rating (`exact`, `parsed`, `inferred`, `unresolved`).
- **Optimize for both humans and AI agents.** Use predictable headings, machine-readable front matter, and chunkable per-entity files.

## Installing from source

The project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management.

```bash
git clone https://github.com/Blue-Kachina/fm-doc-saxml.git fm-saxml-converter
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

## CLI behaviour

- `fm-saxml file.xml` is shorthand for `fm-saxml build file.xml`.
- `--out` is optional. For `build`, output defaults to `<input name>_docs` next to the input file; for `render` (which starts from a `model.json`), it defaults to `./saxml2doc`.
- If the output directory already exists and is non-empty, you'll be prompted to overwrite or cancel (with an extra warning if the folder wasn't created by `fm-saxml`). Pass `--force`/`-f` or `--yes`/`-y` to skip the prompt in non-interactive contexts.
- Errors are shown as a single readable line. Set `FM_SAXML_DEBUG=1` to get the full traceback.
- Paths are platform-flexible — Windows drive letters and UNC paths, macOS, and Linux paths all work. `~` and environment variables (`$HOME`, `%USERPROFILE%`) are expanded automatically.
- `validate` exits non-zero if there are critical issues. `UNUSED_FIELD_CANDIDATE` warnings don't count as critical.

### All `build` / `render` options

| Flag | Command | Purpose |
|---|---|---|
| `--out <path>` / `-o` | `build`, `render` | Output folder (see defaults above) |
| `--model-out <path>` | `build` | Also write the intermediate `model.json` alongside the Markdown output |
| `--include-json` / `--no-include-json` | `build` | Write `entities.json`/`references.json` into the output dir (default: on) |
| `--strict` | `build` | Exit non-zero if any reference is left `unresolved` after resolution |
| `--force` / `-f`, `--yes` / `-y` | `build`, `render` | Skip the overwrite-confirmation prompt |
| `--open` | `build` | Open the output folder when finished |
| `--html` | `build`, `render` | Also write an `index.html` for browsing the docs in a web browser (see [HTML viewer](./docs/html-viewer.md)) |
| `--webmcp` | `build`, `render` | Make the HTML viewer agent-ready (see [HTML viewer](./docs/html-viewer.md#agent-ready-html---webmcp)). Turns on `--html` |
| `--serve` / `--port <n>` | `build`, `render` | With `--webmcp`: serve the docs at `http://127.0.0.1:<port>` when done (default 8765). Same as the `serve` command |
| `--coverage` | `build`, `parse`, `render` | Also check that everything in the export reached the docs, and write `Reports/coverage.md` (see [Coverage report](#coverage-report)) |
| `--fail-on-coverage-gap` | `build` | Exit with status 1 if anything in the export didn't reach the docs, or the export has XML the converter doesn't recognise. Turns on `--coverage`. For CI. |
| `--fail-on-secrets` | `build`, `parse`, `render` | Exit with status 1 (after writing everything) if the export contains hardcoded credentials. For CI. |

The scrubbing flags (`--scrub-level`, `--scrub-keyword`, `--scrub-allow`, `--disable-scrubbing`) are described in [Scrubbing](./docs/scrubbing.md).

### Environment variables

| Variable | Purpose |
|---|---|
| `FM_SAXML_DEBUG=1` | Show full tracebacks instead of one-line errors |
| `FM_SAXML_NO_UPDATE_CHECK=1` | Turn off the once-a-day "newer version available" notice |
| `FM_SAXML_SCRUB_SALT` | Keyed, run-stable scrubbing placeholders (see [Scrubbing](./docs/scrubbing.md#stable-placeholders-across-runs)) |

## Coverage report

```bash
fm-saxml build ./MySolution.xml --coverage
```

With `--coverage` (or `--fail-on-coverage-gap`), the build writes `Reports/coverage.md`. It's off by default because it reads the whole export a second time. `parse --coverage` keeps the counts in `model.json`, and `render --coverage` turns them into the report.

The report counts about 70 things straight from the export's XML (scripts, step comments, Set Variable names, button actions, relationship options, value list sources, privilege rows, validation rules, and so on), independently of the converter, and sets each against the same thing in the finished docs. Some checks look at the rendered text: a Set Variable name only counts if it appears in the step.

The report also lists any element or attribute the converter has no rule for ("Unrecognised XML"), so a FileMaker option this version doesn't document can't disappear silently, and what it leaves out on purpose (images, styling, layout geometry). The home page shows a one-line result, and a multi-file build's `Reports/batch-summary.md` has a Coverage column.

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
├─ Layouts/            (parts, objects with their value lists and button actions)
├─ LayoutObjects/
│  └─ <LayoutName>/
├─ Scripts/
├─ Variables/          ($$globals; each script's $locals are on its page)
├─ CustomFunctions/
├─ ValueLists/
├─ Reports/
│  ├─ summary.md
│  ├─ coverage.md     (--coverage only)
│  ├─ redactions.md
│  ├─ warnings.md
│  └─ unresolved-references.md
├─ index.html          (--html only)
└─ _viewer/            (--html only)
   ├─ manifest.js
   ├─ pages/
   ├─ webmcp.js        (--webmcp only; llms.txt at the top level too)
   └─ data/<file>/     (--webmcp only: catalog, one script per entity type, refs, access)
```

**Script pages** list every step as FileMaker's Script Workspace shows it: comments, `Set Variable [ $name ; Value: … ]`, `Set Field [ Table::field ; … ]`, Perform Script parameters and step options, with nothing truncated. If/Loop blocks are indented and disabled steps are prefixed with `//`. Step numbers match FileMaker's. A **Variables** table on each script page shows where each variable is set and read. `Variables/index.md` lists every `$$global` (with a page showing where it is set and read across scripts, fields, layouts and custom functions) and each script's `$locals`. Locals that are read but never set are flagged: they are always empty, which usually means a typo.

File names are safe on Windows, macOS and Linux: invalid characters and Windows reserved names (`CON`, `NUL`, …) are replaced, long names are truncated with a short hash, and names that would collide on a case-insensitive file system (`Invoices` vs `invoices`, or an entity named `index`) get a `-2`, `-3`… suffix. Links always point at the final file names.

Every Markdown page carries YAML front matter with `docId`, `entityType`, and source metadata so the output is friendly to static site generators and AI indexers. The top-level `index.md` records two timestamps for clarity: **XML Created At** (mtime of the source export) and **Support Documentation Created At** (when the docs were generated).

A multi-file build has one of these folders per FileMaker file, plus a combined `index.md` and `Reports/` — see [Multi-file solutions](./docs/multi-file.md).

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
├─ analyze/             # Calculation parsing, backlinks, warnings (incl. UNUSED_FIELD_CANDIDATE), diff.py, coverage.py, access.py (effective privileges)
├─ render/
│  ├─ markdown/         # Jinja2 templates and renderer (incl. diff_renderer.py)
│  ├─ html/             # --html viewer: index.html template + per-page scripts; --webmcp tools and data
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

## FileMaker XML notes

A few quirks worth knowing about:

- `SaveAsXML` files are encoded as **UTF-16 LE**. Always open in binary mode and let `lxml` read the encoding declaration.
- In FileMaker 22+, embedded layout images are duplicated inside every `<LayoutObject>` (rather than shared via `<LibraryCatalog>`), which can dramatically inflate file size. The layout extractor skips `<StreamList>` image data by default.
- Layout objects in modern (v2) `SaveAsXML` files appear as `<LayoutObject>` inside `<Part><ObjectList>`. Older v1 exports use `<Object type="FieldObj">`. Both are parsed.
- Relationship names and script folder paths are **derived during normalization**, not read directly from the XML.
- Script steps are shown as **FileMaker prints them** in the Script Workspace, taken from the `StepText` entries in the export's `DDR_INFO` section (scrubbed like any calculation). Steps without one (older exports, older `model.json` files) are rebuilt from their parameters instead.

## Known limitations

- **A missing "Called By" is not proof that a script is unused.** Buttons, button groups, layout and object triggers, File Options triggers and Perform Script steps are all traced, but a script can also be run from a custom menu item in another file, by name from a calculation (`Perform Script by name`), or by FileMaker Server schedules, none of which the export links to a script page.
- **Custom privilege lists for layouts, value lists and scripts** are read generically (each row's object and its access columns), because the sample exports used for testing only have custom *record* privileges. Unusual shapes still come through, but their column names are FileMaker's raw element names.
- **`UNUSED_FIELD_CANDIDATE` only sees references this tool already extracts** — relationships, layouts, layout objects, script steps, and custom-function calculations. It does **not** yet parse the calculation text of a field's own `Calculation` (e.g. a `FullName` calc field referencing `FirstName`/`LastName`) — fields referenced only from inside another field's formula will currently show up as false-positive unused candidates. Treat it as a lead to investigate, not a guarantee.
- **`diff`'s script-step comparison is content-based, not line-by-line.** It tells you how many steps were added/removed per script, not exactly which ones or where — open the two `Scripts/<name>.md` pages side by side for that level of detail.
