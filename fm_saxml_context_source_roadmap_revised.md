# fm-saxml as the single context source — roadmap (revised)

Date: 2026-10-21. Revises `fm_saxml_context_source_roadmap.md` to follow the tentative update of the parent roadmap.

Sources:
- Phase 1 of "FileMaker Agentic Dev on Windows and Mac: Roadmap (tentative update)" (`FileMaker Agentic Dev on Windows-Mac - New Roadmap (tentative update).md`), only the units marked `[saxml]`.
- That update revises the published "FileMaker Agentic Dev on Windows — Roadmap" ([doc](https://claude.ai/artifact/GkyhUeLsp3iH88dHTsxpbh)). It is **not yet accepted by the owner**, so section 0 lists what depends on its open points.

Baseline: `master` at `be5d247` (v0.6.2).

Phase 1's outcome, unchanged by the update: *fm-saxml's model holds everything agentic-fm's tools need, including multi-file exports made by a script, so nothing downstream needs the exploder's XML.*

This file goes below the surface of each unit: what the code does today (with file:line), the decisions to make, the work broken into sessions where needed, and the unknowns. Paths are relative to `src/fm_saxml/` unless they start with a repo name. `afm/` means `dis-custom-agentic-dev-harness/tools/agentic-fm/`. `H` means `dis-custom-agentic-dev-harness/tools/saxml_to_agentic_context.py`.

## Status

F0 done (fixtures in `samples/by_type/`, v0 contract fixture frozen in `tests/fixtures/contract_v0/`). **C1 done 2026-10-21**: C1a–C1c in commit `db69023`, C1d–C1e uncommitted (1,093 passed, 13 skipped). **C2 and C3 done 2026-10-21** (uncommitted; 1,127 passed, 13 skipped). Next: M1–M3, G3, G5, G4a, D1 (the rest of the 0.7.0 cut). H is pinned to fm-saxml **0.6.2** (bumped and pushed 2026-10-21; download, build, adapter, `trace.py build` and its adapter tests all passed). **Before H bumps its pin to 0.7.0, it needs the references.json change in C1a.** The Claude Doc's v2 tab marks the contract item done (C1a–C1e) and corrects its "nothing reads these files" line. Nothing else started. Research done 2026-10-21 (three read-only surveys of this repo, agentic-fm and the harness adapter). Revised the same day for the tentative parent update. The revision added a read of `afm/.cursor/skills/menu-lookup/SKILL.md`. **Q1 answered 2026-10-21:** a colleague ran agentic-fm's real Explode XML path on a Mac (committed as `samples/EverythingBagel_mac_run/`, `3c3c4a8`). Section 1a has what it showed, and it also answers Q12, Q14 and Q15 and most of Q16.

---

## 0. What the tentative update changes here

Only one `[saxml]` unit in Phase 1 changed: **custom menu and menu set UUIDs (G3)**. Its consumer is now the `menu-lookup` skill instead of `install_menus.py`. Every other Phase 1 unit and the Phase 2 `[saxml]` unit (cover analyze.py's profile in Reports/) are word-for-word the same.

The wider changes still reach this file:

| Parent change | Effect here |
|---|---|
| `install_menus.py` is deleted, not ported. `menu-lookup` moves from "Low value" to "Analysis" and gets a rewrite unit in Phase 5. | G3 is rewritten for the new consumer. The new consumer needs more than the old one: UUIDs on the **Markdown pages** as well as in JSON, and the menu's raw XML as a base for edits (G3, Q16). |
| `xml_parsed/` goes away on the Mac too, along with the web viewer. | Nothing in agentic-fm can read the exploder's output after Phase 2. The model must be complete before the exploder path is deleted, on both platforms. Q1 (one real exploder run for golden fixtures) is now urgent: it must happen before that deletion. |
| The web viewer is out of scope (its script-search port is gone). | One less consumer of the reader API (C2) and of script lookup. No unit here shrinks, because the Python ports still need the same data. |
| WSL is not supported in v1. | No effect. None of our units mention WSL. C3's directory swap was already written for native Windows. |
| Old Phase 7 (setup) is now Phase 6. Setup, quick start and pilot now cover the Mac too. | The `doctor` reference in the brainstorm moves to Phase 6. C3's `FM_SAXML_DOCS_ROOT` and `find_docs` must be tested on macOS as well as Windows. |
| Proofkit harness added "After v1". | No unit changes. Proofkit's MCP reads the **live** file (unscrubbed, needs FileMaker open). Our model is the **offline, scrubbed** reading. The Proofkit "who does what" table should say so (brainstorm). |

**Contingent on the owner's open point 1.** The update puts G3 in v1 only because `menu-lookup` stays and needs real UUIDs.
- If the owner accepts a `menu-lookup` that answers only from what the pages already hold, G3 moves to after v1, and so does Q12.
- Until then, this file plans G3 as v1 work, but in the 0.8.0 cut because of its raw-XML part (section 4).

Two small inconsistencies in the update, to raise with its author:
- The WSL out-of-scope note says "see open point 3". WSL is open point 2.
- Open point 1 says the menu UUIDs item moved "from After v1 back to Phase 1". In the published roadmap it was always in Phase 1. Only the feedback file (`Roadmap review - feedback.md`, not in this repo) proposed moving it out. The net change from the published roadmap is the consumer, not the phase.

---

## 1. What the research changed

The published units are mostly right, but six findings change their size or shape:

| # | Finding | Effect on the plan |
|---|---|---|
| 1 | **Nothing reads `entities.json` or `references.json` today.** `diff`, `rename-check` and `render` read `model.json`; webmcp, serve, coverage and batch linking use the in-memory model. | We can fix the JSON shape now with no migration pain inside this repo. **Checked in C1a:** agentic-fm reads none of them, but H reads entities, references and external-references. Only the references.json wrapper breaks H, and only once its pin moves to 0.7.0. |
| 2 | **`entities.json` holds 11 of the model's 18 entity maps.** Missing: accounts, extendedPrivileges, customMenus, customMenuSets, themes, fileReferences, variables, plus externalDataSources, indirectionSites, fileOptions (`render/json/writer.py:89-101`). References point at docIds that the file doesn't contain. | The contract unit must first make the file complete. Two gap units (menus, data sources) are half-solved by that. |
| 3 | **`references.json` is a bare JSON array** (`writer.py:108-111`). | It can't carry `schemaVersion`. Wrapping it is a breaking change, so it must happen in contract 1.0. |
| 4 | **The manifest never takes part in pairing.** Cross-file pairing matches the data source's path against each export's root `File` name (`batch/links.py:157-202`). Summary.xml only feeds warnings, `--strict`, `validate` and two index rows. | "Use the synthesized manifest for pairing" becomes a test, not a change. A synthesized manifest built from the exports always agrees with itself, so its checks never fire. M1–M3 are reshaped below. |
| 5 | **The SaXML export has everything the gap units ask for** (theme CSS and metadata, menu and catalog UUIDs, layout `LocalCSS`, step subtrees). It's the model that drops them. | All gaps are extractor and model work, with no workarounds. |
| 6 | **Under the harness today, agentic-fm's readers have no input at all.** H writes `.index` files and sanitized scripts, but not the `xml_parsed/{scripts,layouts,themes,custom_menus,custom_menu_sets,external_data_sources}` folders they read. This includes the `menu-lookup` skill, which lists and reads `xml_parsed/custom_menus/` and `custom_menu_sets/`. | Phase 2's golden fixtures can't come from the harness. They need the real exploder run once (Open question Q1), and it must happen before the exploder path is deleted on both platforms. |

## 1a. What the Mac exploder run showed (Q1, 2026-10-21)

**The run.** `samples/EverythingBagel_mac_run/`, see its `NOTES.md`.
- Tools: FileMaker Pro 26.0.3, fm-xml-export-exploder 0.6.1, agentic-fm upstream `b2669b6`, all default flags.
- The colleague pasted agentic-fm's "Get agentic-fm path" and "Explode XML" scripts into a copy of EverythingBagel.fmp12 and ran Explode XML. That's the real Save a Copy as XML → `/explode` → fmparse.sh → fmcontext.sh path. trace.py and analyze.py ran afterwards, and every command exited 0.
- His `saxml/EverythingBagel.xml` is the same file as ours except for two differences:
    - it holds the two pasted scripts (ids 3 and 4)
    - **`Has_DDR_INFO="False"`**

I built it with fm-saxml and diffed entities.json against our build.

| # | Finding | Effect on the plan |
|---|---|---|
| 7 | **Scripted exports have no DDR info.** The Explode XML script's Save a Copy as XML writes `Has_DDR_INFO="False"`; ours, from the Tools menu, is `True`. That removes the `DDR_INFO` block (262 `DDRREF`, 52 `ChunkList`). The build still succeeds with the same entity counts and 95 of 96 references, but it loses:<br>- every step's `fmText` (pages fall back to our own step text, which reads differently)<br>- every calc's `chunkRefs` (references fall back to parsing the text, `normalize/calc_refs.py:71`)<br>- the popover title calc (layout object 25)<br>- TO `Empty`'s external base table name, id and UUID, so external-references loses that table | Phase 3's export script must turn DDR info on. The step has an option for it: "Include details for analysis tools" in the dialog, `include_details` in its JSON options (Q17, answered). New unit **D1**: a no-DDR fixture, a warning when `Has_DDR_INFO="False"`, and a coverage check that names what's missing. |
| 8 | **Menu UUIDs: the clipboard and SaXML match** (menu, menu item, both catalogs, set). | Q12 answered. G3a's UUIDs are safe to hand to a paste. |
| 9 | **The clipboard (paste) form isn't the SaXML form.** A copied menu comes wrapped in its catalog (`CustomMenuCatalog` with SortOrder, CustomOrderList and the catalog UUID) plus a `PasteIndexList`. Its action step is in snippet form (`StepText`, no hash), and the item `hash` differs. | Q16 mostly answered: the paste needs the catalog wrapper. Raw SaXML menu XML (G3b) is a **base for conversion**, not paste-ready, like steps for `fm_xml_to_snippet.py`. The SaXML → clipboard conversion is `[afm]` work; G3b serves the raw element plus the catalog UUID. |
| 10 | **The exploder's menu files have no catalog UUIDs and drop item UUIDs and step bodies.** `custom_menus/…/Custom Custom Menu - ID 25.xml` keeps only the menu `<UUID>`; its `Beep` step is an empty `<Step>`. | `menu-lookup` today can't report the two catalog UUIDs its SKILL.md promises. G3a is a strict improvement, not just a port. |
| 11 | **The exploder strips step `<UUID>`, `<OwnerID>` and `@index`**, keeping `@hash` (default mode, not `--lossless`). Exploded scripts have no `DDRREF` either. | Q11 narrowed: `saxml_read` has only ever seen stripped steps. G1's raw XML still carries them. Either confirm `saxml_read` ignores them, or let `raw_xml` return the stripped form (G1). |
| 12 | **Layout objects have no `@key`.** In the exploded layout, `key=` appears only on the 4 library references; objects carry `id`. | Confirms G4a's note: `layout_to_summary.py:514` reads nothing today. Its port must use `id`. |
| 13 | **Display styles and bounds.** `Display @Style` 0 Edit Box, 1 Drop-down List, 2 Pop-up Menu, 3 Checkbox Set, 4 Radio Button Set, 6 Drop-down Calendar, 7 Concealed Edit Box (5 not seen). The clipboard's `displayType` uses the same numbers. Bounds are **points**, identical in SaXML and the clipboard. | Q14 and Q15 answered. G4a can write the name map and the contract text. |
| 14 | **The exploder path is weak where we compare against it.** `trace.py build` found 3 references (our build: 95). fmcontext.sh writes an empty `custom_functions.index` (it reads `custom_function_stubs/`, which 0.6.1 doesn't create) and blank value list names (wrong XPath). No layout summaries are generated by default, so every field and both layouts come out "unused". | Phase 2's golden comparison must check that **ours covers theirs**, not that the two are equal, and record each of these as a known exploder defect, not a regression. |
| 15 | **The exploder keeps whole themes** (CSS, Metadata, Image; 94 KB for `Vibrant Custom`) and whole layouts (`LocalCSS`, `Display`, `StyledText`, `IconData`). | `extract_theme.py` reads the full `<Theme>`, so G2's span answer (G2-D1 (b)) is enough for it. G4b's comparison can now run: `layout_to_summary.py` against `xml_parsed/layouts/`, locally. |

The no-DDR build also trips the scrub guard on `Scripts/OneOfEverything.md:49`, not just entities.json, because the fallback step text quotes the parameter differently. It's the same cause as B1; its test list gains this case.

## 2. Units at a glance

| ID | Published unit | Verdict | Sessions |
|---|---|---|---|
| F0 | *(new)* Fixtures | Add. Every unit below needs a committed sample with themes, menus and sets, styled layouts, data sources and real step shapes. | 1 |
| C1 | Publish the model as a versioned contract | Keep. Split into 4 parts: complete the files, wrap them, add versions and migrations, then document. **Done 2026-10-21.** | 4 |
| C2 | Python reader API | Keep. Depends on C1. **Done 2026-10-21.** | 2 |
| C3 | Agree on the output location | Keep. Needs a root catalog JSON that doesn't exist yet. **Done 2026-10-21** (macOS run pending CI). | 1 |
| M1 | Specify a synthesized `Summary.xml` | Reshape. Write a spec with a provenance flag, and decide whether the FileMaker export script writes the manifest itself (Q4). | 1 (with M2) |
| M2 | Generate `Summary.xml` when missing | Reshape. Build it in memory only and never write it into the input folder. | (with M1) |
| M3 | Use the synthesized manifest for pairing | Shrink to a test. Pairing already ignores the manifest. | ½ |
| G0 | *(new)* Source spans | Add. One shared mechanism to point back at the export's XML. G1 needs it, and G2 and G4 can use it. | 1 + spike |
| G1 | Raw step XML per script step | Keep. Scrubbing is the hard part. | 1–2 |
| G2 | Theme styles | Keep. Structured metadata, with CSS through G0 or a field (decision G2-D1). | 1 |
| G3 | Custom menu and menu set UUIDs | **Changed by the update.** The consumer is now `menu-lookup`, not `install_menus.py`. It needs UUIDs on the pages, catalog UUIDs, and raw menu XML. Split it: G3a (UUIDs, model and pages), G3b (raw menu XML through G0). Contingent on the owner's open point 1. | 1 + ½ |
| G4 | Layout object geometry and styles | Keep. The gap is larger than the published text suggests. Split it. | 2 |
| G5 | External data source details | Shrink. The model is already complete; the only gap is in entities.json (done in C1). | ½ |
| D1 | *(new, from Q1)* Exports without DDR info | Add. Scripted exports have no `DDR_INFO`. Fixture, warning, and a coverage line for what's lost. | ½ |

---

## 3. Units

### F0. Fixtures first

**Why.** No committed sample has a custom menu set (the split sample's `FileA_CustomMenuSetCatalog.xml` is empty). Our only styled layouts, menu sets and real step shapes with `UUID`/`DDRREF`/`OwnerID` children are in `samples/has_indirection/`, which is client data and gitignored. There are no golden JSON tests, and the committed `samples/has_restricted_access_to_scripts/EverythingBagel_docs/` output is stale: its references.json has no `via`/`siteDocId`.

- [x] Fixture solution: an FM26 (26.0.3, SaXML 2.3.0.0) `EverythingBagel.fmp12` plus an `Empty.fmp12`, committed under **`samples/by_type/`** (2026-10-21):
    - `whole/EverythingBagel.xml`: one file, 356 KB, UTF-8, CR+LF
    - `split_catalogues/`: the same file as split catalogs, plus Summary.xml
    - `second_file/`: EverythingBagel and Empty as whole files, plus a real two-file Summary.xml
    - Re-exported 2026-10-21 (commit `076d510`) with the two additions below. All three exports carry them.
- [x] Froze the stale `EverythingBagel_docs/*.json` (from `samples/has_restricted_access_to_scripts/`; it has no `via`/`siteDocId`) as `tests/fixtures/contract_v0/`. The source folder is gitignored (`*_docs/`), so this copy is the only versioned one.

**What `samples/by_type/whole/EverythingBagel.xml` covers**

| Need | Present | Notes |
|---|---|---|
| Scripts and steps | Yes | 2 scripts, 209 steps: **one of every step type** (`OneOfEverything`), with `# (comment)`, If/Else and Set Variable. Every step has `DDRREF` and `OwnerID` children, the real shape Q11 asks about. |
| Themes | Yes | Two custom themes:<br>- `Vibrant Custom` (`defaultTheme="True"`, `baseName="com.filemaker.theme.vibrant"`)<br>- `Apex Blue Copy` (`baseName="com.filemaker.theme.apex_blue"`)<br>Each is used by one layout. Custom themes *do* carry their base on `<Theme>`. |
| Layout `LocalCSS` | Yes | 16 objects |
| Layout objects | Yes | Portal, button bar, 2 popovers, 4 buttons, 5 `IconData`, 26 `findMode` |
| Field display styles | Yes, but **numeric** | `Display Style="0|1|2|6"`, not `dropDown`/`popUp`. G4a needs a number → name map (Q15, answered in 1a #13; styles 3, 4 and 7 are only in `EverythingBagel_mac_run/display_styles/`). |
| Custom menus | Yes | 25 menus (24 bracketed standard copies plus `Custom Custom Menu`) |
| Menu set | Yes | `Custom Menu Set` id 2 with `<UUID>` |
| File default menu set | Yes | Catalog-level `CustomMenuSetReference` → `[Standard FileMaker Menus]` |
| Menu set on a layout | Yes | Layout `CustomMenuSetLayout` → `Custom Menu Set` (`UUID="4629F04A-…"`). Layout `EverythingBagel` uses `[File Default]` with `UUID=""`, so readers must allow an empty UUID. |
| External data sources | Yes | `Empty` (FileMaker, `file:Empty` + `fmnet:/127.0.0.1/Empty`) and `odbc_test` (ODBC) |
| Multi-file pairing | Yes | In `second_file/`, the `Empty` data source should pair with `Empty.fmp12` by path |

- [x] Added in the re-export: a second theme with a default marked (G2), and a layout with its own custom menu set (G3).

Smoke-testing these fixtures found a scrubber bug outside this roadmap. It's logged as backlog item **B1** (section 7).

Done when the fixtures are committed and `uv run pytest` still passes: 1,045 passed, 13 skipped on 2026-10-21.

---

### C1. Versioned contract

**Before C1 (baseline `be5d247`).** Kept for history; C1a–C1c changed all of this, and the line numbers are pre-change.
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

**Done 2026-10-21.** The decisions are below each item.

- [x] Grep H and `afm/` for any read of `entities.json`, `references.json`, `backlinks.json` and `external-references.json`. The breaking changes below assume there are none.
    - **agentic-fm reads none of them.** Its only `*.json` reads are the plug-in's `preferences.json`.
    - **H reads three of them, so the assumption was wrong:**
        - `entities.json`: the top level must be an object. It reads 10 named collections (`check_input`, `REQUIRED_KEYS`) plus `privilegeSets`, and ignores unknown top-level keys. **The envelope keys don't break it.**
        - `references.json`: `check_input` requires a bare list ("top level is not a list"), and `build_references` / `build_privileges` iterate it. **Wrapping it breaks H: it refuses to convert.**
        - `external-references.json`: it reads `dataSources[]` and `source.fileMakerVersion`. **Both are kept.** It doesn't read `source.fileName`, and H's fixtures already blank that path by hand.
        - It doesn't read `backlinks.json`.
    - **Mitigation:** H pins fm-saxml by version and hash (`get_fm_saxml.py` `VERSION`, `FM_SAXML_TESTED`; 0.6.1 at the time, 0.6.2 since 2026-10-21). Nothing breaks until someone bumps that pin. **The bump to 0.7.0 needs a two-line change in H**: read `refs["references"]` when the top level is an object. C1d's upgrade chain makes the same change on the reader side.
- [x] Decide the contract's scope. **Proposal:** one contract version shared by `entities.json`, `references.json`, `backlinks.json` and `external-references.json`. `model.json` stays internal and keeps its own `SCHEMA_VERSION`.
    - **Decided: one version (Q3).** It lives in `contract.py` as `CONTRACT_VERSION = (1, 0)`.
- [x] Decide the envelope. **Proposal:** every contract file becomes an object:
  ```json
  { "schemaVersion": "1.0", "generator": {"name": "fm-saxml-converter", "version": "0.7.0"},
    "source": {"fmpFileName": "...", "fileUuid": "...", "fileMakerVersion": "...", "saxmlVersion": "2.3.0.0"},
    "...": "payload" }
  ```
  Under this envelope references.json's payload goes under `references`, and backlinks' under `backlinks`.
  - `source` has no absolute path; the input file name is enough.
  - `generatedAt` is left out so output is byte-reproducible (Q6).
  - **Decided, with three refinements:**
    - In `entities.json` the collections stay **at the top level, next to the envelope keys**, not under an `entities` key. That keeps H working unchanged. `schemaVersion`, `generator` and `source` are reserved, and no collection may use those names (a test checks this).
    - `source` also carries `scope`, since every scoped id is built from it.
    - `generatedAt` is left out of every contract file (**Q6: yes**). `generator.version` is the package version, not the git commit, so two builds from one release are byte-identical.
- [x] Decide what to do about the docId instabilities:
    - Document positional step ids and name-based ids as they are. **Decided:** C1e writes them into `docs/contract.md`. Stable step ids wait for 2.0 (section 6).
    - Make silent duplicate overwrites a model warning. **Done:** `normalize._warn_duplicate_names` compares the raw records with the docIds they produce and adds `DUPLICATE_NAME` for tables, fields, TOs, value lists, custom functions, privilege sets, accounts, extended privileges, custom menus, menu sets and themes. FileMaker's dialogs reject duplicate names for these, so the warning shouldn't fire. If it does, Q5's answer is "yes" and it shows up in `Reports/warnings.md`. It doesn't fire on F0, NEXUS or DGC_UAT.
    - **Decided:** don't rewrite `ds:` scopes in 1.0. Add a `resolvedScope` on pairing in a 1.x minor.

#### C1b. Complete `entities.json` (session 2)

**Done 2026-10-21** (`render/json/writer.py` `build_entities`, tests in `tests/test_contract.py`).

- [x] Add the missing maps: `accounts`, `extendedPrivileges`, `customMenus`, `customMenuSets`, `themes`, `fileReferences`, `variables`, `externalDataSources`, `indirectionSites`.
    - `externalDataSources` is a list on the model. It's keyed here by a new docId form, `dataSource:<name>` (`ids.data_source_doc_id`). FileMaker keeps data source names unique.
    - `indirectionSites` is keyed by the site's own `docId` (`<source docId>#ind<n>`).
- [x] Add `fileOptions` and `graphNotes` as top-level non-map keys. `fileOptions` is `null` when the export has none.
- [x] Drive the list from `EntityMaps`' fields instead of the hardcoded list at `writer.py:89-101`, so a new entity type can't be left out again. A test asserts that every `EntityMaps` field is present.
- [x] Scrubbing: accounts and variables are already scrubbed in the model. Confirm `_guard_output` covers the new keys (`cli.py:422`).
    - Confirmed: `guard_output` scans every text file under the output folder, so new keys are covered with no change. `AccountEntity` has no password field.
    - NEXUS and DGC_UAT builds at the default level pass the guard. F0 still trips B1, which this unit doesn't touch.
- [x] Measure the size change on NEXUS (33 MB XML) and DGC_UAT (218 MB). Record it here.

    | File | NEXUS before → after | DGC_UAT before → after |
    |---|---|---|
    | entities.json | 12.35 → 13.73 MB (+11%) | 150.9 → 162.7 MB (+8%) |
    | references.json | 3.29 → 3.51 MB | 58.8 → 62.8 MB |
    | backlinks.json | 1.91 → 2.05 MB | 34.3 → 36.6 MB |
    | build time | 4.9 s → 5.0 s | 1 m 46.5 s → 1 m 46.7 s |

    - Most of the entities growth is `variables`: 949 entries / 1.1 MB on NEXUS, 7,447 / 8.3 MB on DGC. Next are `indirectionSites` (2.1 MB on DGC) and `customMenus` (0.4 MB). Everything else is under 0.1 MB.
    - references.json and backlinks.json grow about 7% with no new data. Their payload moved one level down under the envelope, so every line gets two more spaces of indentation. If size starts to matter, drop `OPT_INDENT_2` for these two files (a minor change, since readers parse JSON, not whitespace).
- [x] Test: every `targetDocId` in references.json either exists in entities.json, is scoped external, or has confidence `unresolved`. It passes on F0 with no exceptions.

#### C1c. Envelope and versions (session 3)

**Done 2026-10-21.**

- [x] Add a `contract.py` module with `CONTRACT_VERSION = (1, 0)` and `parse_version("1.0") -> (1, 0)`. Fix the string comparison at `cli.py:787` to use it (with the model's own version).
    - `contract.py` also holds `CONTRACT_FILES`, `ENVELOPE_KEYS`, `format_version` and `envelope(model)`.
    - `parse_version` returns a tuple of any length (`"0.5.0"` → `(0, 5, 0)`) and raises `ValueError` on anything else.
    - rename-check now calls `cli._model_older_than(model, (0, 5))`. A version it can't read counts as old.
- [x] Wrap all four files as decided in C1a. `external-references.json` moves from its own `1.0.0` to the shared contract.
    - references.json is now `{envelope, "references": [...]}`, and backlinks.json is `{envelope, "backlinks": {...}}`.
    - The envelope's `source.saxmlVersion` needed a new model field: `SourceInfo.saxml_version`, read from `FMSaveAsXML/@version`. **model.json `SCHEMA_VERSION` 0.5.0 → 0.6.0** (additive).
- [x] Write the split JSON from `render` too, or say in the contract that only `build` produces it (decision).
    - **Decided: `render` writes it too.** `--include-json/--no-include-json` is now shared by `build` and `render` (`IncludeJsonOpt`), so every docs folder carries the contract.
- [x] Remove the absolute input path from `external-references.json`. `source.fileName` is gone. No contract file holds a path, and a test checks this.

#### C1d. Upgrade chain (session 4)

**Done 2026-10-21** (`contract_models.py`, `contract_migrations.py`, tests in `tests/test_contract_versions.py`).

- [x] Add `contract_migrations.py`: an ordered registry `{(0, 0): upgrade_0_to_1, …}` that works on plain dicts in memory, chained, and returns the current major.
    - The registry is keyed by major (`UPGRADES = {0: upgrade_0_to_1}`); a minor never needs an upgrade.
    - `upgrade(file_name, data)` returns the dict at the current major. `read_contract_file(path)` parses, upgrades and validates, and returns the typed model.
    - **"The 1.0 models" had to be written first:** `contract_models.py` has one Pydantic model per file (`EntitiesDoc`, `ReferencesDoc`, `BacklinksDoc`, `ExternalReferencesDoc`, plus the shared `ContractEnvelope`). `EntitiesDoc` extends `EntityMaps`, so new entity types reach it automatically. A test round-trips every file of a build through its model, so the models can't drift from the writer.
- [x] Rules:
    - A file with no `schemaVersion` (a bare array, or entities without an envelope) counts as **0.0**.
        - So does external-references.json with its old three-part `"1.0.0"`.
    - A minor difference reads as-is, and missing keys take Pydantic defaults.
    - A newer major fails with `ContractVersionError("docs written by schema 2.x; this fm-saxml reads up to 1.x — upgrade fm-saxml")`. The message starts with the file's path.
    - 0.0 → 1.0 adds the envelope with `generator: null`, wraps references and backlinks, and drops external-references' absolute `source.fileName`.
- [x] Fixture test: load `tests/fixtures/contract_v0/` (from F0), upgrade it, and validate against the 1.0 models. All four files upgrade with no changes needed to the models.
- [x] Fixture test: a synthetic `"schemaVersion": "1.9"` with an unknown key loads and ignores the key. A `"2.0"` fails with the message above.

#### C1e. Contract document and golden test (with C1d or a 5th session)

**Done 2026-10-21.**

- [x] Write `docs/contract.md`:
    - the collections, required keys per entity, and the docId rules (C1a)
    - the scoped-id forms and what `confidence` values mean
    - the version policy (what is minor and what is major)
    - Also: reading older files, external-references resolution, and the steps for changing the contract. Linked from README's Documentation table. README_technical's output layout and `--include-json` row are updated.
    - A test fails if the page stops mentioning a collection.
- [x] Generate a JSON Schema per file from the Pydantic models (`model_json_schema`) into `docs/contract/schema-1.0/`. Add a test that fails when the committed schema is stale.
    - The schemas are validation-mode (Draft 2020-12), so their `required` lists are the required keys.
    - The F0 build validates against them with the `jsonschema` package, added as a **dev-only** dependency. The test skips if it's missing.
- [x] Golden test: build F0's sample twice and assert the JSON is byte-identical. Store a golden copy and diff against it, with an `--update-golden` flag.
    - Golden copy: `tests/fixtures/contract_golden/EverythingBagel/` (four files, 290 KB), built unscrubbed from `samples/by_type/whole/EverythingBagel.xml`.
    - The comparison masks `generator.version`, so a release bump doesn't fail it. A mismatch prints a unified diff.
    - `uv run pytest tests/test_contract_versions.py --update-golden` rewrites both the golden copy and the schemas (flag in `tests/conftest.py`).

**Unknowns.** Whether H or agentic-fm parse these files today (C1a). Size growth on big files (C1b). Whether duplicate names occur in real exports (Q5).

**Done when** a 1.0 build validates against the committed schema, the v0 fixture upgrades, and a 2.0 doc fails clearly. **Met 2026-10-21:** each condition is a test in `tests/test_contract_versions.py`.

---

### C2. Python reader API

**Before C2 (2026-10-21).** `fm_saxml/__init__.py` held only `__version__`. `model/__init__.__all__` re-exported 20 classes but left out `LayoutObjectEntity`, `AccountEntity`, `VariableEntity`, `ExternalTarget` and `IndirectionSite`. The pipeline lives in private `cli._run_pipeline` / `_analyze`. The distribution is `fm-saxml-converter`, the import name is `fm_saxml`, Python 3.11 or later.

#### C2a. API shape and single-file loading (session 1)

**Done 2026-10-21** (`src/fm_saxml/api.py`, tests in `tests/test_reader_api.py`).

- [x] Write `fm_saxml/api.py` and re-export it from `fm_saxml/__init__.py`:
  ```python
  docs = fm_saxml.load(docs_dir)          # -> SolutionDocs (one file) or BatchDocs (a batch root)
  docs.source, docs.schema_version
  docs.entities.scripts["script:Foo"]     # typed Pydantic entities, same classes the converter uses
  docs.references                         # list[ReferenceRecord]
  docs.refs_from(doc_id) / docs.refs_to(doc_id)
  docs.find("script", "foo")              # case-insensitive name lookup, returns all matches
  ```
    - Also: `docs.get(doc_id)`, `docs.collection(kind)`, `docs.backlinks`, `docs.external`, `docs.name`, `docs.catalog` (its docs.json), and `docs.to_document_model()` (the converter's model, rebuilt without warnings, scrub summary or coverage).
    - `find()` matches `name`, plus a field's `Table::Field` and a theme's `displayName`. A kind can be a docId prefix (`script`, `to`), a collection (`scripts`) or a plain word (`tableOccurrence`, `object`).
    - `fm_saxml` exports `load`, `find_docs`, `SolutionDocs`, `BatchDocs`, `ResolvedRef`, `DocsNotFoundError` and `ContractVersionError`.
- [x] Run C1d's upgrade chain on load and raise `ContractVersionError` / `DocsNotFoundError` with paths in the message. `load()` reads pre-contract docs too (`tests/fixtures/contract_v0/` loads, with `source` taken from external-references).
- [x] Performance:
    - Measure `model_validate` over NEXUS/DGC entities.json.
    - If it takes more than ~2 s, load collections lazily: validate on first access to `docs.entities.<collection>`.
    - Record the numbers here.

    | Export | entities.json: parse + validate | references.json |
    |---|---|---|
    | NEXUS (13.7 MB entities) | 0.04 s + 0.04 s | 0.03 s |
    | DGC_UAT (162.7 MB entities) | 0.50 s + 0.60 s | 0.39 s |

    - Under 2 s, so collections aren't lazy. Each **file** is read on first use instead (`cached_property`): opening a batch and touching one file's entities reads nothing else.
    - `scriptSteps` (0.52 s) and `layoutObjects` (0.24 s) are most of DGC's validation time.
- [x] Complete `model.__all__` and mark the public surface in `docs/contract.md`. `model.__all__` now lists 54 classes (every entity class, `ReferenceRecord`, `ExternalTarget`, `IndirectionSite`, `EntityMaps`, …). `docs/contract.md` has "Reading from Python" with the public surface.

#### C2b. Batch loading and consumer ergonomics (session 2)

**Done 2026-10-21.**

- [x] `load(batch_root)` reads the root catalog from C3 and returns `BatchDocs` keyed by file name, plus `.resolve(scoped_doc_id)` across files. This covers the `<fileUuid>/`, `file:`, `ds:` and `xfile:` forms.
    - `BatchDocs` is a read-only mapping. Lookups ignore case and accept `Name`, `Name.fmp12` or the folder.
    - `resolve()` returns `ResolvedRef(file, doc_id, entity)`: `entity` is None when the file is there but the docId isn't, and the whole result is None when the file isn't in the batch. An unscoped docId raises `ValueError`.
    - `ds:` scopes resolve through docs.json's new `pairings` (the build's own data-source pairing, with the data source UUID). A batch built before docs.json falls back to pairing by path, as the build does.
    - **The `ds:` scopes in the files themselves are still not rewritten** (decided in C1a); `resolve()` is how a reader follows them.
- [x] Decide whether `diff`, `rename-check` and `render` move to `load()` as well, as dogfooding. Recommendation: yes for `rename-check`, later for the rest.
    - **Decided as recommended.** `rename-check` accepts one file's docs folder (`cli._load_docs_model` → `load().to_document_model()`); a batch root is refused with the folder to use. On NEXUS its report is identical to the XML run's (18 names, 76 by-name places). `diff` and `render` stay on XML / model.json for now.
- [x] Dependency weight. agentic-fm will `pip install fm-saxml-converter`, which pulls lxml, typer, rich, jinja2 and orjson. Decide whether that's acceptable or whether to make a `[cli]` extra (Q7).
    - **Decided: no `[cli]` extra for 0.7.0.** An extra would break `pipx install fm-saxml-converter` (and H's README command), which needs the CLI deps.
    - What matters at run time is import cost, and that's fixed: `import fm_saxml` takes about 160 ms and loads none of lxml, typer, rich, jinja2 or slugify. A test guards it. The reader had been loading the parser through `normalize/__init__.py`; it now imports `normalize.ids` and `safe_slug` only where used.
    - Revisit only if install size inside agentic-fm becomes a problem (Q7 stays open for the harness owner).

**Unknowns.** agentic-fm's Python floor and how it pins this package. (Lazy validation: not needed, see C2a.)

---

### C3. Output location

**Done 2026-10-21** (tests in `tests/test_output_location.py`; documented in `docs/contract.md` "docs.json" and "Where docs live").

**Before C3.**
- `build` writes to `--out`, or else `<stem>_docs` / `<folder>_docs` next to the input (`cli.py:263-265, 324`).
- A batch writes `<root>/<safe_slug(file)>/` per file, and reserves `reports` and `_viewer` (`cli.py:388-470`).
- `--force` **wipes** the whole folder (`cli.py:1085-1150`).
- There's no config file. The only environment variables are `FM_SAXML_SCRUB_SALT`, `FM_SAXML_DEBUG` and `FM_SAXML_NO_UPDATE_CHECK`.
- `exports/` appears nowhere in this repo; it's agentic-fm's convention.
- A `.fm-saxml` marker file is written to the output root, but it carries no data.
- A batch root has no JSON listing its files.

- [x] **Root catalog.** Write `docs.json` at every output root:
    - single file: `{schemaVersion, kind: "single", file: {...}}`
    - batch: `{schemaVersion, kind: "batch", files: [{name, fmpFileName, fileUuid, folder, saxmlVersion}], synthesizedManifest: bool}`

  It replaces scanning subfolders or parsing `_viewer/manifest.js`. Fold the `.fm-saxml` marker into it, or keep both (decision).
    - **Built with one shape for both kinds:** `{schemaVersion, generator, kind, solution, files: [...], pairings: [...], synthesizedManifest}`. A single build has one entry in `files` with `folder: ""`, so readers don't branch on `file` vs `files`. Each file also carries `scope` and `fileMakerVersion`. `pairings` is new (batch only, used by `resolve()`; also covers half of G5's `pairedFile`).
    - Part of contract 1.0: `DocsCatalog` model, `docs.schema.json`, golden copy. `build` and `render` write it; `--no-include-json` leaves it out.
    - **Decided: keep both.** `.fm-saxml` stays the "safe to overwrite" marker the overwrite prompt checks; `docs.json` is data. Older output has only the marker.
- [x] **Config key.** Use one environment variable, `FM_SAXML_DOCS_ROOT`, plus `--docs-root`. If it's set, `build` without `--out` writes to `<root>/<solution-slug>/`. Here "solution" means the batch folder name for a folder, or the file stem.
    - The FileMaker export script (Phase 3) writes into timestamped folders, so the output path must **not** follow the input folder. It must be stable per solution.
    - **Changed, because of that point:** for one file, the solution is the FileMaker file name **read from the export** (`File` attribute), not the input file's stem. A timestamped `Invoices 2026-10-21 1530.xml` still goes to `<root>/Invoices` (tested).
    - For a folder of exports it's still the folder's name. **A timestamped export folder needs `--solution <name>`** (new option, also used for docs.json's `solution`). Phase 3's `/convert` should pass it.
    - Precedence: `--out`, then `--docs-root` / `FM_SAXML_DOCS_ROOT`, then `<input>_docs`.
- [x] **Lookup function.** Add `fm_saxml.find_docs(solution: str, root: Path | None = None) -> Path`:
    - case-insensitive, slug-aware
    - also matches a file name inside a batch's `docs.json`
    - with no match, the error lists the solutions it found
    - Match order: folder name or slug, then docs.json `solution`, then a file listed in any docs.json (a batch member returns its own folder). Several matches at one step raise `DocsNotFoundError` instead of guessing.
- [x] **Safe rewrite.** Repeated `/convert` calls will rebuild in place while readers may be open.
    - Build into `<out>.tmp-<pid>`, then swap.
    - On Windows, `os.replace` on a directory with open handles fails, so either rename the old folder aside first and retry, or document the limit (test on Windows).
    - **Both:** `cli._staged_output` builds into `<out>.tmp-<pid>`, renames the old folder to `<out>.old-<pid>` (retrying 15 × 0.2 s), moves the new one in, then deletes the old one. A failed build deletes the staging folder and leaves the old docs alone.
    - **Tested on Windows:** with a file held open inside the old docs, the swap is refused. The build stops with "Could not replace …", keeps the old docs, and says where the new ones are. Readers that load and close (like `load()`) don't block it. Documented in docs/contract.md.
    - Applies to `build` (single and batch). `render` still clears its folder in place.
- [x] State in the README and the contract that converted output is local and never committed. Agentic-fm's `.gitignore` is an `[afm]` follow-up.

- [ ] *(new)* Test `find_docs`, the root catalog and the safe rewrite on macOS as well as Windows. The update's Phase 3 runs `/convert` on both, and on the Mac it replaces the exploder outright.
    - Tests written and passing on Windows. The open-file test expects the swap to succeed on macOS/Linux. CI runs the suite on `macos-latest` and `ubuntu-latest`, so **tick this after the first green CI run on the push.**

**Unknowns.** Whether agentic-fm wants to keep `exports/<name>_docs` or adopt `FM_SAXML_DOCS_ROOT` (Q8). Either works: agentic-fm can point `FM_SAXML_DOCS_ROOT` at its `exports/` folder, with `--solution` keeping names stable.

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

G1 needs this, and G2, G3b and G4 can reuse it. Today `SourceXmlInfo{path, line}` exists (`model/entities.py:45-51`), but `line` is never filled and `path` is a non-unique tag chain (`parser/extractors/_helpers.py:87-96`).

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
- [ ] Fill spans only for the entities that need them: scripts and steps (G1), themes (G2-D1), layouts and layout objects (G4), custom menus and menu sets (G3b). They go behind the contract as a 1.x minor addition. If 1.0 hasn't shipped yet, put them in 1.0.
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
    - The exploder strips `<UUID>`, `<OwnerID>` and `@index` and keeps `@hash` (1a #11). So the Mac run's `xml_parsed/scripts/EverythingBagel/OneOfEverything - ID 1.xml` is the exact input `saxml_read` gets today. Compare `fm_xml_to_snippet.py` on that file and on our raw slice; the two outputs should match.
    - If they don't, add `raw_xml(doc_id, form="exploder")`, which drops those three, rather than patch agentic-fm.

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

### G3. Custom menu and menu set UUIDs (1½ sessions; contingent on the owner's open point 1)

**What changed.**
- The published roadmap's consumer was `install_menus.py`. The tentative update deletes it with the exploder path and keeps the `menu-lookup` skill instead.
- Its Phase 5 rewrite unit: *"Find a custom menu or menu set by name or ID from the fm-saxml pages and return the real UUIDs needed before creating or modifying menu XML."*
- Skills read Markdown pages (principle "No extra files"), so the UUIDs must be on the **pages**, not only in entities.json.

**What `menu-lookup` needs** (`afm/.cursor/skills/menu-lookup/SKILL.md`, read 2026-10-21). Today it lists `agent/xml_parsed/custom_menus/*/` and `custom_menu_sets/*/` and reads the matched file:
- Matching by numeric ID (from `- ID {N}.xml` file names, or a set's `<CustomMenuReference id>`), then exact, contains and fuzzy name. It handles several solutions by solution folder.
- It reports four UUIDs, "never invent them":
    - `CustomMenuCatalog` UUID
    - `CustomMenu` UUID
    - `CustomMenuSetCatalog` UUID
    - `CustomMenuSet` UUID
- It also reports the menu item count (`MenuItemList @membercount`).
- **Modifying an existing menu uses the source XML from `xml_parsed/custom_menus/` as the base**, copied to `agent/sandbox/`, edited, and written to the clipboard. So the skill needs the menu's **raw XML**, not just its UUIDs. A new menu still starts from a clipboard copy taken in FileMaker, as today.
- Item UUIDs and `hash` can be placeholders: FileMaker reassigns them on paste.

**What the old consumer needed**, for comparison (`afm/agent/scripts/install_menus.py`, deleted by the update). It took UUIDs from **clipboard snapshots** (`agent/sandbox/custom_menus.xml`, `custom_menu_set.xml`), because its docstring says they're "not available in xml_parsed" (`:20-21, 45-73`):
- per-menu ID and UUID
- `FM_FILE_NAME`, `FM_FILE_UUID`
- `CustomMenuCatalog` UUID, `CustomMenuSetCatalog` UUID, the menu set UUID and ID
- the standard menus `CustomMenuSetReference @UUID`

The UUID list is nearly the same, so G3a's model work stands. What's new is the page surface and the raw XML.

**What we keep:** menus (`entities.py:594-609`) have name, id, base menu, install condition, mode flags and items. Item `id` is read but dropped (`custom_menus.py:72-108`). Sets have name, id and menu docIds. **No UUIDs anywhere.** File name and UUID are already in `SourceInfo`.

**In the export:**
- `FileA_CustomMenuCatalog.xml:58`: catalog `<UUID>`
- `:60-61`: `<CustomMenu name id><UUID>`
- DGC_UAT:
    - `:177752`: set catalog `<UUID>`
    - `:177754`: file default `CustomMenuSetReference @UUID`
    - `:177756-57`: a set `<UUID>`
    - `:237483`: a layout's `[Standard FileMaker Menus]` reference `@UUID`

**On the pages today.** `CustomMenus/<name>.md` and `CustomMenuSets/<name>.md` exist (`render/markdown/renderer.py:792-830`, templates `custom_menu.md.j2`, `custom_menu_set.md.j2`). Their front matter has `docId`, `entityType` and `name`. The Metadata table has FMP ID, modified, base menu and mode flags. No UUIDs, no item count.

#### G3a. UUIDs in the model and on the pages (session 1)

- [ ] Add `uuid` to `CustomMenuEntity`, `CustomMenuItem` (plus `id`) and `CustomMenuSetEntity`.
- [ ] Add catalog UUIDs (`customMenuCatalogUuid`, `customMenuSetCatalogUuid`) and the default set reference `{name, id, uuid}` to `fileOptions` (or `SolutionInfo`; decide which).
- [ ] Keep the UUID on layout `menu_set` references.
- [ ] **Pages** *(new)*. Front matter on menu and menu set pages gets `fmpId`, `uuid` and `catalogUuid`, so a skill can read them without parsing tables. The Metadata table gets the same rows plus the item count.
    - The page's own UUID goes in front matter only if the scrubber leaves it alone. UUIDs aren't secrets, but confirm `_guard_output` doesn't treat them as such.
- [ ] Item count from the model (`len(items)`). Check that it equals `MenuItemList @membercount` on F0.
- [ ] Test on F0 (it needs a non-empty menu set; see F0). Assert the four UUIDs on the page and in entities.json for `Custom Custom Menu` and `Custom Menu Set`.
- [x] Verify with a person on FileMaker that the clipboard `FMObjectTransfer` UUIDs equal the SaXML ones (Q12). **They match** for the menu, its item, both catalogs and the set (Mac run, `clipboard/`). The exploder's menu files lack the catalog UUIDs entirely (1a #10), so this unit gives `menu-lookup` data it never had.
- [x] Verify whether the `[Standard FileMaker Menus]` UUID is a constant across files (Q13): it isn't. Read it per file.

#### G3b. Raw menu XML (half a session, after G0) *(new)*

- [ ] G0 spans on `CustomMenu` and `CustomMenuSet` elements, so `docs.raw_xml("customMenu:…")` returns the base XML that `menu-lookup` edits.
- [x] Decide the shape (Q16). **The paste needs the catalog wrapper** (1a #9). FileMaker's clipboard copy is `CustomMenuCatalog` (SortOrder, CustomOrderList, catalog UUID) → `CustomMenu`, plus a `PasteIndexList`. Its action steps are in snippet form, not SaXML form. So:
    - `raw_xml("customMenu:…")` returns the SaXML `<CustomMenu>` element. The catalog UUID comes from G3a.
    - Converting that into the clipboard form is `[afm]` work, next to `fm_xml_to_snippet.py`. The Mac run's `clipboard/Custom Custom Menu.clipboard.xml` is its target fixture.
    - Still read `afm/agent/docs/CUSTOM_MENUS.md` before the `[afm]` converter, in case it documents more.
- [ ] Scrubbing: menu item titles and install conditions are calcs. The raw XML must come from the same scrubbed source as G1 (G1-D1).
- [ ] Until G3b ships, `menu-lookup`'s rewrite can tell the developer to copy the menu from FileMaker and read it with `clipboard.py read`, the path the skill already uses for new menus. Note this for the Phase 5 rewrite.

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
    - `display_style` map (Q15, 1a #13): 0 `editBox`, 1 `dropDownList`, 2 `popUpMenu`, 3 `checkboxSet`, 4 `radioButtonSet`, 6 `dropDownCalendar`, 7 `concealedEditBox`. Keep the raw number too; 5 and anything unknown pass through as the number.
    - Fixture: `samples/EverythingBagel_mac_run/display_styles/EverythingBagel_styles.saxml.xml` has styles 3, 4, 6 and 7. F0 has only 0, 1, 2 and 6.
- [x] Bounds: confirm the unit (Q14). **Points.** SaXML and the XML2 clipboard give identical bounds (1a #13). Our docstrings that say "pixel" get fixed in this session, and the contract says points.
- [ ] `@key` vs `id`: `layout_to_summary.py:514` reads `@key`, but SaXML objects carry `id`. **Confirmed by the Mac run**: exploded layout objects have no `@key` (1a #12). Note it for the Phase 2 port. No model change.

#### G4b. Styles and raw layout XML (session 2)

- [ ] Add `local_css: {name, display_name, css}` on objects and parts.
- [ ] Decide whether to also parse the visuals agentic-fm derives (colour, radius, font) into fields, or leave that to the port (decision G4-D1). Recommendation: keep `css` raw, and let a helper in the reader API parse it so the logic lives in one place.
- [ ] G0 spans on layouts and layout objects, so layout-design can fetch real layout XML through `raw_xml`.
- [ ] Field-by-field comparison: run `layout_to_summary.py` on F0 through the exploder (Q1) and diff its output against what the model now holds. The Mac run didn't generate layout summaries (not on the default path), but its `xml_parsed/layouts/` is the input: run `layout_to_summary.py` on it locally. Every remaining gap is either fixed here or noted as "not needed" with a reason. That table also answers Phase 2's "port or retire" question.

---

### G5. External data source details (half a session)

**What agentic-fm reads** (`afm/agent/scripts/analyze.py`):
- `analyze_integrations` lists data source file stems (`:1941-1945`).
- `detect_multi_file` reads `@name`, `@id`, `@type` and `UniversalPathList` split on CR/LF. It parses `file:`/`fmnet:` and flags `$var` paths (`:1998-2081`).

**What we keep:** `ExternalDataSource{name, fmp_id, uuid, type, paths[]}` (`document_model.py:60-69`), with paths split per line or `<Location>` (fixed in fix_gaps2). That already covers everything `analyze.py` uses.

- [x] Add `externalDataSources` to entities.json (done in C1b; tick both). Keyed by `dataSource:<name>`.
- [ ] Add `pairedFile` / `pairing.match` from batch linking to each data source in a batch build. agentic-fm's `data_source_map` recomputes this by path and base-table overlap (`:2097-2160`); we already compute it in `batch/links.py`.
- [ ] Note for Phase 2: H's `data_sources.index` is never read by `analyze.py` (H:360-367). The port reads the model, so nothing to fix here.

---

### D1. Exports without DDR info (half a session) *(new, from Q1)*

**Why.** The export the roadmap depends on, agentic-fm's scripted Save a Copy as XML, writes `Has_DDR_INFO="False"` (1a #7). Nothing in fm-saxml says so today. The output just reads a little differently and quietly loses the popover title, the external base table and FileMaker's own step text.

- [ ] Fixture: `samples/EverythingBagel_mac_run/saxml/EverythingBagel.xml` is a committed no-DDR twin of `by_type/whole/`. Test that both builds have the same entity docIds (apart from the two pasted scripts), and that references differ only in the external base table.
- [ ] Read `@Has_DDR_INFO` into `SourceInfo`, and put it in the contract's `source` (a 1.x minor field).
- [ ] When it's `False`, add one model warning that names what's missing, and a line on the coverage report and index.md.
- [ ] Check whether the external base table can come from somewhere other than `DDR_INFO` (the `Empty` TO's `BaseTableReference`, or the paired file in a batch). If it can, use it.
- [ ] `[fm]` note for Phase 3: the export script turns on the step's analysis-tools option, `include_details` (Q17). A colleague's rewrite of the export script already sets it. Once it runs, check its export says `Has_DDR_INFO="True"` and has a `DDR_INFO` block.

## 4. Order and dependencies

```
F0 ─┬─ C1a → C1b → C1c → C1d → C1e ─┬─ C2a → C2b
    │                               └─ C3 (docs.json needs the envelope)
    ├─ M1+M2 → M3                         (independent; can run any time)
    ├─ G5 (with C1b) · G3a · D1           (small; after C1b)
    └─ G0 spike → G0 → G1 · G2 · G3b · G4b (G4a can start after F0)
```

Suggested release cut:
- **0.7.0 = contract 1.0**: F0, C1, C2a, C3, M1–M3, G3a, G5, G4a, D1.
- **0.8.0 = raw XML**: G0, G1, G2, G3b, G4b, C2b.

H (the harness adapter) moves to 0.7.0 only with its references.json fix. Otherwise it stays on 0.6.2 until Phase 2 retires it.

After 0.7.0:
- Phase 2's trace.py and data-source ports can start.
- So can the Phase 5 `menu-lookup` rewrite, for lookups and UUIDs, with the clipboard fallback for edits.

After 0.8.0: the snippet, theme and layout-design ports, and `menu-lookup` edits from raw XML.

Phase 2 no longer ports `install_menus.py` or the web viewer, so 0.7.0 unblocks one port fewer than before.

**Gate added by the update.** Phase 2's "Delete the exploder path" now removes `xml_parsed/` on the Mac too. Before it lands:
- 0.8.0 must have shipped, or every kept reader must have a working fallback.
- ~~Q1's real exploder run must be done.~~ Done 2026-10-21 (`samples/EverythingBagel_mac_run/`).

About 19–22 agent sessions in total (G3b and D1 add half a session each).

## 5. Open questions

| # | Question | Blocks | Who |
|---|---|---|---|
| Q1 | ~~Can someone run fm-xml-export-exploder on a Mac against F0's export?~~ **Done:** `samples/EverythingBagel_mac_run/` (`3c3c4a8`). Findings in section 1a. | — | answered 2026-10-21 |
| Q2 | ~~Do H or agentic-fm parse `entities.json`/`references.json` anywhere today?~~ **H does; agentic-fm doesn't.** Only the references.json wrap breaks H, and only after its pin bump. See C1a. | — | answered 2026-10-21 |
| Q3 | ~~One contract version for all four files, or one each?~~ **One** (`contract.CONTRACT_VERSION`). | — | decided 2026-10-21 |
| Q4 | Should the FileMaker export script write a Summary.xml (host, time, file list)? | M1 scope, Phase 3 `[fm]` | harness owner |
| Q5 | Can tables, TOs, value lists or custom functions have duplicate names in a real export? Today they silently overwrite. | C1a docId rules | check FileMaker |
| Q6 | ~~Drop `generatedAt` from contract files to make them byte-reproducible?~~ **Yes, dropped.** A test builds F0 twice and compares the bytes. | — | decided 2026-10-21 |
| Q7 | Is the full CLI dependency set acceptable inside agentic-fm, or do we add a `[cli]` extra? **Our answer for 0.7.0: no extra** (it would break `pipx install`); importing the reader loads none of the CLI deps (C2b). Harness owner to confirm install size is fine. | — | harness owner |
| Q8 | `FM_SAXML_DOCS_ROOT` or agentic-fm's `exports/<name>_docs`? Both work: `FM_SAXML_DOCS_ROOT=<agentic-fm>/exports` gives `exports/<name>` (no `_docs` suffix), and `--out exports/<name>_docs` keeps today's exact path. | Phase 3 `/convert` | harness owner |
| Q9 | Are byte spans reliable on UTF-16 and CR-heavy exports, and what do they cost on 218 MB? | G0 | spike |
| Q10 | Store the export root as an absolute path in docs, or make the reader pass it? | G0 | us |
| Q11 | Does `saxml_read` handle real steps with `UUID`/`DDRREF`/`OwnerID` children? **Narrowed:** the exploder strips `UUID`, `OwnerID` and `@index`, so it has never seen them (1a #11). Test with the Mac run's exploded script vs our raw slice. | G1 hand-off | afm test |
| Q12 | ~~Are the clipboard `FMObjectTransfer` menu UUIDs the same as SaXML's?~~ **Yes**, for menu, item, both catalogs and set (1a #8). | — | answered 2026-10-21 |
| Q13 | ~~Is the `[Standard FileMaker Menus]` set UUID a constant?~~ **No:** it's `2C8E1610-…` in by_type/EverythingBagel and `129DFB31-…` in DGC_UAT. It's per file, so it must be read from the model. | — | answered 2026-10-21 |
| Q15 | ~~What does each `Display @Style` number mean?~~ **0 Edit Box, 1 Drop-down List, 2 Pop-up Menu, 3 Checkbox Set, 4 Radio Button Set, 6 Drop-down Calendar, 7 Concealed Edit Box**; 5 not seen (1a #13). | — | answered 2026-10-21 |
| Q14 | ~~Bounds unit (points vs pixels).~~ **Points**, the same in SaXML and the clipboard (1a #13). | — | answered 2026-10-21 |
| Q16 | What XML does a menu paste need? **Mostly answered:** the catalog wrapper plus a `PasteIndexList`, with steps in snippet form (1a #9). SaXML → clipboard conversion is `[afm]` work. Still read `afm/agent/docs/CUSTOM_MENUS.md` before writing that converter. | `[afm]` menu converter | afm |
| Q17 | ~~What is the Save a Copy as XML script step's option that sets `Has_DDR_INFO="True"`~~ **`include_details`**, in the step's JSON options ("Specify JSON options", then `[ "include_details" ; True ; JSONBoolean ]`). Seen in a copied step from FileMaker 26 on Windows (2026-10-21). A colleague's rewrite of the export script uses it. agentic-fm's Explode XML step has no JSON options at all, which is why its export lacks DDR info. **Still open:** confirm an export made with it has `Has_DDR_INFO="True"`, and whether FileMaker 21–25 and the Mac offer it. | D1, Phase 3 `[fm]` export script | person on FileMaker |
| OP1 | *(new; the parent update's open point 1)* Do menu UUIDs stay in v1, or does `menu-lookup` answer only from what the pages hold? | G3a, G3b, Q12, Q16 | owner (Matt) |
| G1-D1 | Where scrubbed raw XML comes from (on-demand rewrite, scrubbed copy, or inline). It now also feeds G3b. | G1, G3b | us + harness owner |

## 6. Brainstorm (add freely)

- `docs.raw_xml()` could back a WebMCP tool (`get_raw_xml`) so a browser agent gets paste-ready XML without the CLI.
- A `fm-saxml snippet <docs> "script:Foo"` command would make G1 useful on its own, before agentic-fm's port.
- Stable step ids: once step UUIDs are kept (G1), `scriptStep:<script>:<uuid>` could become a 2.0 docId. For now it stays positional.
- `docs.json` could carry a coverage summary, so Phase 6's `doctor` (Phase 7 before the update) can report "converted with schema 1.0, 1,824/1,824 checks".
- For the After-v1 Proofkit table: Proofkit's MCP reads the live, unscrubbed file and needs FileMaker open. fm-saxml is the offline, scrubbed, versioned reading. A one-line rule could be "questions about structure → fm-saxml docs; live data or running scripts → Proofkit".
- A `menu-lookup` WebMCP tool on the HTML viewer would be cheap after G3a: the viewer already holds the model.

## 7. Backlog (outside Phase 1)

Found while working on this roadmap. These items don't block any Phase 1 unit. Do B2 after B1, because B2 replaces the rule B1 patches.

### B1. Scrubber: AI account names redacted as API keys, and the guard trips on a parameter label

**Symptom.**
- `fm-saxml build samples/by_type/second_file` writes everything, then exits 2: "Scrubbing guard failed: 2 redacted value(s) still appear in the output".
- Both hits are in `EverythingBagel/entities.json`, on step 26, *Configure RAG Account*.

**Cause, in two parts.**
1. **Over-broad rule.**
    - `scrub/structural.py:136-137` treats *every* calc of Configure AI Account (212) and Configure RAG Account (227) as `api_key` / `ai_account`.
    - So the account **name** is redacted as if it were the key: `"accountNameGoesHere"` → `[REDACTED:api_key#1]`, `"RAGAccountName"` → `[REDACTED:api_key#2]`.
    - Each step has separate calc slots for name, key and endpoint. The rule should look at the slot, not the step.
2. **The guard matches a structural word.**
    - The literal `"RAGAccountName"` is also the parameter's type (`<Parameter type="RAGAccountName">`).
    - entities.json writes that as `params[].label` and `calculations[].parameter`.
    - `scrub/guard.py` searches the output for every redacted value, so it finds the parameter type name and reports a leak. The real value was redacted correctly.
    - Anyone who hardcodes a value equal to a step's parameter type name or option label hits the same failure.

**Work.**
- [ ] Make the AI/RAG rule slot-based: only the API key parameter is `api_key`. The account-name slot moves to B2's `account_name` rule, or is left alone if B2 isn't done yet.
    - The sample's API key slots are empty: Configure AI Account only shows `LLMAccountName`. So F0 needs both steps filled in with a literal key and endpoint first, to learn the key's parameter type name (see B2's census).
- [ ] Guard decision (B1-D1). The options:
    - (a) Build a vocabulary of structural names from the export (`Parameter/@type`, `Boolean/@type`, `List/@name`, step names). When a redacted value equals one of those words, don't count its occurrences in label and parameter fields as leaks.
    - (b) Don't redact a literal that equals its own slot's parameter type name. It's almost certainly a placeholder, not a secret.
    - (c) Both.
    - Recommendation: (c). (b) avoids the redaction where it is clearly a placeholder. (a) keeps the guard from failing on any remaining coincidence, and it still fails on real leaks in text fields.
- [ ] Tests:
    - the `by_type/second_file` build passes the guard
    - a real-looking key in Configure AI Account is still redacted
    - the account name is handled per B2 (or left alone)
    - a value equal to a parameter type name, appearing in an unrelated text field, is still caught as a leak

### B2. Scrub hardcoded account names in every step slot that takes one

**Goal.** Know every script-step slot where a developer can type an account name. Then redact a **hardcoded literal** there (category `account_name`), and leave variables (`$account`) and field references (`Users::Name`) as they are.

This extends the existing structural rules in `scrub/structural.py`, which already do this by slot for passwords: `<Parameter type="Password">` → `password_parameter`.

**Census so far.** From `samples/by_type/whole/EverythingBagel.xml`, which holds one of nearly every step. Many steps were saved without their options set, so their account slot doesn't appear in the XML.

| Step (id) | Account slot seen in sample | Kind of account | Status |
|---|---|---|---|
| Configure AI Account (212) | `LLMAccountName` (calc) | AI account label | confirmed |
| Configure RAG Account (227) | `RAGAccountName` (calc) | RAG account label | confirmed |
| Generate Response from Model (220) | `LLMAccountName` (calc) | AI account label | confirmed |
| Fine-Tune Model (213) | `FineTuneAccountName` (calc) | AI account label | confirmed |
| Insert Embedding (215) | none: options not set | AI account label | **need the step configured** |
| Insert Embedding in Found Set (216) | none | AI account label | **need the step configured** |
| Perform Semantic Find (218) | none | AI account label | **need the step configured** |
| Perform RAG Action (219) | none | RAG account label | **need the step configured** |
| Perform Find by Natural Language (221) | none | AI account label | **need the step configured** |
| Perform SQL Query by Natural Language (214) | none | AI account label | **need the step configured** |
| Configure Prompt Template (226) | none | probably none | verify |
| Add Account (134) | none (only `AccountType`, privilege set, `Expire password`) | FileMaker login | **need the step configured** |
| Delete Account (135) | none | FileMaker login | **need the step configured** |
| Reset Account Password (136) | only `Password` | FileMaker login | **need the step configured** |
| Re-Login (138) | only data source + `With dialog` | FileMaker login | **need the step configured** |
| Enable Account | **step missing from sample** | FileMaker login | **add to sample** |
| Change Password (83) | only `With dialog`; it takes old and new passwords, no account name | none | verify |
| Send Mail (63), via SMTP | no SMTP options set | SMTP user name | **need SMTP configured** |
| Execute SQL (117), ODBC | no ODBC options set | ODBC user name | **need ODBC configured** |
| Import Records (35), ODBC source | no ODBC options set | ODBC user name | **need ODBC configured** |
| Insert from URL / Open URL / Trigger Claris Connect Flow | `URL`, cURL options | user in `--user` or in the URL | already covered by positional cURL rules; confirm user-only redaction |

**Work.**
1. [ ] **Complete the census sample** (FileMaker, by hand). In a copy of EverythingBagel, configure each step marked "need …" above with a **hardcoded literal** in every account, user, password and key slot. Use obviously fake values (`"acct-literal-<step>"`).
    - Add Enable Account.
    - Add a second copy of each step that uses a `$variable`, and a third that uses a field reference.
    - Re-export all three sample types.
2. [ ] **Census script.** Add `tests/tools/step_slot_census.py`. It lists, per step id, every `Parameter/@type` that holds a calc, plus every non-calc attribute holding text. Run it on the new sample and record the result in `docs/scrubbing.md` as the slot table. The table is the source of truth for the rule.
3. [ ] **Rule.** Add an `ACCOUNT_NAME_SLOTS = {(step_id, parameter_type), …}` table in `scrub/structural.py`. In `_structural_rule`, a match returns `("account_name", "account_slot", "<step> account name")`. Handling by value shape (existing `_resolve`):
    - **literal** → redacted
    - **`$variable` / field reference** → left as written (decision B2-D2)
    - **expression** (`"svc_" & Get(...)`) → redact its string pieces, as passwords do
    - Some slots may be plain attributes rather than calcs (SMTP and ODBC user names). Check whether the walker exposes them as slots; if not, extend `scrub/walker.py`.
4. [ ] **Level (decision B2-D1).** Today account and modified-by names are scrubbed only at `--scrub-level strict` (`scrub/policy.py:13`, `walker.py:42`).
    - Recommendation:
        - **FileMaker login, SMTP and ODBC user names** → `secrets`. A hardcoded login name next to a hardcoded password is half the credential.
        - **AI/RAG account labels** → `standard`. They name a configuration, not a person or a login.
    - Either way, the redactions report shows the category.
5. [ ] **Keep the placeholder numbering consistent.** The same account name in the Accounts catalog (strict) and in a Re-Login step (secrets) must get the same placeholder, `[REDACTED:account_name#n]`, when both are scrubbed. Check that `registry` keys by value, not by category.
6. [ ] **Tests** (one per row of the census table, generated from the table):
    - a literal is redacted
    - `$var` is untouched
    - a field reference is untouched
    - an expression's string parts are redacted
    - the guard passes on the full sample
    - the coverage report (`--coverage`) still shows every step complete
7. [ ] **Docs.** Add the slot table and the level rule to `docs/scrubbing.md`. Update the list at line 54 ("password parameters … Configure AI / RAG Account").

**Open questions.**
- B2-D1: which level for each kind of account (above).
- B2-D2: should a `$variable` be traced back to its Set Variable and redacted there, as passwords are (`structural.py` `_trace`)? Your rule as stated keeps variables and field references. The trade-off is that `Set Variable [$acct; "admin"]` → `Re-Login [$acct]` leaves `"admin"` visible. Recommendation: trace for FileMaker login slots, don't trace for AI labels.
- Does FileMaker store any account slot as a plain attribute rather than a calc (likely for SMTP/ODBC)? The census answers this.
