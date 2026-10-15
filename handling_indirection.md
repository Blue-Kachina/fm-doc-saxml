# Handling indirection: roadmap and brainstorm

Date: 2026-10-15. Source: `samples/has_indirection/` (`DRCC.xml` 52 MB, `DGC_UAT.xml` 209 MB, `Summary.xml`). These are two files of one hosted solution.

## Status (2026-10-15): Phases 0–7 built, uncommitted

User docs: [docs/indirection.md](docs/indirection.md). Tests: `tests/test_indirection.py` (39, including 3 WebMCP browser tests); full suite 1,050 passed.

| Phase | Where | Notes |
|---|---|---|
| 0 Fixtures | `tests/test_indirection.py` (synthetic XML built in the test) | `samples/has_indirection/` is now in `.gitignore`. The census script stayed in the session scratchpad and was not added as `tools/` |
| 1 Sinks + classes | `analyze/indirection.py`, `analyze/calc_ast.py`, `model/indirection.py` | Runs at the end of `resolve_references`. Uses the scrub lexer, not the ChunkList token stream (see below) |
| 2 Literal linking, pages | `ReferenceRecord.via="byName"` + `siteDocId`; `render/markdown/by_name.py`, `_by_name*.md.j2`, `Reports/indirection.md` | "Used By" tables show direct references only; `UNUSED_FIELD_CANDIDATE` counts by-name use |
| 3 Variables + CFs | same | Flow-insensitive. CF roles (wrapper / capture / ID resolver / name lookup) are stored in `CustomFunctionEntity.name_role` |
| 4 Parameters + callbacks | same | Perform Script, button and trigger callers. An unset `$local` is treated as the parameter key of the same name (`#Assign`) |
| 5 ExecuteSQL | `_sql_identifiers` | Also handles `Substitute` SQL templates and `List` |
| 6 Tooling | `analyze/rename.py`, `fm-saxml rename-check`, diff "Names Still Using an Old Name", WebMCP `find_indirection` / `rename_impact` / `includeByName` | Diff pairs renames by UUID / FileMaker id |
| 7 Docs | `docs/indirection.md`, README, README_technical, docs/html-viewer.md | `fm-doc-saxml.skill` not updated: it's an old archive that predates most features |

Results on the samples:

| | Sites | B | C | D | E | A | A′ | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| DRCC | 165 | 20 | 40 | 41 | 2 | 53 | 9 | Both E are real rename breaks: `Refresh Object` on `bb_communication_drcc` / `bb_receipt_missing_receipt_payable_to_flt`; the objects are now `…_drcc_only` / `bb_receipt_missing_payable_to_flt` |
| DGC_UAT | 1,073 | 416 | 69 | 165 | 34 | 361 | 28 | 302 of the ExecuteSQL calls are safe captures through SQLField/SQLTable templates |

Analysis time is negligible: DGC_UAT parse 19.9 s vs 19.7 s without it; full `--webmcp` build 6:36 vs 6:25.

Deviations from the plan below:
- Sinks are found with the scrubbing lexer (`scrub/calc_lexer.py`) plus a small parser, not FileMaker's ChunkList tokens. The lexer gives the same protection from comments and strings, works on v1 exports and `model.json`, and doesn't keep a token stream for every calc in memory.
- Basic and deep analysis are not split: everything always runs (§8 Q1 answered by the timings).
- Bare-equality literals (§4.3 level 4) are not reported at all (§8 Q2).
- By-name links count as usage, and are kept out of the "Used By" tables (§8 Q3).
- `$$globals` are traced across the file and capped at 48 alternatives per expression (§8 Q4).

This file is both the roadmap and the place to brainstorm. Add ideas under **§7 Brainstorm** and decisions under **§8 Open questions**.

---

## 1. The goal

A colleague wants to rename fields, scripts, layouts and other objects to match a naming standard. Today they can't tell what will break. FileMaker updates *direct* references on rename, because a `FieldRef` in a calc is stored by ID. It does **not** update a name that lives inside a string. So the question we need to answer for any entity is:

> "If I rename X, which places refer to X **by name**, and which places *might*?"

