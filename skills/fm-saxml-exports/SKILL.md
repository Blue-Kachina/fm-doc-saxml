---
name: fm-saxml-exports
description: Use for questions about a FileMaker solution's fm-saxml docs ('what calls script X', 'what uses this field', 'who can access X', 'what changed', 'is X unused') or to run the fm-saxml CLI.
metadata:
  author: "Matthew Leering"
  tags: [filemaker, fm-saxml, analysis, references]
compatibility: Needs docs built by fm-saxml-converter. The Python API and the CLI need fm-saxml installed (Python 3.11+); the WebMCP tools need a --webmcp build.
---

# Answering questions from fm-saxml output

`fm-saxml` turns a FileMaker "Save a Copy as XML" export into a folder of Markdown pages, a stable JSON
contract, and optionally an HTML viewer with agent tools. Everything is **read-only, scrubbed of secrets by
default, and built from the model, not the raw XML**. The goal here: reach the right answer with the fewest
reads. Large solutions have thousands of pages; never browse them.

## Purpose

Answers per-solution questions (what uses X, what X uses, who can access X, what changed between exports, what is unused, what a rename breaks) from a converted solution, by picking the cheapest source among the JSON contract, the Markdown pages, the WebMCP tools and the CLI. It reads the docs and never changes them; to refresh them, rebuild with `fm-saxml build`.

## Prerequisites

- A docs folder built by fm-saxml (`docs.json` at its top level). The export's XML is needed only for `diff`, `rename-check`, `inspect` and a rebuild.
- For the Python API and the CLI: a Python 3.11+ with fm-saxml installed (`import fm_saxml` works; `pip install fm-saxml-converter`).
- For the WebMCP tools: a build with `--webmcp`, opened by URL or served with `fm-saxml serve`.

## Step 0: find out what you were given (30 seconds, do this first)

Locate the docs folder. If you were not told, check `exports/<Solution>/`, `$FM_SAXML_DOCS_ROOT`, a sibling `<name>_docs` folder. Then look at the top level only:

| You see | It means | Use |
|---|---|---|
| `docs.json` | A build root. Read it first: `kind` is `"single"` or `"batch"`, `solution` is the name, and `files[]` gives each FileMaker file's `name`, `folder` (`""` for a single file) and `fileMakerVersion` | always |
| `entities.json`, `references.json`, `backlinks.json`, `external-references.json` | The JSON contract (default on) | counting, filtering, graph questions |
| `index.md`, `Tables/ Scripts/ Layouts/ ...` | Markdown pages | reading one entity |
| `Reports/` | Precomputed reports (`summary`, `profile`, `warnings`, `unresolved-references`, `indirection`, `redactions`). `coverage.md` appears only if built with `--coverage` **and** the export carries coverage data (a v2-format export; an older FileMaker 19 fixture built with `--coverage` still produced none) | overviews, health, dead-code hints |
| `raw/` (`scripts.json`, `layouts.json`, `themes.json`, `menus.json`) | Scrubbed original XML per entity. Can be empty for older v1-format exports, in which case `raw_xml()` raises `RawXmlNotFoundError` | exact step or layout object XML |
| `index.html`, `_viewer/` | `--html` viewer | humans; also agents via URL |
| `_viewer/webmcp.js`, `_viewer/data/`, `llms.txt` | `--webmcp`: query tools available | cross-cutting questions in one call |
| `docs.json` with `kind: "batch"`, one subfolder per FileMaker file, a combined `index.md`, and only `Reports/batch-summary.md` + `redactions.md` at the root | Multi-file solution. The contract files (`entities.json` etc.), `Reports/` and `raw/` live **inside each file's subfolder**, not at the root | see "Multi-file solutions" below |
| `_companion_job.json` | Written when a harness ran the build: records `html`, `webmcp`, `export_path`, `docs_root`, per-stage timings | quick way to learn which flags were used |

Also note `schemaVersion` and `generator.version` in any contract file's envelope. The docs may be older than
the export or the repo; say so if it matters. If something you need is missing (no `--webmcp`, no
`--coverage`), rebuilding is cheap and usually better than working around it (Optimizations, item 6).

## Choosing the source

Rule of thumb: **Markdown to read one thing, JSON or tools to ask about many things.**

