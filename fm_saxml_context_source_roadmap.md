# fm-saxml as the single context source — roadmap

Date: 2026-10-21. Source: Phase 1 of the published "FileMaker Agentic Dev on Windows — Roadmap" ([doc](https://claude.ai/artifact/GkyhUeLsp3iH88dHTsxpbh)), only the units marked `[saxml]`. Baseline: `master` at `be5d247` (v0.6.2).

Phase 1's outcome, as published: *fm-saxml's model holds everything agentic-fm's tools need, including multi-file exports made by a script, so nothing downstream needs the exploder's XML.*

This file goes below the surface of each unit: what the code does today (with file:line), the decisions to make, the work broken into sessions where needed, and the unknowns. Paths are relative to `src/fm_saxml/` unless they start with a repo name. `afm/` means `dis-custom-agentic-dev-harness/tools/agentic-fm/`. `H` means `dis-custom-agentic-dev-harness/tools/saxml_to_agentic_context.py`.

## Status

F0 done (fixtures in `samples/by_type/`, v0 contract fixture frozen in `tests/fixtures/contract_v0/`). Nothing else started. Research done 2026-10-21 (three read-only surveys of this repo, agentic-fm and the harness adapter).

---

## 1. What the research changed

The published units are mostly right, but six findings change their size or shape:

| # | Finding | Effect on the plan |
|---|---|---|
| 1 | **Nothing reads `entities.json` or `references.json` today.** `diff`, `rename-check` and `render` read `model.json`; webmcp, serve, coverage and batch linking use the in-memory model. | We can fix the JSON shape now with no migration pain inside this repo. Check H and agentic-fm before calling it free (C1a). |
| 2 | **`entities.json` holds 11 of the model's 18 entity maps.** Missing: accounts, extendedPrivileges, customMenus, customMenuSets, themes, fileReferences, variables, plus externalDataSources, indirectionSites, fileOptions (`render/json/writer.py:89-101`). References point at docIds that the file doesn't contain. | The contract unit must first make the file complete. Two gap units (menus, data sources) are half-solved by that. |
| 3 | **`references.json` is a bare JSON array** (`writer.py:108-111`). | It can't carry `schemaVersion`. Wrapping it is a breaking change, so it must happen in contract 1.0. |
| 4 | **The manifest never takes part in pairing.** Cross-file pairing matches the data source's path against each export's root `File` name (`batch/links.py:157-202`). Summary.xml only feeds warnings, `--strict`, `validate` and two index rows. | "Use the synthesized manifest for pairing" becomes a test, not a change. A synthesized manifest built from the exports always agrees with itself, so its checks never fire. M1–M3 are reshaped below. |
| 5 | **The SaXML export has everything the gap units ask for** (theme CSS and metadata, menu and catalog UUIDs, layout `LocalCSS`, step subtrees). It's the model that drops them. | All gaps are extractor and model work, with no workarounds. |
| 6 | **Under the harness today, agentic-fm's five readers have no input at all.** H writes `.index` files and sanitized scripts, but not the `xml_parsed/{scripts,layouts,themes,custom_menus,custom_menu_sets,external_data_sources}` folders they read. | Phase 2's golden fixtures can't come from the harness. They need the real exploder run once (Open question Q1). |

## 2. Units at a glance

| ID | Published unit | Verdict | Sessions |
|---|---|---|---|
| F0 | *(new)* Fixtures | Add. Every unit below needs a committed sample with themes, menus and sets, styled layouts, data sources and real step shapes. | 1 |
| C1 | Publish the model as a versioned contract | Keep. Split into 4 parts: complete the files, wrap them, add versions and migrations, then document. | 4 |
| C2 | Python reader API | Keep. Depends on C1. | 2 |
| C3 | Agree on the output location | Keep. Needs a root catalog JSON that doesn't exist yet. | 1 |
| M1 | Specify a synthesized `Summary.xml` | Reshape. Write a spec with a provenance flag, and decide whether the FileMaker export script writes the manifest itself (Q4). | 1 (with M2) |
| M2 | Generate `Summary.xml` when missing | Reshape. Build it in memory only and never write it into the input folder. | (with M1) |
| M3 | Use the synthesized manifest for pairing | Shrink to a test. Pairing already ignores the manifest. | ½ |
| G0 | *(new)* Source spans | Add. One shared mechanism to point back at the export's XML. G1 needs it, and G2 and G4 can use it. | 1 + spike |
| G1 | Raw step XML per script step | Keep. Scrubbing is the hard part. | 1–2 |
| G2 | Theme styles | Keep. Structured metadata, with CSS through G0 or a field (decision G2-D1). | 1 |
| G3 | Custom menu and menu set UUIDs | Keep. Small. | 1 |
| G4 | Layout object geometry and styles | Keep. The gap is larger than the published text suggests. Split it. | 2 |
| G5 | External data source details | Shrink. The model is already complete; the only gap is in entities.json (done in C1). | ½ |

---

## 3. Units

### F0. Fixtures first

**Why.** No committed sample has a custom menu set (the split sample's `FileA_CustomMenuSetCatalog.xml` is empty). Our only styled layouts, menu sets and real step shapes with `UUID`/`DDRREF`/`OwnerID` children are in `samples/has_indirection/`, which is client data and gitignored. There are no golden JSON tests, and the committed `samples/has_restricted_access_to_scripts/EverythingBagel_docs/` output is stale: its references.json has no `via`/`siteDocId`.

- [x] Fixture solution: an FM26 (26.0.3, SaXML 2.3.0.0) `EverythingBagel.fmp12` plus an `Empty.fmp12`, committed under **`samples/by_type/`** (2026-10-21):
    - `whole/EverythingBagel.xml`: one file, 356 KB, UTF-8, CR+LF
    - `split_catalogues/`: the same file as split catalogs, plus Summary.xml
    - `second_file/`: EverythingBagel and Empty, both split, plus a real two-file Summary.xml
- [x] Froze the stale `EverythingBagel_docs/*.json` (from `samples/has_restricted_access_to_scripts/`; it has no `via`/`siteDocId`) as `tests/fixtures/contract_v0/`. The source folder is gitignored (`*_docs/`), so this copy is the only versioned one.

**What `samples/by_type/whole/EverythingBagel.xml` covers**

| Need | Present | Notes |
|---|---|---|
| Scripts and steps | Yes | 2 scripts, 209 steps: **one of every step type** (`OneOfEverything`), with `# (comment)`, If/Else and Set Variable. Every step has `DDRREF` and `OwnerID` children, the real shape Q11 asks about. |
| Themes | Partly | **One** custom theme, `Vibrant Custom`. It has `baseName="com.filemaker.theme.vibrant"` and `baseVersion`, so custom themes *do* carry their base on `<Theme>`. There's no `defaultTheme` attribute and no second theme, so default-theme selection can't be tested. |
| Layout `LocalCSS` | Yes | 16 objects |
| Layout objects | Yes | Portal, button bar, 2 popovers, 4 buttons, 5 `IconData`, 26 `findMode` |
| Field display styles | Yes, but **numeric** | `Display Style="0|1|2|6"`, not `dropDown`/`popUp`. G4a needs a number → name map (Q15). |
| Custom menus | Yes | 25 menus (24 bracketed standard copies plus `Custom Custom Menu`) |
| Menu set | Yes | `Custom Menu Set` id 2 with `<UUID>` |
| File default menu set | Yes | Catalog-level `CustomMenuSetReference` → `[Standard FileMaker Menus]` |
| Menu set on a layout | **No** | The layout uses `[File Default]` with `UUID=""`. A step parameter also references the standard set. |
| External data sources | Yes | `Empty` (FileMaker, `file:Empty` + `fmnet:/127.0.0.1/Empty`) and `odbc_test` (ODBC) |
| Multi-file pairing | Yes | In `second_file/`, the `Empty` data source should pair with `Empty.fmp12` by path |

Gaps that are still open. Each is optional; add it when its unit needs it:
- [ ] a second theme, with one marked `defaultTheme="True"` (G2)
- [ ] a layout with its own custom menu set (G3)

Done when the fixtures are committed and `uv run pytest` still passes: 1,045 passed, 13 skipped on 2026-10-21.

---

### C1. Versioned contract

**Today.**
- `write_split_json` (`render/json/writer.py:86-113`) writes `entities.json` (11 maps, `{docId: entity}`), `references.json` (a bare array of `ReferenceRecord`), `backlinks.json` and `external-references.json`.
- The JSON files carry three unrelated versions:
    - `external-references.json` has `schemaVersion: "1.0.0"` (`writer.py:19`).
    - `model.json` has `DocumentModel.schema_version = "0.5.0"` (`model/document_model.py:35-37`).
    - The package is `0.6.2`.
- `rename-check` compares versions as strings (`cli.py:787`), so `"0.10.0" < "0.5.0"`.
- `render` and `--no-include-json` skip the split JSON (`cli.py:611-662`).
- `external-references.json` and `model.json` embed the absolute input path (`source.fileName`, `cli.py:1196`).

**How docIds behave today** (`normalize/ids.py`). These rules go into the contract because readers depend on them:
- Format: type prefix plus name, `strip()` only, case-sensitive.
    - `field:<Table>::<Field>`
    - `scriptStep:<script>:<NNNN>` (positional)
    - `layoutObject:<layout>::<id>`
    - local variables `variable:<scriptName>::$x`
- Relationship names are synthesized as `<leftTO>__<rightTO>`, else `rel_<id>`.
- Duplicate names: only layouts, scripts and file references are disambiguated, as `name (#id)`. For other types a duplicate silently overwrites (`normalize.py:199-222`).
- Mixed id forms:
    - Scoped ids (`<fileUuid>/<docId>`, `file:<name>/…`, provisional `ds:<uuid>/…`) sit next to unscoped ids inside entity fields.
    - Batch backlinks add a third form, `xfile:<folder>/<docId>` (`batch/links.py:137-141`).
    - The `ds:` scopes are never rewritten to the real file UUID after pairing.

#### C1a. Shape decisions and consumer check (session 1, mostly writing)

- [ ] Grep H and `afm/` for any read of `entities.json`, `references.json`, `backlinks.json` and `external-references.json`. The breaking changes below assume there are none.
- [ ] Decide the contract's scope. **Proposal:** one contract version shared by `entities.json`, `references.json`, `backlinks.json` and `external-references.json`. `model.json` stays internal and keeps its own `SCHEMA_VERSION`.
- [ ] Decide the envelope. **Proposal:** every contract file becomes an object:
  ```json
  { "schemaVersion": "1.0", "generator": {"name": "fm-saxml-converter", "version": "0.7.0"},
    "source": {"fmpFileName": "...", "fileUuid": "...", "fileMakerVersion": "...", "saxmlVersion": "2.3.0.0"},
    "...": "payload" }
  ```
  Under this envelope references.json's payload goes under `references`, and backlinks' under `backlinks`.
  - `source` has no absolute path; the input file name is enough.
  - `generatedAt` is left out so output is byte-reproducible (Q6).
- [ ] Decide what to do about the docId instabilities:
    - Document positional step ids and name-based ids as they are.
    - Make silent duplicate overwrites a model warning: does FileMaker ever allow duplicate table, TO, value list or custom function names? Verify; Q5.
    - Recommendation: don't rewrite `ds:` scopes in 1.0. Add a `resolvedScope` on pairing in a 1.x minor.

#### C1b. Complete `entities.json` (session 2)

- [ ] Add the missing maps: `accounts`, `extendedPrivileges`, `customMenus`, `customMenuSets`, `themes`, `fileReferences`, `variables`, `externalDataSources`, `indirectionSites`.
- [ ] Add `fileOptions` and `graphNotes` as top-level non-map keys.
- [ ] Drive the list from `EntityMaps`' fields instead of the hardcoded list at `writer.py:89-101`, so a new entity type can't be left out again.
- [ ] Scrubbing: accounts and variables are already scrubbed in the model. Confirm `_guard_output` covers the new keys (`cli.py:422`).
- [ ] Measure the size change on NEXUS (33 MB XML) and DGC_UAT (218 MB). Record it here.
- [ ] Test: every `targetDocId` in references.json either exists in entities.json, is scoped external, or has confidence `unresolved`.

#### C1c. Envelope and versions (session 3)

- [ ] Add a `contract.py` module with `CONTRACT_VERSION = (1, 0)` and `parse_version("1.0") -> (1, 0)`. Fix the string comparison at `cli.py:787` to use it (with the model's own version).
- [ ] Wrap all four files as decided in C1a. `external-references.json` moves from its own `1.0.0` to the shared contract.
- [ ] Write the split JSON from `render` too, or say in the contract that only `build` produces it (decision).
- [ ] Remove the absolute input path from `external-references.json`.

#### C1d. Upgrade chain (session 4)

- [ ] Add `contract_migrations.py`: an ordered registry `{(0, 0): upgrade_0_to_1, …}` that works on plain dicts in memory, chained, and returns the current major.
- [ ] Rules:
    - A file with no `schemaVersion` (a bare array, or entities without an envelope) counts as **0.0**.
    - A minor difference reads as-is, and missing keys take Pydantic defaults.
    - A newer major fails with `ContractVersionError("docs written by schema 2.x; this fm-saxml reads up to 1.x — upgrade fm-saxml")`.
- [ ] Fixture test: load `tests/fixtures/contract_v0/` (from F0), upgrade it, and validate against the 1.0 models.
- [ ] Fixture test: a synthetic `"schemaVersion": "1.9"` with an unknown key loads and ignores the key. A `"2.0"` fails with the message above.

#### C1e. Contract document and golden test (with C1d or a 5th session)

- [ ] Write `docs/contract.md`:
    - the collections, required keys per entity, and the docId rules (C1a)
    - the scoped-id forms and what `confidence` values mean
    - the version policy (what is minor and what is major)
- [ ] Generate a JSON Schema per file from the Pydantic models (`model_json_schema`) into `docs/contract/schema-1.0/`. Add a test that fails when the committed schema is stale.
- [ ] Golden test: build F0's sample twice and assert the JSON is byte-identical. Store a golden copy and diff against it, with an `--update-golden` flag.

**Unknowns.** Whether H or agentic-fm parse these files today (C1a). Size growth on big files (C1b). Whether duplicate names occur in real exports (Q5).

**Done when** a 1.0 build validates against the committed schema, the v0 fixture upgrades, and a 2.0 doc fails clearly.

---

### C2. Python reader API

**Today.** `fm_saxml/__init__.py` holds only `__version__`. `model/__init__.__all__` re-exports 20 classes but leaves out `LayoutObjectEntity`, `AccountEntity`, `VariableEntity`, `ExternalTarget` and `IndirectionSite`. The pipeline lives in private `cli._run_pipeline` / `_analyze`. The distribution is `fm-saxml-converter`, the import name is `fm_saxml`, Python 3.11 or later.

#### C2a. API shape and single-file loading (session 1)

- [ ] Write `fm_saxml/api.py` and re-export it from `fm_saxml/__init__.py`:
  ```python
  docs = fm_saxml.load(docs_dir)          # -> SolutionDocs (one file) or BatchDocs (a batch root)
  docs.source, docs.schema_version
  docs.entities.scripts["script:Foo"]     # typed Pydantic entities, same classes the converter uses
  docs.references                         # list[ReferenceRecord]
  docs.refs_from(doc_id) / docs.refs_to(doc_id)
  docs.find("script", "foo")              # case-insensitive name lookup, returns all matches
  ```
- [ ] Run C1d's upgrade chain on load and raise `ContractVersionError` / `DocsNotFoundError` with paths in the message.
- [ ] Performance:
    - Measure `model_validate` over NEXUS/DGC entities.json.
    - If it takes more than ~2 s, load collections lazily: validate on first access to `docs.entities.<collection>`.
    - Record the numbers here.
- [ ] Complete `model.__all__` and mark the public surface in `docs/contract.md`.

#### C2b. Batch loading and consumer ergonomics (session 2)

- [ ] `load(batch_root)` reads the root catalog from C3 and returns `BatchDocs` keyed by file name, plus `.resolve(scoped_doc_id)` across files. This covers the `<fileUuid>/`, `file:`, `ds:` and `xfile:` forms.
- [ ] Decide whether `diff`, `rename-check` and `render` move to `load()` as well, as dogfooding. Recommendation: yes for `rename-check`, later for the rest.
- [ ] Dependency weight. agentic-fm will `pip install fm-saxml-converter`, which pulls lxml, typer, rich, jinja2 and orjson. Decide whether that's acceptable or whether to make a `[cli]` extra (Q7).

**Unknowns.** agentic-fm's Python floor and how it pins this package. Whether lazy validation is needed.

---

### C3. Output location

**Today.**
- `build` writes to `--out`, or else `<stem>_docs` / `<folder>_docs` next to the input (`cli.py:263-265, 324`).
- A batch writes `<root>/<safe_slug(file)>/` per file, and reserves `reports` and `_viewer` (`cli.py:388-470`).
- `--force` **wipes** the whole folder (`cli.py:1085-1150`).
- There's no config file. The only environment variables are `FM_SAXML_SCRUB_SALT`, `FM_SAXML_DEBUG` and `FM_SAXML_NO_UPDATE_CHECK`.
- `exports/` appears nowhere in this repo; it's agentic-fm's convention.
- A `.fm-saxml` marker file is written to the output root, but it carries no data.
- A batch root has no JSON listing its files.

- [ ] **Root catalog.** Write `docs.json` at every output root:
    - single file: `{schemaVersion, kind: "single", file: {...}}`
    - batch: `{schemaVersion, kind: "batch", files: [{name, fmpFileName, fileUuid, folder, saxmlVersion}], synthesizedManifest: bool}`

  It replaces scanning subfolders or parsing `_viewer/manifest.js`. Fold the `.fm-saxml` marker into it, or keep both (decision).
- [ ] **Config key.** Use one environment variable, `FM_SAXML_DOCS_ROOT`, plus `--docs-root`. If it's set, `build` without `--out` writes to `<root>/<solution-slug>/`. Here "solution" means the batch folder name for a folder, or the file stem.
    - The FileMaker export script (Phase 3) writes into timestamped folders, so the output path must **not** follow the input folder. It must be stable per solution.
- [ ] **Lookup function.** Add `fm_saxml.find_docs(solution: str, root: Path | None = None) -> Path`:
    - case-insensitive, slug-aware
    - also matches a file name inside a batch's `docs.json`
    - with no match, the error lists the solutions it found
- [ ] **Safe rewrite.** Repeated `/convert` calls will rebuild in place while readers may be open.
    - Build into `<out>.tmp-<pid>`, then swap.
    - On Windows, `os.replace` on a directory with open handles fails, so either rename the old folder aside first and retry, or document the limit (test on Windows).
- [ ] State in the README and the contract that converted output is local and never committed. Agentic-fm's `.gitignore` is an `[afm]` follow-up.

**Unknowns.** Whether agentic-fm wants to keep `exports/<name>_docs` or adopt `FM_SAXML_DOCS_ROOT` (Q8). Windows directory swap with open handles.

---

### M1 + M2. Manifest when FileMaker's is missing (one session)

**Today.**
- The manifest is detected by its root element (`FMPReport type="Summary"`), not its file name (`parser/input_scan.py:83-84`).
- `_read_manifest` reads `CreationDate`/`CreationTime`, `File/@name`, `File/@path` (the server host for hosted files, the local folder for local ones) and `XML/@path` (`input_scan.py:205-222`).
- It drives:
    - console warnings (`cli.py:520-529`)
    - `--strict` (`cli.py:431-432`) and `validate` (`cli.py:736`)
    - the "XML Created At" and "Exported From" rows in index.md (`batch_index.md.j2:17-18`)
    - "Not Converted" rows
    - the "Not Listed in Summary.xml" section of `Reports/batch-summary.md`
- **There's no test for a folder without a manifest.**

**What can be derived from the exports**

| Manifest field | Derivable? | From |
|---|---|---|
| `File/@name` | Yes (v2) | root `File` attribute. v1 exports have none, so use the XML stem plus `.fmp12`. |
| `XML/@path` | Yes | local path (a split folder ends with a separator) |
| `version`, `membercount` | Yes | root `version` (it can differ between files) and the count |
| `CreationDate`/`Time` | **No** | No export time exists in SaXML. File mtime is the only proxy, and it's lost on copy or unzip. |
| `File/@path` (host / folder) | **No** | Not in the export |

**What's wrong with the published version.**
- A manifest built from the exports always matches them, so the completeness checks it exists for never fire.
- Writing it into the input folder breaks things:
    - A second manifest is skipped and counted as "Not Converted", and `--strict` fails (`input_scan.py:193-194`, `cli.py:433-434`).
    - Input folders may be read-only.
    - `build` refuses to run when given a Summary.xml as its input.

**Proposed shape.**
- [ ] Write the spec in `docs/manifest.md`, using the table above and the rules below.
- [ ] Synthesize in memory only: `Manifest(synthesized=True, created=None, hosts=[])` when the input is a folder with two or more exports and no manifest.
    - Never write it to disk, and never show an mtime as "XML Created At".
    - index.md and batch-summary show "Summary.xml: not present (built from N exports)".
    - `docs.json` (C3) carries `synthesizedManifest: true`.
- [ ] **Decide Q4: should the FileMaker export script write the manifest?** The script knows which files were open, `Get(HostName)`, the file paths and the export time. If it writes a FileMaker-shaped `Summary.xml` (marked with an extra `generator="agentic-fm"` attribute, which our parser ignores), then the completeness checks and the host and time rows work again for scripted exports.
    - If yes, the `[saxml]` work is to accept and label that attribute. The `[fm]` work goes to Phase 3.
- [ ] Tests:
    - a folder with no manifest (this closes today's gap)
    - single-solution folders with no manifest
    - the label appears, with no "XML Created At" row
    - `--strict` passes
    - a v1 export in a folder with no manifest

**Unknowns.**
- Whether FileMaker writes failed files into `membercount`.
- Whether `CreationTime` depends on the locale.
- What to write as `version` when files differ (FileMaker never produces such a mix).

### M3. Pairing with a synthesized manifest (half a session)

- [ ] Test: build `samples/multi_file_export/SaXML_no_separate_catalogue/` with and without its Summary.xml, and assert the Data Source Pairings table and the "Cross-file references: N of N resolved" line are identical.
- [ ] Add one sentence to `multi_file_saxml.md`: pairing never uses the manifest.

---

### G0. Source spans: a pointer back into the export (spike + 1 session)

G1 needs this, and G2 and G4 can reuse it. Today `SourceXmlInfo{path, line}` exists (`model/entities.py:45-51`), but `line` is never filled and `path` is a non-unique tag chain (`parser/extractors/_helpers.py:87-96`).

**Facts measured with lxml 6.1.0 / libxml2 2.11.9.**
- `sourceline` works past 65535. The comment at `scrub/xml_writer.py:390-391` is stale for this version.
- **But it's one line off from `grep -n` on NEXUS and DGC_UAT**, probably because of bare CRs inside text.
- lxml gives no byte offsets.
- `scrub/xml_writer.py:393-399` (`_patch_source`) already finds element k's start tag by scanning with `_MARKUP_RE`. The same scan can give char offsets.
- The FM22 exports (EverythingBagel at the root, NEXUS, disRenewalUniverse) are **UTF-16LE with a BOM**. The FM26 samples are UTF-8.

**Spike** (time-boxed, answers Q9):
- [ ] On F0, NEXUS and DGC_UAT, compute `(start_byte, end_byte)` per `StepsForScripts/Script` and per `Step`:
    - decode, scan start and end tags, then map char offsets to byte offsets per encoding
    - slice, parse the slice and compare it with the lxml subtree (tag, attributes, text)
- [ ] Record the cost per GB and the extra memory. The 218 MB DGC_UAT is the stress case.

**Build:**
- [ ] Add `SourceSpan{file: str, start: int, end: int}` to the model.
    - `file` is relative to the input root, and points at the fragment file for split catalogs.
    - Add an `exportFingerprint{size, sha256}` per input file, in `docs.json` / entities `source`.
- [ ] Fill spans only for the entities that need them: scripts and steps (G1), themes (G2-D1), layouts and layout objects (G4). They go behind the contract as a 1.x minor addition. If 1.0 hasn't shipped yet, put them in 1.0.
- [ ] Add a reader, `docs.raw_xml(doc_id) -> bytes`:
    - It finds the export under the recorded input root (or an override) and checks the fingerprint.
    - It fails clearly: `export not found at …` or `export changed since conversion (sha256 mismatch); reconvert`.

**Unknowns.**
- Whether spans survive the Phase 3 retention policy (are timestamped export folders kept?).
- Whether to store the input root as an absolute path, a privacy cost, or require the caller to pass it (Q10).

---

### G1. Raw step XML (1–2 sessions, after G0)

**What agentic-fm needs** (`afm/agent/scripts/fm_xml_to_snippet.py`):
- `translate_script` reads the first `ObjectList` → `Step` (`:345-365`).
- Control-flow steps read `ParameterValues/Parameter[@type]`, `Comment/@value`, `Boolean[@type=Collapsed]`, `List/@name`, `Variable/Name/@value` and `value/Calculation/Calculation/Text` (`:129-272`).
- Every other step goes through `saxml_read.read_saxml_step`, which decodes the whole raw `<ParameterValues>` subtree (`:312-338`).
- So the model's display-oriented `params` aren't enough. It needs the subtree.

**What we keep** (`parser/extractors/scripts.py:136-198`, `ScriptStepEntity` `entities.py:366-384`):
- kept: step id, name, enabled, text, refs, calcs, display params
- **not kept:** step `<UUID>`, `<Options>`, `@hash`, the Parameter type tree, or any raw XML

**Scrubbing is the hard part.**
- Scrubbing runs on parsed records (`cli.py:1194-1199` → `scrub/engine.py:91-94`), so a slice of the original export is **unscrubbed**.
- The safe path that already exists is `scrub_xml_file` / `_Rewriter` (`scrub/xml_writer.py:83-127, 259-281`). It covers calcs, ChunkList, StepText and comment steps, and drops `hash` from changed elements.

Decision G1-D1, where the scrubbed bytes come from:

| Option | How | For | Against |
|---|---|---|---|
| A | Read on demand: slice the original, then run `_Rewriter` over the fragment with the run's salt and finding map | No extra files, follows "No extra files" | Needs the same placeholder numbering as the build (needs `FM_SAXML_SCRUB_SALT` or a stored finding map), and the rewriter runs per call |
| B | At build, also write a scrubbed copy of the export (`fm-saxml scrub` output) and point spans at it | Byte-exact, scrubbed once, simple reader | A second copy of the export (it can be large), against the "no extra files" principle |
| C | Store scrubbed step XML in entities.json | One file | Bloats entities.json, duplicates content |

**Recommendation:** B when scrubbing is on, with spans pointing into the scrubbed copy. Otherwise the original. Raise it with the harness owner, because it bends "No extra files".

- [ ] Add a `uuid` field to `ScriptStepEntity` (cheap, and useful for diff).
- [ ] Implement G1-D1.
- [ ] Spans per script (one `StepsForScripts/Script` element) **and** per step. The script span feeds `fm_xml_to_snippet.py` directly; the step spans allow partial pastes.
- [ ] Test: for F0, `raw_xml("script:…")` parses, contains every `Step` in order, and holds no secret seeded in a step calc.
- [ ] Hand-off check with agentic-fm: run `fm_xml_to_snippet.py` on a raw script from F0 and DGC_UAT. Real steps carry `UUID`/`DDRREF`/`OwnerID` children that its fixtures leave out (Q11).

---

### G2. Theme styles (1 session)

**What agentic-fm needs** (`afm/agent/scripts/extract_theme.py`):
- theme `@Display`, `@id`, `@name`, `@defaultTheme`
- the `CSS` CDATA
- `Metadata/namedstyles/*` (class → display name), `layoutbuilder/*`, `colorpalette/*`, `charting/*`
- it also scans layouts for `LocalCSS` (`:539-581`)
- it writes `theme.css`, `theme-web.css`, `theme-manifest.json` and `theme-classes.json`

**What we keep:** `ThemeEntity` has name, id, display name, group, default flag and modified (`entities.py:624-635`; extractor `parser/extractors/themes.py:11-30`). The theme UUID, CSS, Metadata and Image are dropped. `LayoutEntity.theme` keeps only the name and drops `@Base` and the UUID (`layouts.py:85-90`).

**In the export:** `FileA_ThemeCatalog.xml:10-5907` has `<Theme Display Group version locale platform name defaultTheme id>`, then `<Image>` (a base64 thumbnail), `<CSS>` (about 5,700 lines), then `<Metadata>` (`namedstyles`, `colorpalette`, `layoutbuilder`, `charting`, `colorScheme`). Built-in themes have no `baseName`. Custom themes do: `samples/by_type` has `<Theme … baseName="com.filemaker.theme.vibrant" baseVersion="6">`. Layouts also carry it as `LayoutThemeReference @Base`. Keep `base_name` and `base_version`.

- [ ] Add structured fields: `uuid`, `version`, `platform`, `locale`, `named_styles: dict`, `color_palette: dict`, `layout_builder: dict`, `charting: dict`, `color_scheme`. Leave out `Image`.
- [ ] Decision G2-D1, CSS:
    - (a) a `css` field in entities.json, about 200–400 KB per theme
    - (b) a G0 span read through `raw_xml`
    - Recommendation: (b). Keep entities.json small; themes rarely change.
- [ ] Layouts: keep `LayoutThemeReference @Base` and its UUID.
- [ ] Scrubbing: CSS and palette data carry no credentials. Exclude them from detectors explicitly so they can't cause false positives, and say so in `docs/contract.md`.
- [ ] Theme Markdown page: list named styles and palette swatches. Optional; decide in-session.
- [ ] Test: F0's two themes, the default flag, a named style seen on a layout, and CSS that loads through `raw_xml`.

---

### G3. Custom menu and menu set UUIDs (1 session)

**What agentic-fm needs** (`afm/agent/scripts/install_menus.py`). Today it takes UUIDs from **clipboard snapshots** (`agent/sandbox/custom_menus.xml`, `custom_menu_set.xml`), because its docstring says they're "not available in xml_parsed" (`:20-21, 45-73`):
- per-menu ID and UUID
- `FM_FILE_NAME`, `FM_FILE_UUID`
- `CustomMenuCatalog` UUID, `CustomMenuSetCatalog` UUID, the menu set UUID and ID
- the standard menus `CustomMenuSetReference @UUID`

**What we keep:** menus (`entities.py:594-609`) have name, id, base menu, install condition, mode flags and items. Item `id` is read but dropped (`custom_menus.py:72-108`). Sets have name, id and menu docIds. **No UUIDs anywhere.** File name and UUID are already in `SourceInfo`.

**In the export:**
- `FileA_CustomMenuCatalog.xml:58`: catalog `<UUID>`
- `:60-61`: `<CustomMenu name id><UUID>`
- DGC_UAT:
    - `:177752`: set catalog `<UUID>`
    - `:177754`: file default `CustomMenuSetReference @UUID`
    - `:177756-57`: a set `<UUID>`
    - `:237483`: a layout's `[Standard FileMaker Menus]` reference `@UUID`

- [ ] Add `uuid` to `CustomMenuEntity`, `CustomMenuItem` (plus `id`) and `CustomMenuSetEntity`.
- [ ] Add catalog UUIDs (`customMenuCatalogUuid`, `customMenuSetCatalogUuid`) and the default set reference `{name, id, uuid}` to `fileOptions` (or `SolutionInfo`; decide which).
- [ ] Keep the UUID on layout `menu_set` references.
- [ ] Test on F0 (it needs a non-empty menu set; see F0).
- [ ] Verify with a person on FileMaker that the clipboard `FMObjectTransfer` UUIDs equal the SaXML ones (Q12). If they do, agentic-fm can drop its clipboard snapshot step.
- [x] Verify whether the `[Standard FileMaker Menus]` UUID is a constant across files (Q13): it isn't. Read it per file.

---

### G4. Layout objects (2 sessions)

**What agentic-fm needs** (`afm/agent/scripts/layout_to_summary.py`):
- layout `@width`, TO and theme
- parts: `Definition @type`, `@size`, `LocalCSS`
- objects:
    - `@type`, `@name`, `@key`, `Bounds` (ints)
    - `LocalCSS @name/@displayName` plus visuals parsed from its CSS (background, gradient, text colour, radius, font size, font family)
    - field `Display @Style`, value list, placeholder, `StyledText` text
    - button label, `IconData`, script plus parameter, tooltip
    - portal `Options @show`, button bar `Select`
    - `Hide @findMode`, conditional formatting count, triggers, nested objects
- The layout-design skill also reads **raw** layout XML as examples for generating new layouts (`SKILL.md:180-193, 266`).

**What we keep** (`parser/extractors/layouts.py`):
- layouts: id, name, uuid, TO, theme name, folder, parts, menu set, triggers, calcs
- parts: type, name, height, break field, object count
- objects: id, name, uuid, type, kind, part, bounds (floats), field, value list, raw text, button script and kind, portal details, triggers, role-tagged calcs

**Not kept:**
- layout: `@width`, `GridStyle`, `ClientType`, `Options`, theme `@Base`/UUID
- parts: `Definition` kind/absolute, part `LocalCSS`, and part `options` (**a bug**: it's extracted at `layouts.py:130-154`, but `LayoutPart` has no field for it, `entities.py:263-272`)
- objects: `LocalCSS`, `Display @Style`, `Hide @findMode`, `<Options>`, `IconData`, `StyledText` button labels

#### G4a. Structure and geometry (session 1)

- [ ] Fix the dropped part `options`.
- [ ] Add layout `width`, `grid_style`, `client_type` and `options`, plus part `definition_kind`.
- [ ] Add object `display_style` (dropDown/popUp/…), `hide_in_find`, `options` (raw bitfield int plus decoded flags where known), `label_text` (StyledText button labels) and `icon_type` (type only; the SVG stays in raw XML).
- [ ] Bounds: confirm the unit (Q14). DGC_UAT has values like `top="2754"`, and our docstrings say both "pixel" and "points". Document it in the contract.
- [ ] `@key` vs `id`: `layout_to_summary.py:514` reads `@key`, but SaXML objects carry `id`. Note it for the Phase 2 port. No model change.

#### G4b. Styles and raw layout XML (session 2)

- [ ] Add `local_css: {name, display_name, css}` on objects and parts.
- [ ] Decide whether to also parse the visuals agentic-fm derives (colour, radius, font) into fields, or leave that to the port (decision G4-D1). Recommendation: keep `css` raw, and let a helper in the reader API parse it so the logic lives in one place.
- [ ] G0 spans on layouts and layout objects, so layout-design can fetch real layout XML through `raw_xml`.
- [ ] Field-by-field comparison: run `layout_to_summary.py` on F0 through the exploder (Q1) and diff its output against what the model now holds. Every remaining gap is either fixed here or noted as "not needed" with a reason. That table also answers Phase 2's "port or retire" question.

---

### G5. External data source details (half a session)

**What agentic-fm reads** (`afm/agent/scripts/analyze.py`):
- `analyze_integrations` lists data source file stems (`:1941-1945`).
- `detect_multi_file` reads `@name`, `@id`, `@type` and `UniversalPathList` split on CR/LF. It parses `file:`/`fmnet:` and flags `$var` paths (`:1998-2081`).

**What we keep:** `ExternalDataSource{name, fmp_id, uuid, type, paths[]}` (`document_model.py:60-69`), with paths split per line or `<Location>` (fixed in fix_gaps2). That already covers everything `analyze.py` uses.

- [ ] Add `externalDataSources` to entities.json (done in C1b; tick both).
- [ ] Add `pairedFile` / `pairing.match` from batch linking to each data source in a batch build. agentic-fm's `data_source_map` recomputes this by path and base-table overlap (`:2097-2160`); we already compute it in `batch/links.py`.
- [ ] Note for Phase 2: H's `data_sources.index` is never read by `analyze.py` (H:360-367). The port reads the model, so nothing to fix here.

---

## 4. Order and dependencies

```
F0 ─┬─ C1a → C1b → C1c → C1d → C1e ─┬─ C2a → C2b
    │                               └─ C3 (docs.json needs the envelope)
    ├─ M1+M2 → M3                         (independent; can run any time)
    ├─ G5 (with C1b) · G3                 (small; after C1b)
    └─ G0 spike → G0 → G1 · G2 · G4b      (G4a can start after F0)
```

Suggested release cut: **0.7.0 = contract 1.0** (F0, C1, C2a, C3, M1–M3, G3, G5, G4a). **0.8.0 = raw XML** (G0, G1, G2, G4b, C2b). That makes Phase 2's ports of trace.py, menus and data sources possible after 0.7.0. The snippet, theme and layout-design ports need 0.8.0.

About 17–20 agent sessions in total.

## 5. Open questions

| # | Question | Blocks | Who |
|---|---|---|---|
| Q1 | Can someone run fm-xml-export-exploder on a Mac against F0's export, so we have real `xml_parsed/` output (file shape, `@key`, kept `UUID`/`hash`/`DDRREF`)? | G4b comparison, Phase 2 golden fixtures | colleague with a Mac |
| Q2 | Do H or agentic-fm parse `entities.json`/`references.json` anywhere today? | C1 (breaking) | C1a grep |
| Q3 | One contract version for all four files, or one each? (Proposal: one.) | C1c | us |
| Q4 | Should the FileMaker export script write a Summary.xml (host, time, file list)? | M1 scope, Phase 3 `[fm]` | harness owner |
| Q5 | Can tables, TOs, value lists or custom functions have duplicate names in a real export? Today they silently overwrite. | C1a docId rules | check FileMaker |
| Q6 | Drop `generatedAt` from contract files to make them byte-reproducible? | C1e golden test | us |
| Q7 | Is the full CLI dependency set acceptable inside agentic-fm, or do we add a `[cli]` extra? | C2b | harness owner |
| Q8 | `FM_SAXML_DOCS_ROOT` or agentic-fm's `exports/<name>_docs`? | C3 | harness owner |
| Q9 | Are byte spans reliable on UTF-16 and CR-heavy exports, and what do they cost on 218 MB? | G0 | spike |
| Q10 | Store the export root as an absolute path in docs, or make the reader pass it? | G0 | us |
| Q11 | Does `saxml_read` handle real steps with `UUID`/`DDRREF`/`OwnerID` children? | G1 hand-off | afm test |
| Q12 | Are the clipboard `FMObjectTransfer` menu UUIDs the same as SaXML's? | G3 value | person on FileMaker |
| Q13 | ~~Is the `[Standard FileMaker Menus]` set UUID a constant?~~ **No:** it's `2C8E1610-…` in by_type/EverythingBagel and `129DFB31-…` in DGC_UAT. It's per file, so it must be read from the model. | — | answered 2026-10-21 |
| Q15 | What does each `Display @Style` number mean (0, 1, 2, 6 seen)? agentic-fm expects names (`dropDown`, `popUp`). | G4a | FileMaker test layout: one field per style |
| Q14 | Bounds unit (points vs pixels). | G4a contract text | FileMaker docs or a test layout |
| G1-D1 | Where scrubbed raw XML comes from (on-demand rewrite, scrubbed copy, or inline). | G1 | us + harness owner |

## 6. Brainstorm (add freely)

- `docs.raw_xml()` could back a WebMCP tool (`get_raw_xml`) so a browser agent gets paste-ready XML without the CLI.
- A `fm-saxml snippet <docs> "script:Foo"` command would make G1 useful on its own, before agentic-fm's port.
- Stable step ids: once step UUIDs are kept (G1), `scriptStep:<script>:<uuid>` could become a 2.0 docId. For now it stays positional.
- `docs.json` could carry a coverage summary, so Phase 7's `doctor` can report "converted with schema 1.0, 1,824/1,824 checks".
