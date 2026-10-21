# The JSON contract (schema 1.0)

Every docs folder holds four JSON files that other tools may read. Their shape is versioned and documented here. Anything else fm-saxml writes (the Markdown pages, `model.json`, the viewer's data) may change in any release without notice.

| File | Payload |
|---|---|
| `entities.json` | Every entity, by collection: `{docId: entity}` |
| `references.json` | `references`: every reference from one entity to another |
| `backlinks.json` | `backlinks`: `references.json` inverted, `{targetDocId: [backlink, ...]}` |
| `external-references.json` | `dataSources`, `externalTableOccurrences`, and `references` into other files |

`build` and `render` both write them. `--no-include-json` leaves them out. In a multi-file build, each file's folder has its own four.

The JSON Schema of each file is in [`contract/schema-1.0/`](contract/schema-1.0/). It's generated from the Pydantic models in `src/fm_saxml/contract_models.py`, and a test fails when the two drift apart.

## Envelope

Every file is a JSON object that starts with the same three keys:

```json
{
  "schemaVersion": "1.0",
  "generator": {"name": "fm-saxml-converter", "version": "0.7.0"},
  "source": {
    "fmpFileName": "EverythingBagel.fmp12",
    "fileUuid": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
    "scope": "400FEDB4-F509-8F4D-AF05-472A0DE02EAC",
    "fileMakerVersion": "26.0.3",
    "saxmlVersion": "2.3.0.0"
  },
  "...": "payload"
}
```

- `source` never holds a path on the machine that ran the build.
- No file holds a timestamp. Building the same export twice with the same fm-saxml release gives byte-identical files.
- `generator` is `null` in a file upgraded from before the contract existed (see Reading older files).
- In `entities.json` the collections sit at the top level, next to these keys. No collection may be named `schemaVersion`, `generator` or `source`.

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