| Question shape | Best source | Why |
|---|---|---|
| "What does script/layout/field X do?" "Show me X" | Markdown page for X (`Scripts/<name>.md`) | Rendered steps, calc text, settings and Used By / Uses links in one file |
| "What uses X?" "What does X use?" | `backlinks.json[docId]` / `references.json`, or the page's Used By section; or WebMCP `find_references` | One lookup. Never grep page text for a name |
| "How many / which of kind K where attribute...?" | `entities.json` filtered with `jq` or Python; or WebMCP `query_entities` | Structured attributes, exact values |
| Multi-hop ("everything that eventually calls X", path between two TOs) | WebMCP `traverse` (or walk `references.json` in code) | Transitive closure is awkward by hand |
| "Who/which privilege sets can run, view, edit X?" | WebMCP `who_can_access` / `what_can_access` | Effective access is computed (with reason); it is not a stored field |
| Exact step options, a layout object's raw XML | `raw/*.json` via `fm_saxml.load(...).raw_xml(docId)` | Markdown summarises; raw is lossless (still scrubbed) |
| "Give me an overview / how big / what's risky" | `Reports/profile.md`, `Reports/summary.md`, `index.md` | Precomputed; free |
| Dead code | `find_unreferenced`, or `Reports/warnings.md` (`UNUSED_FIELD_CANDIDATE`) | These are **candidates**: calls by name, other files, schedules and plug-ins can hide use |
| Names written in text (`GetField`, Perform Script by name, `ExecuteSQL`) | `Reports/indirection.md`, WebMCP `find_indirection` / `rename_impact` | Normal references miss these |
| "What breaks if I rename X?" | `fm-saxml rename-check <input> "Table::Field"` or `rename_impact` | Covers by-name uses |
| "What changed between two exports?" | `fm-saxml diff old.xml new.xml -o diff.md` | Semantic diff, not a text diff |
| Parse errors, odd input, is the export sane | `fm-saxml inspect` / `validate` / `doctor` | Counts and warnings without building |

### Reading JSON efficiently
- **Do not read `entities.json` whole.** It can be many MB. Filter first, in Python (`jq` is often not installed, notably on Windows):
  `python -c "import json;d=json.load(open('entities.json'));print([k for k,v in d['scripts'].items() if 'Invoice' in v['name']])"`
  Top-level keys are the envelope (`schemaVersion generator source`) plus the collections, so `d['scripts']` is `{docId: entity}`. A script entity has `name steps folderPath referencedFields referencedLayouts referencedScripts variables warnings runWithFullAccess ...`.
- Prefer the Python API over hand-parsing; it is typed and handles batches:
  ```python
  import fm_saxml
  d = fm_saxml.load(path)                 # SolutionDocs, or BatchDocs for a multi-file build
  d.find("script", "Create Invoice")      # by name, case-insensitive
  d.get("field:Invoices::Total")          # by docId
  d.refs_to("script:Create Invoice")      # who uses it
  d.refs_from("script:Create Invoice")    # what it uses
  d.collection("layouts")                 # {docId: entity}
  d.raw_xml("scriptStep:Create Invoice:0003")
  fm_saxml.find_docs("Invoices")          # locate a build under $FM_SAXML_DOCS_ROOT
  ```
- Collections: `tables fields tableOccurrences relationships layouts layoutObjects scripts scriptSteps customFunctions valueLists privilegeSets accounts extendedPrivileges customMenus customMenuSets themes fileReferences variables externalDataSources indirectionSites`, plus `fileOptions` and `graphNotes`.
- **docIds**: `field:Table::Field`, `script:Name`, `layout:Name`, `to:Name`, `scriptStep:Script:0003` (0-based, positional), `layoutObject:Layout::<objectId>`, `privilegeSet:Name`, and so on. They follow names (a rename changes them), and duplicate names become `script:Name (#id)`. Names can contain `/`, so split scoped ids on the **first** `/` only.
- **Multi-file**: docIds may be scoped (`<file uuid>/...`, `file:<name>/...`, `ds:<data source>/...`). Use `BatchDocs.resolve(scoped_id)` rather than parsing them. Unscoped lookups are per file: `batch["Clients"].get(...)`.
- Contract timestamps do not exist and files are byte-reproducible: diffing two builds' JSON is a valid change check.
- Layout `bounds`, `width`, `height` are in points. `options` bitfields are not decoded.

