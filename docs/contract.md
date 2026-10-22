# The JSON contract (schema 1.0)

Every docs folder holds JSON files that other tools may read. Their shape is versioned and documented here. Anything else fm-saxml writes (the Markdown pages, `model.json`, the viewer's data) may change in any release without notice.

From Python, read them with `fm_saxml.load()` instead of parsing them by hand (see Reading from Python).

| File | Payload |
|---|---|
| `docs.json` | At the output root only: one file's docs or a multi-file build, and where each file's docs are |
| `entities.json` | Every entity, by collection: `{docId: entity}` |
| `references.json` | `references`: every reference from one entity to another |
| `backlinks.json` | `backlinks`: `references.json` inverted, `{targetDocId: [backlink, ...]}` |
| `external-references.json` | `dataSources`, `externalTableOccurrences`, and `references` into other files |

`build` and `render` both write them. `--no-include-json` leaves them out. In a multi-file build, each file's folder has its own four, and `docs.json` sits at the root.

The JSON Schema of each file, `docs.json` included, is in [`contract/schema-1.0/`](contract/schema-1.0/). It's generated from the Pydantic models in `src/fm_saxml/contract_models.py`, and a test fails when the two drift apart.

## Envelope

The four per-file files are JSON objects that start with the same three keys (`docs.json` has `schemaVersion` and `generator`; see below):

```json
{
  "schemaVersion": "1.0",
  "generator": {"name": "fm-saxml-converter", "version": "0.7.0"},
  "source": {
    "fmpFileName": "EverythingBagel.fmp12",
    "fileUuid": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
    "scope": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
    "fileMakerVersion": "26.0.3",
    "saxmlVersion": "2.3.0.0",
    "hasDdrInfo": true
  },
  "...": "payload"
}
```

- `source` never holds a path on the machine that ran the build.
- `hasDdrInfo` is the export's `Has_DDR_INFO`, or `null` when it doesn't say. When it's `false` the export has no `DDR_INFO` block, so the docs are less complete: script steps use fm-saxml's own wording instead of FileMaker's, calculation references come from parsing the text, popover titles are missing, and external table occurrences have no base table (so `external-references.json` lacks those tables). A scripted Save a Copy as XML writes `false` unless its JSON options set `include_details`.
- No file holds a timestamp. Building the same export twice with the same fm-saxml release gives byte-identical files.
- `generator` is `null` in a file upgraded from before the contract existed (see Reading older files).
- In `entities.json` the collections sit at the top level, next to these keys. No collection may be named `schemaVersion`, `generator` or `source`.

## docs.json

The catalog at the root of every output folder. Readers start here instead of scanning subfolders.

```json
{
  "schemaVersion": "1.0",
  "generator": {"name": "fm-saxml-converter", "version": "0.7.0"},
  "kind": "batch",
  "solution": "Accounting",
  "files": [
    {"name": "Invoices", "folder": "Invoices", "fmpFileName": "Invoices.fmp12", "fileUuid": "…",
     "scope": "…", "fileMakerVersion": "26.0.3", "saxmlVersion": "2.3.0.0",
     "hasDdrInfo": true}
  ],
  "pairings": [
    {"folder": "Invoices", "dataSource": "Clients", "dataSourceUuid": "…",
     "targetFolder": "Clients", "match": "path", "reason": ""}
  ],
  "synthesizedManifest": false
}
```

- `kind` is `single` (one file's docs, in the root itself: its `folder` is `""`) or `batch` (each file in its own subfolder).
- `solution` is the name `find_docs()` looks up: the FileMaker file name for one file, the input folder's name for a multi-file export, or `--solution`.
- `pairings` (batch only) records which file each FileMaker data source was paired with, and how: `path` (the data source's path names the file), `name` (no path; matched by data source name), or `""` with a `reason`. `BatchDocs.resolve()` uses it for `ds:` scoped ids.
- `synthesizedManifest` is true when a batch's input folder had no `Summary.xml`, so fm-saxml built one in memory from the exports. Missing-file checks and the export time and host are then unavailable. See [manifest.md](manifest.md).

## Where docs live

Converted docs are **local output**: each developer builds them from their own export, and they're never committed. They hold the solution's code (scrubbed of secrets by default, but not of everything).

- `build` writes to `--out`. Without it, `--docs-root <folder>` or the `FM_SAXML_DOCS_ROOT` environment variable files the build under `<docs root>/<solution>`, so a tool can find it by name. Without either, it writes `<input name>_docs` next to the input.
- The solution name comes from the export (the FileMaker file name), not the input file's name. A timestamped export (`Invoices 2026-10-21 1530.xml`) still lands in `<docs root>/Invoices`. For a folder of exports it's the folder's name; pass `--solution` when that folder name changes between exports.
- `fm_saxml.find_docs("Invoices")` returns the folder under `$FM_SAXML_DOCS_ROOT` (or `root=`). It ignores case and matches, in order: a folder name or its slug, a `docs.json` `solution`, then a FileMaker file listed in a `docs.json` (for a batch, that file's own folder). No match, or several at one step, raises `DocsNotFoundError` listing what it found.

### Rebuilding while readers are open

`build` writes into `<out>.tmp-<pid>` next to the output folder, then swaps it in: the old folder is renamed to `<out>.old-<pid>`, the new one takes its name, and the old one is deleted. A reader never sees a half-written folder. A failed build leaves the old docs untouched.

On Windows a folder can't be renamed while a program has a file in it open. `build` retries for about 3 seconds, then stops with an error, keeping the old docs in place and the new ones in `<out>.tmp-<pid>`. Readers that load a file and close it (as `fm_saxml.load()` does) don't block it. macOS and Linux swap even with files open.

`render` still clears and rewrites its output folder in place.

## Reading from Python

```python
import fm_saxml

docs = fm_saxml.load("exports/Invoices")            # SolutionDocs, or BatchDocs for a multi-file build
docs.entities.scripts["script:Post Invoice"]         # typed entities: fm_saxml.model classes
docs.find("field", "invoices::total")                # by name, ignoring case; every match
docs.refs_from("script:Post Invoice")                # references it makes
docs.refs_to("field:Invoices::Total")                # references to it from this file
docs.get("layout:Invoice")                           # any entity by docId
docs.source.file_uuid, docs.schema_version

batch = fm_saxml.load("exports/Accounting")          # BatchDocs: a read-only mapping of file name -> SolutionDocs
batch["Invoices"].entities.layouts
batch.resolve("ds:EEC9827D-…/field:Clients::Name")   # ResolvedRef(file, doc_id, entity), or None

fm_saxml.find_docs("Invoices")                       # the docs folder, under $FM_SAXML_DOCS_ROOT
```

Each file is read on first use, upgraded if an older fm-saxml wrote it, and validated. Loading `entities.json` and `references.json` for a 218 MB export takes about 1.5 seconds.

**Public surface.** These names follow the contract's version policy:

- `fm_saxml`: `load`, `find_docs`, `SolutionDocs`, `BatchDocs`, `ResolvedRef`, `DocsNotFoundError`, `ContractVersionError`
- `fm_saxml.model`: every class in its `__all__` (the entity classes, `ReferenceRecord`, `ExternalTarget`, `IndirectionSite`, …). Their fields are the contract's keys.
- `fm_saxml.contract_models`: one model per file (`EntitiesDoc`, `ReferencesDoc`, `BacklinksDoc`, `ExternalReferencesDoc`, `DocsCatalog`)
- `fm_saxml.contract_migrations.read_contract_file(path)`

Everything else in the package is internal.

`fm-saxml rename-check` reads a docs folder the same way: `fm-saxml rename-check exports/Invoices "Invoices::Total"`.

## Versions

`schemaVersion` is `MAJOR.MINOR`. One version covers all four files.

| Change | Version | Readers |
|---|---|---|
| A new key, collection or entity field | minor (1.0 → 1.1) | Read it as-is. Ignore keys they don't know; keys a file lacks take their defaults. |
| A key renamed, removed, retyped, or a docId form changed | major (1.x → 2.0) | Upgrade older files on load. Refuse newer majors. |

Compare versions as numbers, never as strings (`"1.10"` is newer than `"1.9"`). `fm_saxml.contract.parse_version` does this.

### Reading older files

`fm_saxml.contract_migrations.read_contract_file(path)` reads any of the four files and returns its typed model at the current version:

- **Before the contract** (fm-saxml 0.6.x and earlier) counts as version 0.0:
    - a file with no `schemaVersion`: references.json as a bare array, entities.json and backlinks.json without the envelope
    - external-references.json with its old `"schemaVersion": "1.0.0"` (three parts)
- **Older major:** upgraded in memory, one major at a time (`UPGRADES`). Nothing is written back. 0.0 → 1.0 adds the envelope, wraps the references and backlinks payloads, and drops the absolute `source.fileName` from external-references.json.
- **Newer minor:** read as-is.
- **Newer major:** fails with `ContractVersionError`: `docs written by schema 2.x; this fm-saxml reads up to 1.x — upgrade fm-saxml`, with the file's path.

## docIds

Every entity has a `docId`: a type prefix and its name, as written in FileMaker (trimmed, case kept). Collections are keyed by it, and references point at it.

| Collection | `docId` form | Required keys |
|---|---|---|
| `tables` | `table:<Table>` | docId, name, fmpId |
| `fields` | `field:<Table>::<Field>` | docId, name, qualifiedName, baseTableDocId, dataType, fieldType, fmpId |
| `tableOccurrences` | `to:<TO>` | docId, name, baseTableDocId, fmpId |
| `relationships` | `relationship:<leftTO>__<rightTO>`, else `relationship:rel_<id>` | docId, name, fmpId, leftTableOccurrenceDocId, rightTableOccurrenceDocId |
| `layouts` | `layout:<Layout>` | docId, name, fmpId |
| `layoutObjects` | `layoutObject:<Layout>::<object id>`, else `…::idx<NNNN>` | docId, layoutDocId |
| `scripts` | `script:<Script>` | docId, name, fmpId |
| `scriptSteps` | `scriptStep:<Script>:<NNNN>` (0-based position) | docId, scriptDocId, index, stepId, name |
| `customFunctions` | `customFunction:<Name>` | docId, name, fmpId |
| `valueLists` | `valueList:<Name>` | docId, name, fmpId |
| `privilegeSets` | `privilegeSet:<Name>` | docId, name, fmpId |
| `accounts` | `account:<Name>` | docId, name, fmpId |
| `extendedPrivileges` | `extPriv:<Name>` | docId, name, fmpId |
| `customMenus` | `customMenu:<Name>` | docId, name, fmpId |
| `customMenuSets` | `customMenuSet:<Name>` | docId, name, fmpId |
| `themes` | `theme:<internal name>` (`displayName` is the name shown in FileMaker) | docId, name, fmpId |
| `fileReferences` | `fileRef:<type>:<name>` | docId, name, fmpId |
| `variables` | `variable:$$global`, or `variable:<Script>::$local` | docId, name, scope |
| `externalDataSources` | key `dataSource:<Name>` (the entity has no `docId` field) | name |
| `indirectionSites` | `<source docId>#ind<n>` | docId, sourceDocId, sourceEntityType, sink, nameKind, expression, class |

Two more keys aren't collections: `fileOptions` (an object, or `null` when the export has none) and `graphNotes` (a list).

Fields some readers look for:
- **Custom menus and menu sets** have `uuid` and `catalogUuid`: the UUID of the file's `CustomMenuCatalog` (on menus) or `CustomMenuSetCatalog` (on sets), which a pasted menu or set must name. Menu items have `uuid`; FileMaker gives a pasted item a new one. `fileOptions` has the default menu set's `defaultMenuSetId` and `defaultMenuSetUuid`, and layouts have `menuSetUuid`. Even `[Standard FileMaker Menus]` has a different UUID in each file, so read it from the file in question. The menu and menu set pages carry `fmpId`, `uuid` and `catalogUuid` in their front matter too.
- **Layouts and layout objects**: `bounds`, layout `width` and part `height` and `absolute` are in **points**, the same numbers FileMaker's clipboard uses. Objects are identified by `objectId` (FileMaker's `id`); SaXML objects have no `key`. Field controls have `displayStyle` (`editBox`, `dropDownList`, `popUpMenu`, `checkboxSet`, `radioButtonSet`, `dropDownCalendar`, `concealedEditBox`) and the raw `displayStyleCode`; an unknown code is passed through as its number. `options` on layouts, parts and objects is FileMaker's bitfield, not decoded. Objects and parts have `localStyle` (`{type, name, displayName}`): for `ThemeCustomStyle`, `name` is a key of the layout's theme's `namedStyles`. Layouts have `themeUuid` and `themeBase`.
- **Themes** have `uuid`, `baseName` and `baseVersion` (the built-in theme a custom theme was made from), and the theme's metadata as `{key: value}` maps: `namedStyles` (style class → name shown in FileMaker), `colorPalette` (`swatch1`… → `#rrggbb`), `layoutBuilder` and `charting`. The theme's CSS and every object's local CSS text aren't in the contract yet. Theme metadata and style names are never scrubbed: they hold no credentials, and skipping them keeps a colour or style class from tripping a detector.
- **Script steps** have `uuid`, which stays the same when steps above them move (their docId is positional).
- **External data sources** have `pairing` in a batch build: `{file, folder, match, reason}`, the batch file the data source was paired with (`file` and `folder` are `null` when it wasn't, and `reason` says why). It's `null` in a single-file build. `docs.json`'s `pairings` hold the same information for the whole batch.

What readers should know about docIds:

- **They follow names.** Renaming something in FileMaker changes its docId, and the docIds of everything named after it (a table's fields, a script's steps).
- **Step ids are positional.** Inserting a step renumbers the steps after it.
- **Duplicate names.** FileMaker allows two scripts or two layouts with one name: the second and later get `script:<Name> (#<id>)`. The same applies to file references. For other types FileMaker keeps names unique. If an export ever breaks that, only one entity is kept and the docs carry a `DUPLICATE_NAME` warning.
- **`/` can appear in a docId** (script names allow it). Split scoped ids on the first `/` only.

### Scoped docIds

Inside one file's docs, docIds are unscoped. To name an entity across files, prefix a scope: `<scope>/<docId>`.

| Scope | Meaning |
|---|---|
| `<file UUID>` | A file whose UUID is known. This is `source.scope` in the envelope. |
| `file:<name.fmp12>` | Fallback when an export has no file UUID |
| `ds:<data source UUID>` | Provisional: "the file that data source names". Used for targets in other files. 1.0 doesn't rewrite these after a multi-file build pairs the files. |
| `xfile:<folder>/<docId>` | Only as a backlink's `sourceDocId` in a multi-file build: a reference from the file in that output folder |

`/` and `%` inside a scope's name are written as `%2F` and `%25`.

## References

Each entry of `references.json` has `sourceDocId`, `sourceEntityType`, `targetDocId`, `targetEntityType` and `relationshipType`. Optional keys: `role`, `confidence`, `rawText`, `externalTarget`, `via`, `siteDocId`.

| `confidence` | Meaning |
|---|---|
| `exact` | Read from an internal id in the export |
| `parsed` | Read from calculation text |
| `inferred` | Worked out indirectly, for example a name traced through a variable |
| `unresolved` | Names something this export doesn't contain. `targetDocId` is a best guess. |
| `external` | Points into another file. `targetDocId` is scoped (`ds:…/…`), and `externalTarget` holds what's needed to find it there. |

`via: "byName"` marks a reference made by a name in a string (`GetField`, `Perform Script` by name, ...). FileMaker doesn't update these on rename. `siteDocId` names the `indirectionSites` entry behind it.

Every `targetDocId` is either a key in `entities.json`, a scoped id, or carries `confidence: "unresolved"`.

`backlinks.json` lists the same references under their target, without the target keys. In a multi-file build it also holds references from the other files (`sourceDocId: "xfile:…"`).

## external-references.json

It describes everything this file reaches in other files, so a later run can resolve those references without parsing this export again:

- `dataSources`: this file's External Data Sources.
- `externalTableOccurrences`: its table occurrences whose base table lives elsewhere.
- `references`: each reference into another file. `sourceScopedDocId` uses this file's scope, and `target.scopedDocId` uses the provisional `ds:` scope.

To resolve a target against the other file, match `target.uuid` first, then `target.fmpId`, then `target.name` (for fields: `target.baseTable` with `target.name`).

## Changing the contract

1. Change the models in `contract_models.py`, and the writer in `render/json/writer.py` to match. A test round-trips each file through its model, so it fails if the two disagree.
2. Raise `CONTRACT_VERSION` in `contract.py`: the minor for a minor change, the major for a major one. A major change also needs an upgrade in `UPGRADES` (`contract_migrations.py`) and a fixture test that upgrades the previous major's golden copy. The new version writes its schemas to a new `contract/schema-<version>/` folder; keep the older folders.
3. Regenerate the committed schemas and the golden output: `uv run pytest tests/test_contract_versions.py --update-golden`. Review the diff, then commit `docs/contract/` and `tests/fixtures/contract_golden/`.
4. Update this page.
