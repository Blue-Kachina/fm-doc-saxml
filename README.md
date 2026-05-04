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

Reference-graph analysis (layouts, table occurrences, relationships, backlinks) is in place. HTML/Vue rendering and diff/version comparison are planned in later phases.

## Requirements

- Python 3.11+
- A FileMaker Pro `Save a Copy as XML` export (UTF-16 LE encoded)

## Installation

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

The CLI is exposed as `fm-saxml`. The `--out` option is **optional** for the `build` and `render` commands — when omitted, output is written to a directory named `saxml2doc` next to the current working directory.

If the output directory already exists and is non-empty, you'll be prompted to overwrite or cancel; pass `--force` (or `-f`) to skip the prompt in non-interactive contexts.

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

# Validate the model and exit non-zero if there are critical issues.
fm-saxml validate ./MySolution.xml
```

### Custom output location

Use `--out` (or `-o`) to write somewhere other than `./saxml2doc`:

```bash
fm-saxml build ./MySolution.xml --out ./docs/MySolution
```

Planned commands include `diff` for comparing two exports.

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

Every Markdown page carries YAML front matter with `docId`, `entityType`, and source metadata so the output is friendly to static site generators and AI indexers. The top-level `index.md` records two timestamps for clarity: **XML Created At** (mtime of the source export) and **Support Documentation Created At** (when the docs were generated).

## Repository structure

```text
src/fm_saxml/
├─ cli.py               # Typer CLI entry point (fm-saxml)
├─ config.py            # Project configuration
├─ parser/              # XML parsing and per-entity extractors
│  ├─ saxml_reader.py
│  ├─ version_detector.py
│  └─ extractors/
├─ model/               # Pydantic models, references, validation
├─ normalize/           # Naming, docId assignment, path generation
├─ analyze/             # Calculation parsing, backlinks, warnings
├─ render/
│  ├─ markdown/         # Jinja2 templates and renderer
│  ├─ html/             # Future HTML/Vue renderer
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

## Roadmap

Major milestones from the plan:

1. **Phase 1** — POC: tables, fields, scripts, basic Markdown output.
2. **Phase 2** — Reference graph: layouts, layout objects, table occurrences, relationships, backlinks.
3. **Phase 3** — Markdown polish: Jinja templates, front matter, indexes, reports.
4. **Phase 4** — Analysis: dependency graph, dead-code detection, server-compatibility checks.
5. **Phase 5** — HTML/Vue interactive renderer over the same JSON model.
6. **Phase 6** — `fm-saxml diff` for version comparison between two exports.

## License

To be determined.
