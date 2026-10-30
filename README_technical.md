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
- `build` writes into `<out>.tmp-<pid>` and swaps it in when done, so a failed build keeps the old docs and readers never see a half-written folder. On Windows a file held open inside the old folder blocks the swap: the build stops with an error and leaves the new docs in `<out>.tmp-<pid>`. See [Rebuilding while readers are open](docs/contract.md#rebuilding-while-readers-are-open).
- Errors are shown as a single readable line. Set `FM_SAXML_DEBUG=1` to get the full traceback.
- Paths are platform-flexible — Windows drive letters and UNC paths, macOS, and Linux paths all work. `~` and environment variables (`$HOME`, `%USERPROFILE%`) are expanded automatically.
- `validate` exits non-zero if there are critical issues. `UNUSED_FIELD_CANDIDATE` warnings don't count as critical.

### Commands

| Command | What it does |
|---|---|
| `build <file or folder>` | Parse the export and write the documentation (the default) |
| `parse <file>` | Parse the export into the normalized `model.json` only |
| `render markdown --model <model.json>` | Write documentation from a `model.json` made earlier |
| `inspect <file or folder>` | Print entity counts and warnings without writing anything |
| `validate <file or folder>` | Exit non-zero if the model has critical issues |
| `diff <old> <new>` | Compare two exports and report what changed — see [Comparing exports](./docs/diff.md) |
| `rename-check <file or docs folder> <name>...` | What would break if you renamed a field, script, layout, object ...: every place that names it in text — see [Names written in text](./docs/indirection.md#rename-check) |
| `scrub <file>` | Write a copy of the XML with secrets redacted — see [Scrubbing](./docs/scrubbing.md#scrubbing-the-xml-itself-scrub) |
| `serve <docs folder>` | Serve a `--webmcp` build at `http://127.0.0.1:8766` so browser agents get its tools |
| `doctor` | Print environment details for bug reports |

Run `fm-saxml <command> --help` for every option.

### All `build` / `render` options

| Flag | Command | Purpose |
|---|---|---|
| `--out <path>` / `-o` | `build`, `render` | Output folder (see defaults above) |
| `--docs-root <folder>` | `build` | Without `--out`: write to `<folder>/<solution>`. Also read from `FM_SAXML_DOCS_ROOT`. See [Where docs live](docs/contract.md#where-docs-live) |
| `--solution <name>` | `build` | The solution's name in the docs root and `docs.json` (default: the FileMaker file name, or the folder name for a multi-file export) |
| `--model-out <path>` | `build` | Also write the intermediate `model.json` alongside the Markdown output |
| `--include-json` / `--no-include-json` | `build`, `render` | Write the JSON contract files (`docs.json`, `entities.json`, `references.json`, `backlinks.json`, `external-references.json`; see [docs/contract.md](docs/contract.md)) into the output dir (default: on) |
| `--raw-xml` / `--no-raw-xml` | `build` | Write `raw/*.json`: the scrubbed XML of every script, layout, theme and custom menu, for tools that paste back into FileMaker (see [docs/contract.md](docs/contract.md)). Adds about two-thirds of the export's size (default: on) |
| `--strict` | `build` | Exit non-zero if any reference is left `unresolved` after resolution |
| `--force` / `-f`, `--yes` / `-y` | `build`, `render` | Skip the overwrite-confirmation prompt |
| `--open` | `build` | Open the output folder when finished |
| `--html` | `build`, `render` | Also write an `index.html` for browsing the docs in a web browser (see [HTML viewer](./docs/html-viewer.md)) |
| `--webmcp` | `build`, `render` | Make the HTML viewer agent-ready (see [HTML viewer](./docs/html-viewer.md#agent-ready-html---webmcp)). Turns on `--html` |
| `--serve` / `--port <n>` | `build`, `render` | With `--webmcp`: serve the docs at `http://127.0.0.1:<port>` when done (default 8766). Same as the `serve` command |
| `--coverage` | `build`, `parse`, `render` | Also check that everything in the export reached the docs, and write `Reports/coverage.md` (see [Coverage report](#coverage-report)) |
| `--fail-on-coverage-gap` | `build` | Exit with status 1 if anything in the export didn't reach the docs, or the export has XML the converter doesn't recognise. Turns on `--coverage`. For CI. |
| `--fail-on-secrets` | `build`, `parse`, `render` | Exit with status 1 (after writing everything) if the export contains hardcoded credentials. For CI. |
| `--progress rich\|plain\|json` | `build` | Live bars, one line per stage and file, or one JSON object per line (see [Progress in scripts and pipes](#progress-in-scripts-and-pipes)). Default: `rich` when stdout is a terminal, else `plain` |
| `--scrub-level secrets\|standard\|strict` | `build`, `parse`, `render`, `diff`, `rename-check`, `scrub` | How much to redact (default `secrets`) — see [Scrubbing](./docs/scrubbing.md) |
| `--disable-scrubbing` | `build`, `parse`, `render`, `diff`, `rename-check` | Turn secret scrubbing off |

The other scrubbing flags (`--scrub-keyword`, `--scrub-allow`) are described in [Scrubbing](./docs/scrubbing.md).

### Environment variables

| Variable | Purpose |
|---|---|
| `FM_SAXML_DEBUG=1` | Show full tracebacks instead of one-line errors |
| `FM_SAXML_NO_UPDATE_CHECK=1` | Turn off the once-a-day "newer version available" notice |
| `FM_SAXML_SCRUB_SALT` | Keyed, run-stable scrubbing placeholders (see [Scrubbing](./docs/scrubbing.md#stable-placeholders-across-runs)) |

### Progress in scripts and pipes

In a terminal, `build` draws live progress bars. When its output goes to a pipe or a file, the bars can't redraw, so by default it prints one line per stage and per file instead (`--progress plain`):

```text
Analyzing: 12 file(s)
[3/12] Analyzing Invoices...
[3/12] Analyzing Invoices (4.2s)
Analyzing done (37.5s)
Writing HTML viewer: 5300/21193 pages (40.1s)
Done (52.1s)
```

A stage that counts pages or files prints how far it got at most every 5 seconds, as in the `Writing HTML viewer` line.

`--progress json` prints the same events as one JSON object per line on stdout, for a program that wants to show the progress (the agentic-fm companion does). The build's other output (summaries, warnings) is still printed around them, so skip any line that isn't a JSON object with an `event` key.

```json
{"event": "file_done", "stage": "analyze", "file": "Invoices", "index": 3, "total": 12, "elapsed": 41.7, "seconds": 4.2}
{"event": "stage_progress", "stage": "write_viewer", "file": "Accounting", "index": 1, "total": 1, "elapsed": 61.3, "done": 5300, "units": 21193, "unit": "pages"}
```

| Field | Meaning |
|---|---|
| `event` | `stage_start`, `file_start`, `stage_progress`, `file_done`, `stage_done`, or `done` (once, at the end of a successful build) |
| `stage` | `read`, `scrub`, `analyze`, `write_raw`, `write_pages`, `write_viewer` or `check`, in that order (no `write_raw` with `--no-raw-xml` or `--no-include-json`, `write_viewer` only with `--html` or `--webmcp`, `check` only when scrubbing is on); `null` for `done` |
| `file` | The export's name (its FileMaker file name) for `file_start`, `stage_progress` and `file_done`; otherwise `null`. `write_viewer` and `check` run once over the whole output, so their one file is the solution (the `--solution` name, or the file's name for a single file) |
| `index` | This file's number in the stage, from 1; `0` for `stage_start` and `done`; `total` for `stage_done` |
| `total` | Files in the stage (`1` for a single-file build); `0` for `done` |
| `elapsed` | Seconds since the build started, to 0.1 |
| `seconds` | `file_done` and `stage_done` only: how long that file or stage took |
| `done` | `stage_progress`, and `stage_done` of `write_pages`, `write_viewer` and `check`: pages or files finished so far in the stage (the final count in `stage_done`) |
| `units` | `stage_progress` only: how many the stage expects. `write_pages`'s is an estimate, so it may end a little above or below |
| `unit` | With `done`: `pages` (`write_pages`, `write_viewer`: the viewer's pages are the Markdown pages) or `files` (`check`: the text files the scrubbing guard scans, none when nothing was redacted) |

`stage_progress` comes at most once a second, and only when `done` has changed. `write_viewer` and `check` can take minutes on a large solution (tens of thousands of pages).

A file that can't be read in a multi-file build still gets its `file_done` in `read`, and is left out of the later stages (their `total` is lower).

## Coverage report

```bash
fm-saxml build ./MySolution.xml --coverage
```

With `--coverage` (or `--fail-on-coverage-gap`), the build writes `Reports/coverage.md`. It's off by default because it reads the whole export a second time. `parse --coverage` keeps the counts in `model.json`, and `render --coverage` turns them into the report.

The report counts about 70 things straight from the export's XML (scripts, step comments, Set Variable names, button actions, relationship options, value list sources, privilege rows, validation rules, and so on), independently of the converter, and sets each against the same thing in the finished docs. Some checks look at the rendered text: a Set Variable name only counts if it appears in the step.

The report also lists any element or attribute the converter has no rule for ("Unrecognised XML"), so a FileMaker option this version doesn't document can't disappear silently, and what it leaves out on purpose (images, styling, layout geometry). The home page shows a one-line result, and a multi-file build's `Reports/batch-summary.md` has a Coverage column.

## Solution profile

Every build writes `Reports/profile.md`, a first look at one file's structure:

- **Data model:** fields per table by data type and field type; relationship join operators, multi-predicate joins, self-joins, and "create" / "delete related records" counted per side (a parent-child cascade is usually on the right); the relationship graph's degrees, hub TOs (5+ relationships), TOs and tables in no relationship.
- **Scripts:** steps per script and the largest, folders, Perform Script links within the file, and entry points: scripts no script performs that a button, trigger, custom menu or another file runs.
- **Layouts:** layouts per base TO and folder, portals and their TOs, layouts nothing navigates to (Go to Layout, New Window, the default layout).
- **Value lists** by type, and **integrations:** enabled steps that reach outside the file (Insert from URL, Send Mail, Execute SQL, Perform Script on Server, Import/Export ...), with their scripts.
- **Unused candidates** for fields, scripts, layouts, value lists and custom functions: no use in the backlinks other than structure, the same rule as the `UNUSED_FIELD_CANDIDATE` warning. Uses from other files of a multi-file build count; calls by calculated name, server schedules and `fmp://` URLs don't, so they're candidates only.

Every number comes from the model; nothing is guessed from object names.

## Output layout

```text
saxml2doc/
├─ index.md
├─ docs.json           (JSON contract: docs/contract.md)
├─ entities.json
├─ references.json
├─ backlinks.json
├─ external-references.json
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
│  ├─ indirection.md  (names written in text: see docs/indirection.md)
│  ├─ warnings.md
│  ├─ unresolved-references.md
│  └─ profile.md      (data model, scripts, layouts, integrations, unused candidates)
├─ index.html          (--html only)
└─ _viewer/            (--html only)
   ├─ manifest.js
   ├─ pages/
   ├─ webmcp.js        (--webmcp only; llms.txt at the top level too)
   └─ data/<file>/     (--webmcp only: catalog, one script per entity type, refs, access, indirectionSite)
```

**Script pages** list every step as FileMaker's Script Workspace shows it: comments, `Set Variable [ $name ; Value: … ]`, `Set Field [ Table::field ; … ]`, Perform Script parameters and step options, with nothing truncated. If/Loop blocks are indented and disabled steps are prefixed with `//`. Step numbers match FileMaker's. A **Variables** table on each script page shows where each variable is set and read. `Variables/index.md` lists every `$$global` (with a page showing where it is set and read across scripts, fields, layouts and custom functions) and each script's `$locals`. Locals that are read but never set are flagged: they are always empty, which usually means a typo.

File names are safe on Windows, macOS and Linux: invalid characters and Windows reserved names (`CON`, `NUL`, …) are replaced, long names are truncated with a short hash, and names that would collide on a case-insensitive file system (`Invoices` vs `invoices`, or an entity named `index`) get a `-2`, `-3`… suffix. Links always point at the final file names.

Every Markdown page carries YAML front matter with `docId`, `entityType`, and source metadata so the output is friendly to static site generators and AI indexers. The top-level `index.md` records two timestamps for clarity: **XML Created At** (mtime of the source export) and **Support Documentation Created At** (when the docs were generated).

A multi-file build has one of these folders per FileMaker file, plus a combined `index.md` and `Reports/` — see [Multi-file solutions](./docs/multi-file.md).

### Provenance / self-versioning

Every generated `index.md` and `Reports/summary.md` also records **which build of `fm-saxml` produced it** (see `src/fm_saxml/version.py`). When running from a git checkout, this is the current commit hash and commit timestamp (e.g. `2026-05-04 20:01 UTC (commit b114c6a)`); when running from an installed package with no reachable `.git`, it falls back to the `__version__` string (e.g. `v0.1.0`). This is best-effort and never fails the build.

## Reading the docs from Python

```python
import fm_saxml

docs = fm_saxml.load("Invoices_docs")
docs.find("script", "post invoice")
docs.refs_to("field:Invoices::Total")
```

See [JSON contract](./docs/contract.md#reading-from-python) for the rest.

## Repository structure

```text
src/fm_saxml/
├─ cli.py               # Typer CLI entry point (fm-saxml)
├─ progress.py          # build --progress: Rich bars, plain lines or JSON lines behind one reporter
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

- **A missing "Called By" is not proof that a script is unused.** Buttons, button groups, layout and object triggers, File Options triggers and Perform Script steps are all traced, and so are names written in text that can be resolved (`Perform Script [ By name ]`, see [Names written in text](./docs/indirection.md)). A script can still be run from a custom menu item in another file, by a name that comes from data, or by FileMaker Server schedules, none of which the export links to a script page.
- **Custom privilege lists for layouts, value lists and scripts** are read generically (each row's object and its access columns), because the sample exports used for testing only have custom *record* privileges. Unusual shapes still come through, but their column names are FileMaker's raw element names.
- **`UNUSED_FIELD_CANDIDATE` only sees references this tool already extracts** — relationships, layouts, layout objects, script steps, and custom-function calculations. It does **not** yet parse the calculation text of a field's own `Calculation` (e.g. a `FullName` calc field referencing `FirstName`/`LastName`) — fields referenced only from inside another field's formula will currently show up as false-positive unused candidates. Treat it as a lead to investigate, not a guarantee.
- **`diff`'s script-step comparison is content-based, not line-by-line.** It tells you how many steps were added/removed per script, not exactly which ones or where — open the two `Scripts/<name>.md` pages side by side for that level of detail.