The aim is to show indirection links in our output (Markdown, JSON, HTML viewer) and in our tooling (WebMCP, CLI), each with an honest confidence level.

Indirection is broader than `GetField`. Anything that names a schema object in a string counts: fields, table occurrences, base tables, layouts, scripts, value lists, layout objects and windows.

---

## 2. What the samples contain

These numbers come from a throwaway census script (regex over calc `<Text>` and step XML). They count calc *sites*, not ChunkLists. ChunkLists are de-duplicated by hash, so `FunctionRef` counts are lower. Treat these numbers as orders of magnitude, not test oracles.

| Pattern | DRCC | DGC_UAT | Class (§3) |
|---|---:|---:|---|
| Calculations (all `<Text>`) | 20,355 | 67,561 | |
| `GetFieldName ( TO::field )` | 40 | 306 | **A** safe capture |
| Calls to SQL helper CFs (`SQLField`, `SQLTable`, …), which wrap `GetFieldName` | 20 | 272 | **A** safe capture |
| `Get ( ScriptName )` used as a script parameter or callback | 401 refs | 390 refs | **A** (self-reference) |
| ID-based CFs (`getScriptName ( 387 )`, `getLayoutName`, `getFieldNameFromID`) | 9 calls | 2 calls | **A′** survives a rename, but not delete and recreate |
| `ExecuteSQL ( "…literal…" )` | 9 | 186 | **B/A** depends on whether the literal or helper CFs name the tables |
| …of which query `FileMaker_Tables` / `FileMaker_Fields` by ID | most | 4+ | **A′** |
| `Get ( LayoutName / LayoutTableName ) ≠ "literal"` | 1 | 26 | **B** hardcoded |
| `ValueListItems ( …; "VL" )` | 1 | 22 | **B** (already parsed by `CalcRefResolver`) |
| `GetLayoutObjectAttribute ( "obj" ; … )` | 1 | 0 (+19 dynamic) | **B** |
| String literal = a qualified `TO::field` name | 0 | **78** | **B** hardcoded |
| String literal = a layout / script / TO name (unfiltered, noisy) | 35 / 89 / 1 | 913 / 798 / 95 | **B?** many false positives |
| `GetField ( $var )` | 7 | 44 | **C** dynamic |
| `Evaluate ( … )` | 2 | 40 (23 on literals, mostly inside CFs) | **C/D** |
| Set Field By Name | 3 | 21 | **C** (target is always a calc) |
| Perform Script, script chosen by name | 49 (`$callbackScriptName`) | 7 | **C** |
| Perform Script on Server, script chosen by name | 12 (3 are `Get(ScriptName)`) | 7 (5 are `Get(ScriptName)`) | **A** / **C** |
| Go to Layout, layout name from a calc | 4 | 8 | **C** (`$$layoutOriginal`, `$searchType & " Advanced Search tabs"`, `GetValue ( Members::zg_ReportSelection ; $i )`) |
| Go to Layout, layout number from a calc | 1 | 34 | **C**. Fragile in a different way: breaks on reorder, not rename |
| Go to Object (literal / calc) | 11 / 17 | 276 / 40 | **B** / **C** for layout object names |
| `<Table Missing>::<Field Missing>` in a by-name target | 0 | 2 | **E** already broken |

### Patterns worth designing for