### Reading Markdown efficiently
- Open the **one** page you need; follow its links for neighbours. Never glob-read a folder.
- **Do not guess page paths.** Script and layout pages are nested in their FileMaker folders (`Scripts/Customer Scripts/Create Customer.md`, not `Scripts/Create Customer.md`), fields live under `Fields/<Table>/`, layout objects under `LayoutObjects/<Layout>/`, and names are slugged (unusual characters and Windows-reserved names like `CON` and `NUL` are altered). Get the path from a WebMCP result (`find_unreferenced` and others return a `path` such as `Scripts/SendEmail.md`), or from the type folder's `index.md` (e.g. `Scripts/index.md`, which lists folders and links to every page).
- Type folders only exist when the solution has that kind of entity (a build with no layout objects has no `LayoutObjects/`). Older, v1-format exports have no `Accounts/`, `Themes/` and so on.
- If many pages must be searched by prose, index the folder once with a doc indexer (jDocMunch or similar) rather than grepping repeatedly.

## Multi-file solutions

Verified on a real two-file build (`disRenewalUniverse` + `idiClients`: 6,743 and 21,365 references,
`entities.json` of 14.6 MB and 19.6 MB). Treat each file as its own docs folder and the batch as a set.

- `fm_saxml.load(root)` returns a `BatchDocs`: iterate it for file names, `batch["idiClients"]` gives that file's `SolutionDocs`. `batch.resolve(scoped_id)` follows a scoped docId to `(file, docId, entity)` and returns `None` when the target file is not in the build (the pairing's `reason` in `docs.json` says why, e.g. "file not in this build").
- **Cross-file links are stored as scoped ids.** A reference from file A to file B has a target like `ds:<data source uuid>/field:idiClients::Entreprise`. In B's `backlinks.json`, the other file's callers appear as sources like `xfile:disRenewalUniverse/layout:Contrat - Liste`. So **`batch["B"].backlinks[docId]` includes callers from other files; `refs_to(docId)` does not** (it is "from this file" only: 116 vs 123 on the field checked).
- **The WebMCP tools are per-file.** On the same field, `find_references` (incoming) returned 115 items, all from `idiClients`, while `backlinks.json` and the Markdown page's Used By list also show 7 callers from `disRenewalUniverse`. `find_references` outgoing from the calling field also showed nothing in the other file, and `traverse` stayed in one file. So for any "what in other files uses X" or "does this file depend on that one" question, use `backlinks.json` / `BatchDocs`, the `Reports/batch-summary.md` pairing table, or `external-references.json`, and do not trust an empty WebMCP result as "no cross-file use".
- Tool results do tell you the file: each item has `file` and a `path` already prefixed with the file's folder (`idiClients/Layouts/Coordonnees.md`, relative to the batch root). Two files can contain the same docId, so always carry `file` along with `docId`.
- Python API object shapes: `references`, `backlinks`, `entities`, `external` are **properties** (no parentheses), `refs_to()`, `refs_from()`, `find()`, `get()`, `collection()`, `raw_xml()` are methods. Pydantic attributes are snake_case (`source_doc_id`, `target_doc_id`, `relationship_type`, `external_data_source`) while the JSON files use camelCase (`sourceDocId`). `ExternalDataSource.pairing` says which batch file a data source resolved to.

## WebMCP / `window.FMDocs` (the `--webmcp` viewer)

Only present if built with `--webmcp`. Read-only query tools that run against the model (`describe_schema` first, then `search_entities`, `query_entities`, `find_references`, `traverse`, `who_can_access`, `rename_impact`, `query` and others), faster than reading pages for cross-cutting questions, and per-file in a multi-file build. Call them natively when the viewer is served (`fm-saxml serve <docs>`), or by URL: `index.html#/results?q=<URL-encoded {"tool":"<name>","args":{...}}>&format=json`.

Read `references/webmcp.md` before the first call: it lists all 17 tools, their result shapes, the three ways to call them and worked examples.

## Optimizations

1. **Look before you read**: `docs.json` + `Reports/summary.md` tell you scope, file list and warnings in two small reads.
2. **Ask the narrowest source**: one docId lookup beats a search; a tool call beats reading ten pages.
3. **Filter before loading** large JSON (see "Reading JSON efficiently"); never paste whole collections into context. Return counts and a short sample, and say how to get the rest.
4. **Cite docIds** in answers so the reader can verify (and so follow-ups are one lookup).
5. **Batch questions** into one `query` pipeline or one Python session instead of many round trips.
6. **Rebuild instead of working around gaps.** Cheap flags worth adding:
   `fm-saxml build <xml-or-folder> --webmcp --coverage --docs-root <root> --force -y`
   `--coverage` writes `Reports/coverage.md` for v2-format exports (what the parser did and did not understand: consult it before claiming something does not exist), and the build prints one "Coverage: ..." line. If neither appears, the export has no coverage data; say coverage is unknown rather than complete. `--docs-root` or `FM_SAXML_DOCS_ROOT` makes builds findable by solution name. `raw/` and the JSON contract are on by default; `--no-raw-xml` and `--no-include-json` turn them off, so check for them before relying on either.
