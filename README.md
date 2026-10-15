# fm-saxml-converter

[![PyPI version](https://img.shields.io/pypi/v/fm-saxml-converter)](https://pypi.org/project/fm-saxml-converter/)
[![Python versions](https://img.shields.io/pypi/pyversions/fm-saxml-converter)](https://pypi.org/project/fm-saxml-converter/)
[![License: MIT](https://img.shields.io/pypi/l/fm-saxml-converter)](LICENSE)
[![CI](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/ci.yml/badge.svg)](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/ci.yml)
[![Release](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/release.yml/badge.svg)](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/release.yml)

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
   Secret / PII scrubbing
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

Reference-graph analysis (layouts, table occurrences, relationships, backlinks) is in place, along with a dead-code check (`UNUSED_FIELD_CANDIDATE`: fields with no *usage* references — a field's structural link to its own table doesn't count) and a `diff` command for comparing two exports. An optional HTML viewer (`--html`) renders the Markdown in a browser, opened straight from disk.

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
pipx install fm-saxml-converter      # or run without installing: uvx --from fm-saxml-converter fm-saxml MySolution.xml
```

### Updating

Check your version with `fm-saxml --version`, then upgrade the same way you installed:

| Installed with | Update command |
|---|---|
| `pipx` | `pipx upgrade fm-saxml-converter` |
| `uv tool install` | `uv tool upgrade fm-saxml-converter` |
| `pip` | `pip install -U fm-saxml-converter` |
| `uvx` | `uvx --from fm-saxml-converter@latest fm-saxml ...` |
| Executable | Download the new file from the Releases page |

When a newer version exists, `fm-saxml` prints a one-line notice after a run (checked at most once a day, never blocks, silent in CI and when output is piped). Disable it with `FM_SAXML_NO_UPDATE_CHECK=1`.

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
# One-shot: parse and render. Output goes to ./MySolution_docs by default.
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

# Serve docs built with --webmcp at http://127.0.0.1:8765, so agents in the browser get the tools.
fm-saxml serve ./MySolution_docs
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
| `--html` | `build`, `render` | Also write an `index.html` for browsing the docs in a web browser (see below) |
| `--webmcp` | `build`, `render` | Make the HTML viewer agent-ready: WebMCP tools that query the solution, and a results view (see [below](#agent-ready-html-webmcp)). Turns on `--html` |
| `--serve` / `--port <n>` | `build`, `render` | With `--webmcp`: serve the docs at `http://127.0.0.1:<port>` when done (default 8765), where browsers give the viewer WebMCP. Same as the `serve` command |
| `--coverage` | `build`, `parse`, `render` | Also check that everything in the export reached the docs, and write `Reports/coverage.md` (see [Coverage report](#coverage-report)) |
| `--fail-on-coverage-gap` | `build` | Exit with status 1 if anything in the export didn't reach the docs, or the export has XML the converter doesn't recognise. Turns on `--coverage`. For CI. |

### Coverage report

```bash
fm-saxml build ./MySolution.xml --coverage
```

With `--coverage` (or `--fail-on-coverage-gap`), the build writes `Reports/coverage.md`. It's off by default because it reads the whole export a second time. `parse --coverage` keeps the counts in `model.json`, and `render --coverage` turns them into the report. The report counts about 70 things straight from the export's XML (scripts, step comments, Set Variable names, button actions, relationship options, value list sources, privilege rows, validation rules, and so on), independently of the converter, and sets each against the same thing in the finished docs. Some checks look at the rendered text: a Set Variable name only counts if it appears in the step. The report also lists any element or attribute the converter has no rule for ("Unrecognised XML"), so a FileMaker option this version doesn't document can't disappear silently, and what it leaves out on purpose (images, styling, layout geometry). The home page shows a one-line result, and a multi-file build's `Reports/batch-summary.md` has a Coverage column.

### Browsing the docs in a web browser (`--html`)

```bash
fm-saxml build ./MySolution.xml --html
```

`--html` adds `index.html` to the output folder. Double-click it to browse the documentation in any modern browser, with a sidebar, page filter, breadcrumbs and working links between pages. It runs straight from disk, so no web server is needed.

- Browsers don't let a page opened from disk read other files, so each Markdown page is also written as a small script under `_viewer/pages/` (one per page). That's why it's opt-in.
- The Markdown is rendered with [Milkdown Crepe](https://milkdown.dev/), loaded from a CDN (esm.sh and jsDelivr). Viewing needs internet access, at least until the browser has cached it. The `.md` files are unchanged and still work on their own.
- Calculations are written as ` ```filemaker ` code blocks, and the viewer highlights them with FileMaker calculation syntax via [fmscriptui](https://github.com/Blue-Kachina/fmscriptui). If that can't load, calculations still show, just without highlighting.
- Keep `index.html` and `_viewer/` together if you move or zip the folder.

### Agent-ready HTML (`--webmcp`)

```bash
fm-saxml build ./MySolution.xml --webmcp --serve    # build, then serve at http://127.0.0.1:8765
fm-saxml serve ./MySolution_docs                     # serve docs built earlier
```

`--webmcp` adds [WebMCP](https://github.com/webmachinelearning/webmcp) tools to the viewer. An AI agent working in the browser can then ask the solution questions that would take a person many clicks, and open the answers in the viewer. The tools work from the model behind the docs, not the rendered pages. Every entity type and attribute, the reference graph, and each privilege set's effective access are written under `_viewer/data/` and loaded as needed.

| Tool | Answers |
|---|---|
| `describe_schema` | Which entity types exist, and the fields of each that can be queried |
| `get_solution_overview`, `get_current_page`, `get_entity` | What's in the solution, what's on screen, and everything about one entity |
| `search_entities` | Find anything by name, or by comment, calculation or step text |
| `query_entities` | Filter one type by its attributes ("unstored calcs that use related fields", "layout objects with a hide condition") |
| `find_script_steps` | Steps by name, text, regex, script or folder, or by what they set ("every Set Field on `Invoices::Total`") |
| `find_references` | What uses an entity, or every field of a table, and what it uses |
| `find_unreferenced` | Dead-code candidates: scripts, layouts, value lists, custom functions or fields nothing references |
| `traverse` | References followed more than one step: everything that eventually calls a script, or the path between two table occurrences |
| `who_can_access`, `what_can_access` | Which privilege sets and accounts can run a script, open a layout, or view, edit, create or delete records, and why |
| `query` | A JSON pipeline (`from`, `where`, `join`, `joinRefs`, `joinAccess`, `select`, `groupBy`, `sort`, `limit`) for questions no other tool covers |
| `navigate_to`, `show_results` | Open a page (for a script step, its script, with the step highlighted), or show a list of entities picked by hand |

On a script, table or layout page there are also tools for that entity: `list_steps_in_this_script`, `list_fields_in_this_table` and `list_objects_on_this_layout`. The last one finds hidden objects: those with a "Hide object when" calculation, and those that only show in a tab panel, slide panel or popover.

- **Results show in the viewer.** Every query tool also opens a results view, grouped by type (steps under their script, objects under their layout, accounts under their privilege set) and by file in a multi-file build. Pass `display: false` to skip it. The view has a link that runs the query again, so it can be bookmarked or shared, and it keeps a list of recent queries. With `--webmcp`, the search box looks up every entity name in every file, grouped by type. Press Enter to also search text, and use the Advanced search form for common filters.
- **Access answers explain themselves.** Each one gives the reason: `[Full Access]`, a setting for the whole category, the object's own row in a custom list, or the "[Any new …]" row. External accounts (identity-provider groups) and disabled accounts are flagged.
- **Open it from localhost, not from disk.** Browsers only give WebMCP to pages served from a web address. A page opened by double-clicking `index.html` (`file://`) doesn't get it, so agents in the browser can't see the tools. `fm-saxml serve <docs folder>` (or `--serve` on `build`/`render`) serves the folder at `http://127.0.0.1:8765` and opens it there. Localhost counts as a secure origin, so WebMCP works.
  - The server listens on 127.0.0.1 only.
  - It serves nothing outside the folder.
  - It refuses requests addressed to any other host name.
  - `--port` picks the port (a free one is used if it's taken), `--no-open` skips opening the browser, and Ctrl+C stops it.
  - Both work only on a `--webmcp` build.
- **Agents without WebMCP.** Some browser agents have no WebMCP. Claude in Chrome is one: it never gets `document.modelContext`. They can reach the same tools in two other ways:
  - **By URL.** `index.html#/results?q=<URL-encoded {"tool": "<name>", "args": {...}}>&format=json` runs a tool and shows the result as JSON text (`<pre id="fm-result-json">`). Without `&format=json`, the same link shows the grouped results view.
  - **In JavaScript in the page.** Call `FMDocs.tools.<name>.execute(...)`.

  The **For AI agents** link in the header (`#/agents`) lists every tool with its argument schema and example links that run against this solution. `--webmcp` also writes an `llms.txt` at the top of the docs folder that points agents there. Both work on a page opened from disk too.
- **Status badge.** With `--webmcp`, the viewer's header shows whether the tools reached the browser: "WebMCP · 15 tools", "WebMCP off: opened from disk", or "WebMCP not in this browser". Click it for the reason and what to do. On a page opened from disk, clicking copies the `fm-saxml serve` command for that folder.
- **Browser support.** WebMCP is still a draft. It's in Chrome from version 149 as an origin trial (or turned on under `chrome://flags`) and in Edge 147 behind a flag. ChatGPT's desktop browser calls it "site tools": it's on in Settings > Browser > Permissions, for models that support it. The viewer registers its tools through `document.modelContext` (or the older `navigator.modelContext`), including when the browser adds it after the page has loaded. The same tools are always available on `window.FMDocs.tools`, so an agent that drives the browser can use them anywhere, and so can a script: `await FMDocs.tools.query_entities.execute({type: "field", where: [{field: "global", op: "eq", value: true}]})`.
- **Read-only.** No tool changes anything. No tool runs code an agent writes: `query` only takes JSON steps. The data is written from the scrubbed model, and the scrubbing guard checks `.js` files too.
- `tests/webmcp_questions.md` lists 30-odd plain-English questions and the calls that answer them.

### Multi-file solutions (FileMaker 26 folder exports)

FileMaker Pro 26 can Save a Copy as XML for several files at once. Point `build` at the folder it wrote:

```bash
fm-saxml build ./SaXML_PROD_2026-10-14
```

Each file gets its own subfolder (named after the FileMaker file, e.g. `Clients/`), laid out exactly like a single-file build. References from one file into another (external table occurrences, relationship predicates, layout fields, Perform Script from another file, Go to Related Record) become links to the other file's pages, and the target's "Used By" / "Referenced By" lists show callers from the other files. A combined `index.md` lists every file with what it references and what references it, `Reports/batch-summary.md` shows how each external data source was paired with a file, and `Reports/redactions.md` is the master list of what was scrubbed: each placeholder and the files it appears in, plus everything flagged for review. Placeholders are shared across the files, so the same secret has the same placeholder everywhere.

- Both export styles work: one XML per file, or **separate catalogs** (one folder per file with one XML per catalog). A single file's catalog folder can also be built on its own.
- `Summary.xml` is used to warn about files it lists that are missing from the folder.
- Data sources are paired with files by their file path (`file:Clients` → `Clients.fmp12`). References into files that aren't in the folder stay plain text and are listed in the index.
- A file that can't be converted is reported and skipped; the others are still built, and the exit code is 1.
- `--strict` also fails on files missing from `Summary.xml`, skipped XMLs, ambiguous pairings and cross-file targets that don't exist. `--model-out` isn't supported for folders.
- `inspect` and `validate` accept a folder too.

### Secret and personal-data scrubbing

Scrubbing is **on by default** for `build`, `parse`, `render` and `diff`. Before any output is written, credentials, tokens and other secrets found in the export are replaced with numbered placeholders. Personal data (emails, card numbers, home-folder usernames) and internal hostnames are kept unless you raise `--scrub-level` to `standard` or `strict`. The calculation logic around them is left intact:

```text
Let ( [ $apikey = "sk-proj-a8Kz9…" ; $url = "https://fms.corp.local/api" ] ; … )
            ↓
Let ( [ $apikey = "[REDACTED:api_key#1]" ; $url = "https://[HOST#1]/api" ] ; … )
```

The same value gets the same placeholder everywhere, so a reader can still tell that two scripts share one key. `Reports/redactions.md` lists every redaction with its location and a masked preview. It never shows the values.

| Flag | Purpose |
|---|---|
| `--disable-scrubbing` | Turn scrubbing off. Output contains secrets as-is, and the report says so. |
| `--scrub-level secrets\|standard\|strict` | `secrets` (default): credentials only. `standard`: also internal hosts and private IPs, home-folder usernames, emails, card numbers. `strict`: also random-looking string literals and account / modified-by names. |
| `--scrub-keyword WORD` | Treat names containing `WORD` as credentials, in addition to the built-in list (`apikey`, `token`, `password`, `secret`, …). Repeatable. |
| `--scrub-allow REGEX` | Never redact values matching `REGEX`. Repeatable. |
| `--fail-on-secrets` | Exit with status 1 (after writing everything) if the export contains hardcoded credentials. For CI. |

`strict` also covers phone numbers, IBANs (checksum-verified) and US SSN / Canadian SIN numbers.

**Allowing a calculation.** A comment containing `fm-saxml:allow` leaves that calculation exactly as written. For example, write `/* fm-saxml:allow: public sandbox key */` above a documented test key. Values in an allowed calculation are allowed everywhere, so the same key isn't redacted next door. Allowed items are listed in the report.

**Stable placeholders across runs.** Placeholders are numbered per run (`#1`, `#2`), so two separately saved `model.json` files can't be compared value by value, and `diff` warns about this. Set `FM_SAXML_SCRUB_SALT` to a private value of at least 16 characters to get keyed fingerprints instead (`[REDACTED:password#3f9a1c]`). These are the same for the same value in every run that uses the salt. Keep the salt private: anyone holding it can test guesses against a fingerprint.

#### Scrubbing the XML itself (`scrub`)

```bash
fm-saxml scrub MySolution.xml                       # writes MySolution.scrubbed.xml
fm-saxml scrub MySolution.xml -o share.xml --report share.redactions.md
```

`scrub` writes a redacted copy of a Save a Copy as XML export, for sharing the raw XML with an AI tool or another developer. It applies everything `build` would redact to every copy of each value: the calculation, its tokenized ChunkList, and the rendered step text in `DDR_INFO`.

- It removes the `hash` attributes of changed elements, since a digest of the original content could be used to confirm a guessed password.
- Binary streams are left untouched.
- The output is the input file with only those spans patched: same encoding (including UTF-16 and its BOM), declaration, line endings and formatting. A diff between the two shows exactly what was redacted.
- It accepts only `FMSaveAsXML` exports. Clipboard XML (`fmxmlsnippet`) and DDR reports (`FMPReport`) are refused, because they lay out step parameters differently.

What is detected:

- Provider key formats (OpenAI, Anthropic, Google, AWS, GitHub, GitLab, Slack, Stripe, SendGrid, OttoFMS, JWTs, webhook URLs, …).
- `keyword = "value"` assignments, including inside commented-out code.
- JSON bodies, HTTP headers, cURL `-u`, URL passwords and secret query parameters, and connection strings.
- Base64 `user:password` values, and every literal in a private-key calculation.
- By position in the script:
  - password parameters (Re-Login, Reset Account Password, …) and Configure AI / RAG Account;
  - Set Variable into a credential-named variable, and Set Field into a credential-named field;
  - JSONSetElement credential keys, Crypt* keys, MBS credential calls and plugin licence registration.

  A secret passed as a `$variable` is traced back to the Set Variable that assigned it and redacted there.
- Credentials written as prose in comments ("temp password is swordfish99").

Some things are **flagged for review** instead of changed, in a "Needs review" section of the report:

- a credential read from a field (nothing in the file to redact);
- a variable whose source couldn't be found;
- a plain word stated as a password in a comment.

Only string literals and comments are ever changed. After writing, a guard searches every output file for each redacted value. If one survived somewhere the scrubber doesn't look (for example, a script *named* after a password), the run fails with exit code 2.

This is a heuristic scrubber, not a guarantee: review output before sharing it. Detection rules are adapted from Andrew Kear's [FileMaker XML Scrubber](https://github.com/andykear/FileMaker-XML-scrubber) (Clockwork Creative Technology, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). The design and roadmap are in [secret-redaction.md](./secret-redaction.md).

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
- Relationship names and script folder paths are **derived during normalization**, not read directly from the XML.
- Script steps are shown as **FileMaker prints them** in the Script Workspace, taken from the `StepText` entries in the export's `DDR_INFO` section (scrubbed like any calculation). Steps without one (older exports, older `model.json` files) are rebuilt from their parameters instead.

## Known limitations

- **A missing "Called By" is not proof that a script is unused.** Buttons, button groups, layout and object triggers, File Options triggers and Perform Script steps are all traced, but a script can also be run from a custom menu item in another file, by name from a calculation (`Perform Script by name`), or by FileMaker Server schedules, none of which the export links to a script page.
- **Custom privilege lists for layouts, value lists and scripts** are read generically (each row's object and its access columns), because the sample exports used for testing only have custom *record* privileges. Unusual shapes still come through, but their column names are FileMaker's raw element names.

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

The secret-detection rules in `src/fm_saxml/scrub/` are adapted from the [FileMaker XML Scrubber](https://github.com/andykear/FileMaker-XML-scrubber) by Andrew Kear, Clockwork Creative Technology, used under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