- **Callbacks.** In DRCC, `"callbackScriptName" ; Get ( ScriptName )` appears 38 times. The callee then runs `Perform Script [ By name: $callbackScriptName ]`. The script name gets resolved through the parameter JSON, so following it takes inter-script data flow (Phase 4).
- **Field name captured into JSON.** For example, `JSONSetElement ( "{}" ; [ "targetField" ; GetFieldName ( INTERFACE::beneficiaryFormEnglish ) ] )` on a layout object's OnObjectModify trigger. The script then does `Set Field By Name [ $targetField ]`. The capture survives a rename, but **the target only appears if we join the two ends**.
- **Hardcoded JSON config.** For example, `[ "fieldName" ; "Members::communicationPreferencesDues" ]` next to `[ "objectName" ; "PREF_DUES" ]`. This breaks on rename, and it names a layout object too.
- **Mapping-driven integrations.** For example, `Set Field By Name [ Get ( LayoutTableName ) & "::" & JSONGetElement_Safe ( $mapping ; "filemaker_field" ) ]`. The field names are in data, not in the file. We can find these sites but never resolve them.
- **Partial names.** `$searchType & " Advanced Search tabs"` names a *family* of layouts. A pattern match (`* Advanced Search tabs`) against the layout catalog gives useful candidates.
- **Self-referencing names.** `Perform Script on Server [ Get ( ScriptName ) ]` is a *safe* by-name call. It must not be reported as a risk.
- **Lookalike literals.** `"Yes"` matches a value list name, `"Find"` a script, `"Members"` both a TO and a layout, and `"container"` a layout object. Matching any literal that equals an entity name gives hundreds of false positives. **Context decides confidence (§4.3).**

---

## 3. Classes of indirection

Every finding is a **site**: the place that consumes or produces a name. Each site gets one class.

| Class | What it is | Breaks on rename? | What we show |
|---|---|---|---|
| **A: Safe capture** | A name produced from a real reference: `GetFieldName ( T::f )`, `Get ( ScriptName )`, `SQLTable ( T::f )`, `Get ( LayoutTableName )` used only as the current context | No | "Captured by reference". Reassures; shown, not alarmed |
| **A′: ID-based** | Resolved by internal ID: `FileMaker_Fields WHERE FieldID=?`, `getScriptName ( 387 )` via `ScriptIDs` | No (yes on delete and recreate, or import into another file) | Resolve the ID to the entity when we can |
| **B: Hardcoded literal** | The name as a string literal used where a name is expected | **Yes** | High-risk link to the named entity |
| **C: Dynamic, resolvable** | A variable, parameter or expression whose possible values we can trace back to A or B | Depends on the source | Candidate links with an evidence chain |
| **D: Opaque** | The name comes from data: field contents, records, a JSON mapping from an API, `Evaluate ( SomeTable::formula )` | Unknown | Site only. Flagged as "cannot be verified statically" |
| **E: Broken** | A literal or trace that resolves to nothing, or `<Field Missing>` | Already broken | Warning |

Class **B** is the colleague's main problem. Class **C** is the "scared" part: the risk exists, but the target is unknown. Class **D** is the honest limit, and the report should say so clearly instead of implying full coverage.

---

## 4. Design

### 4.1 Where it lives in the pipeline

The new analyzer, `analyze/indirection.py`, runs after `resolve_references` and `build_variables`. It needs the variables index and the resolved catalogs, and it runs before `generate_backlinks` and `generate_warnings`. That way the new edges show up as backlinks, and `UNUSED_FIELD_CANDIDATE` stops flagging fields that are only used by name.

Building blocks we already have:

- **ChunkLists** (`parser/extractors/chunk_lists.py`) already tokenize every calc into `FunctionRef`, `FieldRef`, `VariableReference`, `CustomFunctionRef` and `NoRef` chunks, with comments split out. Use them to find sinks (`FunctionRef` = `GetField`) so that comments and strings never produce false hits. Today `_chunk_refs` drops everything except `FieldRef` and `CustomFunctionRef`. Phase 1 keeps an ordered token stream.
- Fall back to `scrub/calc_lexer.py` when there is no ChunkList (v1 exports, calcs that didn't tokenize). This is the same fallback rule `CalcRefResolver` uses.
- `normalize/variables.py` already records every set and read of `$x` / `$$x` by script and step. That is the start of the data flow.
- The `ReferenceRecord` confidences `parsed` and `inferred` already exist and have no producer for this purpose yet.

### 4.2 Sinks (where a name is consumed)

| Sink | Name kind | Argument |
|---|---|---|
| `GetField`, `GetFieldName` on a string, `GetRepetition (GetField…)`, `FieldType`, `FieldStyle`, `FieldRepetitions`, `FieldBounds`, `FieldComment` | field (`TO::f` or bare `f` = current layout TO) | 1st, or 2nd for `Field*` (`FieldType ( file ; "TO::f" )`) |
| `Evaluate` | any (an expression string) | 1st. Parse the evaluated literal as a calc, recursively |
| `ExecuteSQL` | TO / field (SQL identifiers) | 1st (SQL text) |
| `ValueListItems`, `ValueListNames`-driven loops | value list | 2nd |
| `GetLayoutObjectAttribute`, `Get ( ActiveLayoutObjectName ) = "…"` | layout object | 1st / comparison |
| `Get ( LayoutName ) = "…"`, `Get ( LayoutTableName ) = "…"`, `Get ( ScriptName ) = "…"`, `Get ( ActiveFieldName ) = "…"` | layout / TO / script / field | comparison operand |
| `FieldNames`, `LayoutNames`, `ScriptNames`, `LayoutObjectNames`, `TableNames`, and the `…IDs` variants | catalog *enumeration*. The consumer then filters by name | note, not a link |
| Step **Set Field By Name** | field | target calc |
| Step **Perform Script** / **Perform Script on Server**, `By name` (`<List name="By name" value="2">`) | script | the calc |
| Step **Go to Layout**, `LayoutReferenceContainer value="3"` (by name) / `"4"` (by number) | layout | the calc |
| Step **Go to Object**, Refresh Object, Go to Field (calc repetition only) | layout object | `<Name>` calc |
| Steps **Select Window**, Close Window, New Window (by name) | window name | not schema, but worth listing (§7) |
| Open URL / Insert from URL with `fmp://…?script=` or a Data API path `/layouts/<name>/` | script / layout | URL literal |
| Custom functions whose body passes a parameter into one of the sinks above | inherited | §4.5 |

### 4.3 Confidence for literals

A literal only becomes a link when **its position** says a name is expected. Ranked from high to low:

1. **Sink argument:** the literal is the argument of a sink in §4.2. → `parsed`, risk B.
2. **Comparison with a name getter:** `Get ( LayoutName ) = "Members"`. → `parsed`.
3. **Name-like JSON key:** a literal value next to a key such as `fieldName`, `targetField`, `scriptName`, `layout`, `objectName` or `callback*`. The key list is configurable. → `inferred`.
4. **Bare equality:** the literal equals an entity name and nothing else is known. → `inferred` and **off by default**. Enable it per kind, and only for distinctive names (contains `::`, or longer than N characters, or not an English word). This keeps "Yes" and "Find" out.

Matching rules: FileMaker names are case-insensitive. Trim whitespace. A bare `field` (no `TO::`) resolves against the layout's TO when the step's layout context is known; otherwise it is a candidate in every TO that has that field.

### 4.4 Data flow for dynamic sites (class C)

The goal is a **small abstract evaluator, not a FileMaker interpreter.** It turns an expression into a set of *name shapes*:

- literal `"X"` → `{X}`
- `GetFieldName ( T::f )` → `{T::f}` (safe origin)
- `Get ( ScriptName )` → `{current script}` (safe)
- `getScriptName ( 387 )` → resolve through `ScriptIDs` order when the CF is recognized (A′)
- `a & b` → concatenation of shapes. An unknown part becomes a wildcard: `$t & " Advanced Search tabs"` → `* Advanced Search tabs`
- `Case`, `If`, `Choose`, `List` → union of the branches
- `$x` → union of every value assigned to `$x`. For locals, that is the same script. For `$$globals`, the whole file, and the output says so. Flow-insensitive to start with.
- `JSONGetElement ( Get ( ScriptParameter ) ; "key" )` → **parameter key**. Phase 4 maps it to each caller's Perform Script parameter where `"key"` is set (the `callbackScriptName` pattern).
- A field read (`Globals::gTableName`, `Members::zg_ReportSelection`) → **D, opaque**. If that field has an auto-enter or a value list of literal names, add those as candidates (§7).

Then match the shapes against the catalog for the sink's name kind: exact names → `parsed`, wildcard patterns → `inferred` with a count. If a pattern matches more than K entities (say 25), downgrade it to D ("matches 140 layouts").

Every candidate keeps its **evidence chain**: `Step 12 Set Field By Name [$targetField]` ← `$targetField` set at step 3 from `JSONGetElement(param; "targetField")` ← caller `Layout "Upload" › object uploadBenFormENG › OnObjectModify` → `GetFieldName ( INTERFACE::beneficiaryFormEnglish )`. This chain is what a person reviewing a rename needs to see.

### 4.5 Custom functions

Compute a per-CF summary once, iterating until nothing changes, because CFs call CFs:

- **Capture CF:** a parameter flows only into `GetFieldName` (`SQLField`, `SQLTable`, `SQLGetFieldName`, `GetFieldName_FieldNameOnly`). Calls behave like class A for the field passed in.
- **Sink CF:** a parameter flows into `GetField` / `Evaluate` / `ExecuteSQL` text (`#Assign`, `CustomList`, `VirtualSort*`). Every call site becomes a sink of that kind.
- **ID-resolver CF:** the body uses `ScriptIDs` / `LayoutIDs` / `FieldIDs` / `FileMaker_*` tables with an ID parameter (`getScriptName`, `getLayoutName`, `getFieldNameFromID`). Calls with a literal ID resolve to an entity (A′).

The CF page shows its role ("Wraps GetField on parameter `field`. 44 call sites inherit this."). Automatic detection may misclassify; config can override it.

### 4.6 ExecuteSQL

Split the SQL argument into literal pieces and expression pieces. Pieces from helper CFs (`SQLTable ( T::f )`) are class A. For the literal pieces, run a small tokenizer, not a full parser and no new dependency, that finds the identifier after `FROM` / `JOIN` / `UPDATE` / `INTO`, plus column identifiers (quoted `"x"` or bare). Resolve tables against **TO names** (FileMaker SQL uses TOs) and columns against that TO's fields. `FileMaker_Tables`, `FileMaker_Fields` and `FileMaker_BaseTableFields` are system tables: mark them as metadata queries (A′), not links.

### 4.7 Model and output

**Model** (`model/references.py` and a new entity):

```python
class IndirectionSite(BaseModel):
    doc_id: str                 # stable: "<source docId>#ind<n>"
    source_doc_id: str          # step / field / layout object / CF / menu item
    script_doc_id: Optional[str]; step: Optional[int]
    sink: str                   # "GetField", "SetFieldByName", "PerformScriptByName", "GoToObject", ...
    name_kind: str              # field | script | layout | tableOccurrence | valueList | layoutObject | window
    expression: str             # the argument text (scrubbed)
    klass: Literal["A", "A'", "B", "C", "D", "E"]
    candidates: list[IndirectCandidate]  # target_doc_id, confidence, shape, evidence: list[str]

# ReferenceRecord gains:  via: Literal["direct", "byName"] = "direct"   (+ site_doc_id)
```

We keep the existing relationship types (`usesField`, `usesScript`, `navigatesTo`, …) and add `via="byName"`. That way every existing backlink view, `find_references` and the diff pick these links up with no new code, and filters can still exclude them.

**Outputs:**

1. **`Reports/indirection.md`**: counts by class × sink × name kind. Then a ranked "rename risk" table: entities with B and C links, most at-risk first. Then opaque sites grouped by script. Link it from `summary.md`.
2. **Entity detail pages** (field, TO, layout, script, value list, layout object) get a new section:
   - *Referenced by name (breaks on rename)*: B links
   - *Possibly referenced by name*: C candidates with confidence and a collapsed evidence chain
   - *Name captured safely*: A, shown collapsed
3. **Script pages:** steps that are sinks get a marker (`⟲ by name`) and a short note (`→ 3 candidates`, `→ opaque`).
4. **CF pages:** the CF summary role (§4.5).
5. **JSON:** `indirectionSites[]`, plus `via` on references. The JSON schema version is bumped.
6. **Warnings:** `BYNAME_TARGET_MISSING` (B or E: the literal names nothing), `BYNAME_OPAQUE` (count only, not one warning per site).
7. **Coverage report:** one row for "by-name sites resolved / opaque".

**Scrubbing:** the expression and evidence text must come from the **scrubbed** calc text (literals can hold secrets). Name matching can use the raw text, because names are schema, not secrets. `guard_output` already catches leaks.

### 4.8 Tooling

- **WebMCP** (`webmcp.js`):
  - `find_indirection { klass?, sink?, nameKind?, scriptDocId? }` lists sites, and the results view works as it does for other query tools.
  - `rename_impact { docId }` is the main feature. It returns direct references (FileMaker fixes these), B links (must edit), C candidates (review), and D sites that *could* reach the entity (same name kind and same base table context). `find_references` gains an `includeByName` flag that is on by default.
- **CLI:**
  - `fm-saxml rename-check <xml> "Members::Email"` prints the same impact report in the terminal.
  - `--rename-plan plan.csv` (old,new rows) writes one checklist for a whole naming-standard migration. It also catches *collisions*, where the new name equals an existing literal elsewhere.
- **Diff** (`analyze/diff.py`): when an entity's name changed between two exports (same ID or UUID), list B literals in the new export that still use the **old** name ("stale by-name references"). This checks the colleague's rename after it is done.

---

## 5. Roadmap

### Phase 0: Fixtures and census (blocking)
- Add a synthetic fixture, `tests/fixtures/indirection.xml`, hand-built from the shapes in §2: callback JSON, GetFieldName into Set Field By Name, hardcoded `"TO::f"` in JSON, `Go to Layout` by name with a wildcard, Go to Object literal, ExecuteSQL with and without helper CFs, ID CFs, `Evaluate`, an opaque mapping, a missing target, and lookalike literals ("Yes", "Find").
- Turn the census script into `tools/indirection_census.py` (dev-only, not shipped) so we can rerun it on any export and see before/after numbers.
- Ignore `samples/has_indirection/`.

### Phase 1: Find and classify sinks (no data flow)
- Keep the ordered chunk stream per calc, and fall back to `calc_lexer` when there is none.
- Detect every sink in §4.2, including the step options (`By name` value 2, `LayoutReferenceContainer` 3 and 4, `Go to Object <Name>`).
- Classify each site using only its own expression: literal → B, safe origin → A, anything else → C, not yet resolved.
- Output: `IndirectionSite` in the model and JSON, `Reports/indirection.md` (counts and site list), and step markers.
- Done when: the fixture shows every class, and DGC_UAT's counts are in the same range as §2.

### Phase 2: Link hardcoded literals (class B), then entity pages
- Resolve B literals and comparison literals (§4.3, levels 1–2) against the catalogs, plus the case-insensitive and current-TO rules.
- Emit a `ReferenceRecord(via="byName")`. Add backlinks, the new detail-page sections and `BYNAME_TARGET_MISSING`.
- Make `UNUSED_FIELD_CANDIDATE` count by-name links as usage.
- Done when: the 78 qualified-field literals in DGC_UAT each land on the right field page, or get a warning.

### Phase 3: Variables and custom functions
- Build the shape evaluator (§4.4) for literals, `&`, branches, `GetFieldName`, `Get(ScriptName)` and `$var` through the variables index.
- Add CF summaries (§4.5), including capture, sink and ID-resolver roles, and config overrides.
- C sites gain candidates and evidence chains. Wildcard patterns are matched against catalogs with the K limit.

### Phase 4: Script parameters and callbacks
- `JSONGetElement ( Get ( ScriptParameter ) ; key )` and `GetValue ( Get ( ScriptParameter ) ; n )` link to callers' Perform Script parameters, script trigger parameters, button parameters and custom menu items.
- Handle the callback convention (`callbackScriptName` = `Get ( ScriptName )` of the caller), resolving to the set of callers.
- Done when: DRCC's 49 `$callbackScriptName` Perform Script steps show their candidate scripts.

### Phase 5: ExecuteSQL
- Tokenizer, TO and column resolution, and system-table recognition (§4.6).

### Phase 6: Tooling
- WebMCP `find_indirection`, `rename_impact` and `find_references.includeByName`, with Playwright tests like `test_webmcp.py`.
- CLI `rename-check` and `--rename-plan`.
- Diff: stale by-name references.

### Phase 7: Docs
- `docs/indirection.md`: the classes, what is and is not detected, how to read confidence, and the D limits. Add a section to the README and the agent skill guidance (`fm-doc-saxml.skill`).

**Suggested order:** 0 → 1 → 2 gives the colleague a useful report quickly, because B is their biggest risk. 3–4 cover most of C. 5 and 6 can run in parallel after 2.

---

## 6. Performance

DGC_UAT has ~67k calcs. Phases 1–2 are a single pass over calcs we already parse, so they should be cheap. Phase 3–4 data flow is bounded per variable. Memoize the shape of each variable, and cap the union size; past the cap, the result is a wildcard. Measure against the multi-file perf numbers already recorded. If the cost is noticeable, put Phases 3–5 behind `--indirection=deep` (with `basic` as the default), the same opt-in model as `--coverage`.

---

## 7. Brainstorm (add freely)

- **Fix suggestions.** For every B site, propose the safe form: `"Members::Email"` → `GetFieldName ( Members::Email )`, and `Perform Script [ By name: "X" ]` → choose the script from the list. Output a "make this solution rename-safe first" checklist so the colleague can harden the file *before* renaming.
- **Value lists as name sources.** `Go to Layout [ GetValue ( Members::zg_ReportSelection ; $i ) ]`: if the field uses a value list with custom values, those values are candidate layout names. Several opaque sites would become class C.
- **Auto-enter and calc fields that hold names.** If `Globals::gTableName` has an auto-enter literal or is set by `Set Field [ Globals::gTableName ; "Members" ]` somewhere, trace it like a variable (field writes from `writesTo` refs).
- **Optional data probe.** For D sites that read stored names (mapping tables, config records), an opt-in mode could read those values from a live file through proofkit-mcp `execute_filemaker_sql`. This is outside the SaXML-only promise, so it would be a separate tool.
- **Cross-file.** Can Perform Script by name or Data API URLs target another file of the solution? If yes, join with `batch/links.py` (same `external` confidence as today).
- **Outside the file.** Data API, OData, ODBC, PHP and web viewers call layouts and scripts by name and are invisible to us. Detect hints (`Insert from URL` to `/fmi/data/…/layouts/<name>`, `fmp://` URLs) and always print a fixed disclaimer in the rename report.
- **Layout object names and window names** are names too. A naming standard often covers objects ("btn_…", "tab_…"). Go to Object (316 sites in DGC_UAT) and `GetLayoutObjectAttribute` deserve the same treatment as fields.
- **Number-based indirection** (`Go to Layout [ by number ]`, 35 sites, `Get ( LayoutNumber )`) is not a rename risk but a *reorder* risk. Should the report have a "reorder risk" section too?
- **Visualization.** In the HTML viewer, show a small graph per entity: direct links solid, by-name dashed, candidates dotted.
- **Agent mode.** `rename_impact` makes an agent able to say "safe to rename" or "edit these 4 places first". Combine it with `navigate_to` so the agent can walk a person through each site.
- **Confidence calibration.** After Phase 3, sample about 50 C candidates from DGC_UAT and grade them by hand. Tune K, the JSON key list and the bare-equality rules from those grades.

---

## 8. Open questions

1. **Default on or opt-in?** Basic (Phases 1–2) on by default, with deep (3–5) behind a flag? See §6.
2. **Bare-equality literals (§4.3 level 4):** never, opt-in, or on for `::`-qualified strings only? The samples suggest "qualified only" by default.
3. **Should `via=byName` links count in existing reference totals** (`summary.md` counts, `find_unreferenced`)? Proposed: yes for usage, and keep them as a separate count in the summary.
4. **Global variables:** a flow-insensitive union over the whole file can be very wide (DGC_UAT has ~1,570 `Set Variable $$…`). Cap it, or mark it as D?
5. **Commented-out code** (`"//Productions::Status = …"` inside strings that build code for `Evaluate`): parse it, or ignore lines that start with `//`?
6. **Rename plan input format:** CSV old,new, or JSON with entity kind? It should match whatever the colleague's naming-standard tooling produces.
7. **Do Perform Script by name or Data API paths reach other files?** This decides whether Phase 4 needs the batch linker.