7. **Scripted runs**: `--progress json` emits machine-readable progress lines; `--strict`, `--fail-on-secrets`, `--fail-on-coverage-gap` set exit codes for CI. Output is staged and swapped in, so a failed build leaves the previous docs intact. Do not rebuild into a folder a reader or server has open.
8. **Staleness**: compare `generator.version` and the export's name/date to what the user is asking about. A rename or new export means rebuild.

## Limitations

State the ones that apply in the answer.

- **Scrubbed**: secrets and personal data are replaced with placeholders (see `Reports/redactions.md`). A missing or odd value may be a placeholder, not a bug in the solution. Never try to recover scrubbed values.
- **Unused means "no static reference found"**: say candidate, not dead. Dynamic names, other files, schedules, web direct, plug-ins and external callers are invisible. `find_unreferenced` is noisy for scripts: on the real solution it flagged 178 of 193 scripts (92%), mostly legitimate entry points (server-side scheduled and PSOS scripts, test scaffolds, dev tools, API and menu-bound scripts; items carry the script's folder in `detail`, and 76 had none). Group the result by `detail` folder, set aside obvious entry-point folders, and report the remainder with the tool's own `caveat`. The same tool is far more useful for fields, value lists and custom functions.
- **WebMCP tools are per-file**: in a multi-file build, an empty result does not mean "no cross-file use" (see "Multi-file solutions").
- **Coverage and raw XML depend on the export**: `Reports/coverage.md` needs a v2-format export (and `--coverage`), and `raw/` can be empty for older v1-format exports. Without them, say coverage is unknown and read the Markdown page instead of raw XML.
- **Names in text** (`Evaluate`, `ExecuteSQL`, `Perform Script by name`) are classed hardcoded / traced / opaque / broken / safe. Opaque ones cannot be resolved statically.
- **Access answers** are derived from privilege sets and accounts and include a reason; relay the reason.
- **Multi-file**: a reference into a file not in the folder stays plain text and is listed in the index; do not claim the target does not exist.
- The converter documents the export, not live data. It cannot say what records contain.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `raw_xml()` raises `RawXmlNotFoundError` | A v1-format export (empty `raw/`), or a build with `--no-raw-xml` | Rebuild without `--no-raw-xml`; for a v1 export, read the Markdown page |
| No `entities.json` or `references.json` at the root | A multi-file build (they sit in each file's subfolder), or a build with `--no-include-json` | Open the file's subfolder; otherwise rebuild without `--no-include-json` |
| `ModuleNotFoundError: No module named 'fm_saxml'` | A Python without fm-saxml | Use the Python fm-saxml is installed in, or `pip install fm-saxml-converter` |
| `jq` not found | Not installed (common on Windows) | Use the Python one-liner in "Reading JSON efficiently" |
| A page path does not exist | Guessed path: pages are nested in FileMaker folders and names are slugged | Take the `path` from a tool result or the type folder's `index.md` |
| Header badge says "WebMCP off: opened from disk" or "WebMCP not in this browser" | Viewer opened from `file://`, or a browser without WebMCP | Use the URL route, or `fm-saxml serve <docs>` |
| `who_can_access` returns `{error, hint}` | The docId does not exist | Get the exact docId with `search_entities` first |
| WebMCP finds no callers from another file | The tools are per-file | Use `backlinks.json` / `BatchDocs`, `Reports/batch-summary.md` or `external-references.json` |
| No `Reports/coverage.md` after `--coverage` | The export carries no coverage data | Say coverage is unknown, not complete |

## Do not

- Grep all pages for a name to find usages (misses by-name and cross-file uses, and is slow).
- Read `entities.json`, `index.html` or `_viewer/pages/*` whole.
- Edit anything in the docs folder; rebuild instead.
- Treat `model.json` as stable. It is the tool's private save format; the JSON contract is the public one.
