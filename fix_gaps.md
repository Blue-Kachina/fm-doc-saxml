# Fix Gaps — roadmap from the competitor comparison

Date: 2026-10-14. Source: a colleague noticed some gaps in our output.

## 1. Verification

I couldn't reproduce the colleague's exact counts (1,072 comments, 1,112 Set Variable, 377 grouped buttons). None of the local samples match those numbers, so they probably used a different file. I checked every claim against the parser code and against a fresh `fm-saxml build` of `NEXUS_saxml.xml` (124 scripts, 8,567 steps), with `disRenewalUniverse.xml` as a second file. **Every claim holds.** Several of the gaps are larger than reported.

| Claim | Verdict | Evidence (NEXUS unless noted) |
|---|---|---|
| 0 comments rendered | **Confirmed** | 3,692 comment steps, 1,818 of them with text. Each renders as the bare `# (comment)`. The text is in `<Parameter type="Comment"><Comment value="…">`, an attribute that the parser never reads. |
| 0 Set Variable names | **Confirmed** | 1,058 steps. `_variable_name()` *does* capture `$name` and normalize stores it in `parameters.variable`, but `raw_text` never includes it. The renderer only shows `raw_text`, so the name is lost. The output also appends the repetition calc: `Set Variable [ Get ( ScriptParameter ) 1 ]`. |
| No Set Field values | **Confirmed** | 457 steps. `raw_text` uses the first match from `layout_ref → field_refs → script_ref → calc`, so as soon as a field ref exists the calc is never shown. 448 non-trivial Set Field calcs are missing. |
| ~17% of step calcs cut off or missing | **Confirmed, and worse here** | Of 3,224 non-repetition step calcs, **14.4% are truncated** (`calc[:80]` in the parser plus `truncate(120)` in the template) and **19.1% are missing entirely**: Set Field, Perform Script parameters, New Window, Replace Field Contents, Insert from URL, PSoS and others. |
| 0 grouped-button actions | **Confirmed** | `_parse_layout_object` looks only for `<Button>` and `<PopoverButton>`. Grouped buttons store their action in `<GroupedButton><action>`. NEXUS has 2 grouped buttons and both actions are lost. Ordinary buttons and button-bar segments work (265 of 265 real actions; the other 67 `<action>` elements are empty). |
| Used scripts look like dead code | **Confirmed (follows from the above)** | A script called only from a grouped button gets no inbound reference. Its page has no "Referenced By" entry and backlinks treat it as unused. The fields and layouts those actions reference also lose their references, which can trigger false `UNUSED_FIELD_CANDIDATE` warnings. |
| Value list contents missing/wrong | **Confirmed** | (a) `Source value="External"` (a value list from another file) becomes `customValues` with 0 values (disRenewal `ChargeCompte_Synapse`). (b) `ShowRelated` (“include only related values starting from TO X”) is dropped, so `Item Line` and `Item Line filtered` look identical. (c) The primary/secondary `show`/`sort` flags are dropped. (d) The source field is shown by base table, not by the TO it is pulled through. (e) Custom values are `strip()`ped and blank lines are removed. |
| Privilege sets missing | **Confirmed** | `extract_privilege_sets` keeps only the name and description. The whole `<access>` block is discarded: Records (including the custom per-table View/Edit/Create/Delete/Fields matrix), Layouts, ValueLists, Scripts and `<Other>` (print, export, manage*, menu commands, disconnect idle, password change). |
| Relationship options wrong | **Confirmed: always `false`** | The extractor reads a `<Options>` element that v2 never emits. The real data is per side: `<LeftTable cascadeCreate cascadeDelete>`, `<RightTable …>` and a `<SortSpecification>` under the side. NEXUS has 7 sides with cascade set and all 7 show `false`. disRenewal has 6 cascades and 6 sort specs, all lost. The model also has only one flag per option, where FileMaker has one per side. |

## 2. Root causes (code locations)

- `src/fm_saxml/parser/extractors/scripts.py:117–172` (`_parse_step`): `raw_text` is a one-line preview built from a single "best" parameter, cut at 80 characters (`:157`). `_extract_v2_step_refs` collects calcs but ignores non-calc parameters (Comment, Boolean, Animation, and so on).
- `src/fm_saxml/render/markdown/templates/script.md.j2:58`: renders only `raw_text | truncate(120)`.
- `src/fm_saxml/normalize/normalize.py:710–711`: keeps only `variable` in `parameters`. Everything else is dropped.
- `src/fm_saxml/parser/extractors/layouts.py:306`: `find_child(lo, "Button", "PopoverButton")` has no `GroupedButton` case.
- `src/fm_saxml/parser/extractors/relationships.py:49–61`: looks for an `<Options>` element that doesn't exist in v2.
- `src/fm_saxml/parser/extractors/privileges.py`: never reads `<access>`.
- `src/fm_saxml/parser/extractors/value_lists.py`: has no `External` branch, ignores `ShowRelated` and the show/sort attributes, and uses lossy `strip()`.
- **Coupling:** the scrubber hard-codes the preview format in `src/fm_saxml/scrub/walker.py:57` (`_STEP_TEXT_WIDTH = 80`, and the `f"{name} [ {basis[:80]} ]"` match at `:226`). `analyze/diff.py:257` uses `raw_text` as the step signature. Any change to step text has to update both.

## 3. Roadmap

Ordered by user impact divided by effort. Each phase ships on its own with tests, and the scrubber stays in step with the parser.

### Phase 1: Script step fidelity (highest impact)

1. **Structured step parameters in the parser.** Have `_parse_step` emit an ordered `params` list built from every `<Parameter type=…>`: `Comment` → text; `Variable` → name, value calc, repetition; `FieldReference` → target plus repetition; `Calculation` → full text; `Boolean`/`Animation`/`Restore`/`SortSpecification` and similar → label/value; plus the existing layout, script and value-list refs, keeping the script parameter calc that belongs to the step.
2. **Model and normalize.** Replace `parameters={"variable": …}` with the full structured list (backward-compatible: keep `variable`). Keep `raw_text` as a *short* preview for the diff and JSON consumers. Bump the model schema version.
3. **FileMaker-style step text.** Add a step-text formatter, in Python and not Jinja, that produces what the Script Workspace shows:
   - `# Start, End Context: Any, Any` (comments shown as comments; a blank comment becomes an empty `#` line)
   - `Set Variable [ $TASK_NAME ; Value: Get ( ScriptName ) ]` (show `[n]` only when the repetition isn't `1`)
   - `Set Field [ CATALOGUE::description ; $value ]`
   - `Perform Script [ "Generic - Centre Card Window" ; Parameter: … ]`
   - A per-step map of templates with a generic fallback (`Name [ p1 ; p2 ; … ]`) so no parameter is ever silently dropped.
4. **Render without truncation.** In `script.md.j2`, render steps as an indented code block (with If/Loop nesting) or keep the table but stop truncating. Put long or multi-line calcs on their own lines, and show disabled steps as `//`. Comments must render in full; that's the biggest visible gap.
5. **Scrubber alignment.** Update `walker.py` (`_STEP_TEXT_WIDTH` and the preview matcher) and `structural.py` so they scrub the new full-text fields. Comment text is now *rendered*, so make sure `scrub/detectors/comments.py` covers the new location. Add a regression test that no secret inside a comment or Set Field calc reaches the Markdown.
6. **Tests.** Add fixtures for a comment, Set Variable with and without a repetition, Set Field with a long multi-line calc, and Perform Script with a parameter. Add a golden test on the rendered step lines. Add an acceptance check against NEXUS: 0 bare `# (comment)` lines where the comment has text; every non-repetition calc appears in full in the Markdown.

7. **Variables section** (added at the user's request). Index every `$local` and `$$global`: where it is set (Set Variable, step `Target:`s, `Let` declarations) and read. Give each global a page, list each script's locals on its page, and add a `Variables/index.md`. Flag locals that are read but never set.

Exit criteria: the 0/1,818 comment, 0/1,058 variable and 0/457 Set Field gaps reach 100%, and truncated or missing calcs fall to 0%.

**Status (2026-10-14): done**, apart from the follow-ups below. Measured with the parser:

| Sample | Step calcs shown | Comments with text shown | Set Variable names shown |
|---|---|---|---|
| NEXUS | 4,824 / 4,824 | 1,818 / 1,818 | 1,058 / 1,058 |
| disRenewalUniverse | 2,442 / 2,442 | 1,457 / 1,457 | 512 / 512 |

What was built:
- **Parser** (`parser/extractors/scripts.py`): `params` per step. Calcs are referenced by index into `calculations`, never copied, so the step text is built from scrubbed calcs, and the scrubber needed no changes. Comment text is scanned as free text by the existing walker; a test proves a password in a comment is redacted in the Markdown.
- **Formatter** (`model/step_text.py`): FileMaker-style text, If/Loop/Transaction indentation, `//` for disabled steps. Used by the script page and by `diff`, which now sees edits past the old 80-character preview. `raw_text` is unchanged on purpose: the scrub walker's preview matching still depends on it.
- **Variables** (`normalize/variables.py`): `VariableEntity` with set/read uses. Pages for globals, a Variables table on each script page, `Variables/index.md`, and counts on the home page and summary. Names are matched case-insensitively, and repetitions are folded into one variable.
- Model `SCHEMA_VERSION` bumped to 0.3.0 (additive: older model.json files still load and render).
- Tests: `tests/test_step_text.py`.

Follow-ups:
- **HTML viewer:** CodeMirror adds its own gutter numbers beside our step numbers. Milkdown doesn't expose a block's language in the DOM, so the fix is a global `.cm-gutters { display: none }` in `render/html/templates/index.html`. That affects calc blocks too, so it's the user's call.
- **Single-step buttons** on layout objects still show the parser's `raw_text` preview. Give `button_step` the same `params` (and the variable index the button's Set Variable targets) as part of Phase 2.
- **Rare complex parameters** (Import/Export field maps, Find requests, sort order details) are summarised as their calcs and references only.

### Phase 2: Grouped-button actions and the dead-code false positives

1. Add `GroupedButton` to the button lookup in `layouts.py:306`. Check how the group's child objects nest (the grouped children are `LayoutObject`s inside the group) so they are still collected.
2. Make sure normalize emits `buttonAction` references for grouped buttons, so scripts, layouts and fields get backlinks.
3. Rather than whitelisting element names, find any `<action>` whose parent is a direct child of the `LayoutObject`, so future button kinds don't go silent.
4. Tests: a grouped-button fixture with Perform Script, and an assertion that the script has a backlink. Re-run NEXUS: 2 of 2 grouped actions captured.
5. Optional follow-up: an explicit `UNUSED_SCRIPT_CANDIDATE` warning, which only becomes trustworthy once 2.1 to 2.3 are done. It should also count script triggers, custom menus, OnFirstWindowOpen and similar file options, and the other file in batch mode.

### Phase 3: Relationship options

1. Read `cascadeCreate` and `cascadeDelete` from `LeftTable` and `RightTable`, and the sort spec under each side.
2. Change the model to per-side options, `left: {allowCreate, delete, sort: [...]}, right: {…}`, with a compatibility shim for the old flat fields.
3. Check operator mapping for the v2 string values (`Equal`, `NotEqual`, `Less`, `LessOrEqual`, `Greater`, `GreaterOrEqual`, `CartesianProduct`) and render them as symbols. Today unknown values are lowercased.
4. Update `relationship.md.j2` to show a two-column options table (left/right) and the sort fields.
5. Tests: a fixture with cascade on one side and a sort on the other. Acceptance: NEXUS 7/7 cascades, disRenewal 6/6 cascades and 6/6 sorts.

### Phase 4: Value lists

1. `External` source: capture the data source and the remote value-list name, and render "Values from *idiClients* › *ChargeCompte_list*". In batch mode, link to the paired file's value list (reuse `batch/links.py`).
2. `ShowRelated`: capture the starting TO and render "Only related values, starting from GLOBALS".
3. Capture the primary/secondary `show`/`sort` flags and render them; also capture the "sort using language" and "show values from second field only" options if they're present.
4. Resolve the source field by **table occurrence**: keep the TO name next to the base-table field link.
5. Keep custom values exactly as written: split on `\r`/`\n` without stripping. Keep blank lines and show them visibly as separators.
6. Tests for each source type, plus the disRenewal acceptance check (the External list is no longer empty or `customValues`).

### Phase 5: Privilege sets

1. Parse `<access>` into: `records` (`all`, `viewAll`, …, or a custom per-table matrix: View/Edit/Create/Delete/Fields, each with its access level and the record-level calc when limited), `layouts`, `valueLists`, `scripts` (all or custom per-object), and `other` (Print, Export, manageDatabase, manageAccounts, manageExtPrivs, manageCustomMenus, allowOverride, allowOpenQuickly, disconnectIdle, menu `commands`, password `prohibitModification`).
2. Link the per-table rows to Table pages and the record-level calcs to their field references. Run those calcs through the scrubber like any other calc.
3. Render a summary table and the custom matrices in `privilege_set.md.j2`. Add the accounts that use each set by reversing `PrivilegeSetReference`.
4. Tests: the default sets `[Full Access]` and `[Data Entry Only]`, and the custom set from disRenewal (14-table matrix).

### Phase 6: Guard against future silent loss

1. **A coverage report** (`Reports/coverage.md`, also usable as a CI check): for each step type, count `<Parameter>` elements seen against parameters rendered. For each LayoutObject type, count `<action>` elements seen against actions captured. Anything unhandled is listed by element name. That makes the next gap of this kind visible before a customer finds it.
2. Run it against the three local samples in the test suite as a non-regression floor.

## 4. Suggested order and size

| Phase | Size | Notes |
|---|---|---|
| 1. Step fidelity | L | Biggest visible win. Touches the parser, normalize, the renderer, the scrubber and diff, so do it first while the scrub layout is fresh. |
| 2. Grouped buttons | S | One-line root cause plus tests. Could ship ahead of Phase 1 as a quick win. |
| 3. Relationships | S–M | Small model-shape change. |
| 4. Value lists | M | |
| 5. Privilege sets | M | New model and template. |
| 6. Coverage report | S–M | Do it right after Phase 1, so Phases 3–5 can be measured. |

Release suggestion: Phase 2 plus Phase 3 as 0.4.x, Phase 1 plus Phase 6 as 0.5.0 (the model schema changes), and Phases 4 and 5 as 0.5.x.

## 5. Second pass (2026-10-14): reassessment against the colleague's full report

The colleague's full report (Synapse, fm-doc-saxml v0.3.0 vs fm-xml-export-exploder v0.8.1) listed 18 gaps and 5 incorrect outputs. After Phase 1, only the script-text gaps were closed. Phase 2 had *not* landed: the commit message said "Grouped buttons recognized", but `layouts.py` still looked only at `Button`/`PopoverButton`. This pass closes the rest.

| Report item | Status | Where |
|---|---|---|
| Comments, Set Variable names, Set Field values, truncated/missing step calcs | Done (Phase 1) | `model/step_text.py` |
| Step options (dialogs, sort order, New Window, custom dialog buttons, export order, Insert from URL target) | **Done**: steps now render FileMaker's own `StepText` from `DDR_INFO` (100% identical on NEXUS and disRenewal, was 72% / 79%). Our own formatter stays as the fallback. The text is scrubbed as a calc (`fm_text` in `_CALC_KEYS`), and the engine's known-value pass keeps it in step with the step's calcs. | `parser/extractors/chunk_lists.py`, `model/step_text.py` |
| Grouped button actions (0/377) and the dead-code false positives | **Done**: any direct child of a LayoutObject holding an `<action>` (NEXUS: 2/2). Single-step buttons now show full step text. | `parser/extractors/layouts.py` |
| Script callers from file triggers (OnFirstWindowOpen) | **Done**: new `FileOptions` on the model; its triggers and default layout are references, so "Called By" shows them | `parser/extractors/file_options.py`, home page |
| File options (default layout, minimum version, login, sharing) | **Done** | home page "File Options" |
| Script options ("Run with full access", menu visibility) | **Done** | script page metadata |
| Relationship options wrong (always "No") | **Done**: per side, with sort order; operators as symbols | `relationships.py`, `relationship.md.j2` |
| Value lists (External typed as custom, related-only, show/sort, source TO, exact values) | **Done**: an External list names the other file's list; the batch link resolver now knows value-list targets (not exercised by our samples, which lack the paired file) | `value_lists.py`, `value_list.md.j2` |
| Privilege sets (ID only) | **Done**: Records/Layouts/Value Lists/Scripts, custom per-object matrices with limiting calcs, Other privileges, Used By | `privileges.py`, `privilege_set.md.j2` |
| Field validation (message, strict, calc-only rules shown as "None") | **Done**: the `<Message>` child was read as an attribute; a rule with only a calc, message or strict type was dropped | `fields.py` |
| Stored vs unstored calcs, "do not evaluate if empty" | **Done** | field page, Storage Options |
| Auto-enter (prohibit modification, do not replace, serial increment / generate) | **Done** | field page |
| Summary fields (operation and target missing for 6/8) | **Done**: v2 nests `<SummaryField>` in `<SummaryInfo>`, which we never looked in | `fields.py` |
| Value list on layout fields (8/61) | **Done**: it was parsed but never rendered; now on the object page and as a column of the layout's object table (with each object's action) | `layout_object.md.j2`, `layout.md.j2` |
| Portal options (rows, sort) | **Done**: rows shown, initial row, sort order with direction; filter was already in Calculations. "Allow deletion" lives in an undocumented bitmask and is not decoded. | `layouts.py` |
| External data sources (JSON only) | **Done**: table on the home page | `index.md.j2` |
| "File References" lists File Access authorizations | **Done**: renamed to File Access everywhere | renderer, CLI, diff |
| Scrubbing flags base64 image data as passwords | **Done**: a 76-character line of base64-wrapped SVG decodes to `tp://www.w3.org/...`, which looked like `user:password`. Lines of a wrapped block and decoded markup / URLs are now skipped; a real Basic-auth token is still caught. | `scrub/detectors/encoded.py` |
| Relationship-graph notes, part sizes, theme CSS, images | Not done (Medium / not needed per the report) | |
| Phase 6 coverage report | Not done. `StepText` makes script steps self-checking; the other catalogs still have no "seen vs rendered" count. | |

Also fixed on the way: `diff` now shows only the keys that changed inside a nested object (it used to cut a long object off before the change), and the model `SCHEMA_VERSION` is 0.4.0 (additive).

Tests: `tests/test_competitor_gaps.py` (21 tests, including an end-to-end check that a password and an API key in a step's calc are redacted in FileMaker's step text too). 919 pass.

**Verified on Synapse** (the colleague's file, from the production export `task_53301/SaXML_PROD_2026-10-14`). Our output now matches every count in their report:

| Check | Report (exploder) | Ours now |
|---|---|---|
| Step text identical to FileMaker's | n/a | 6,049 / 6,050 (the 1 is a comparison artefact) |
| Button actions captured (incl. grouped) | 377 grouped | 465 / 465 real actions (26 more are "Do Nothing" buttons) |
| Relationship sides allowing creation / sorted | 6 / 3 | 6 / 3 |
| Summary fields with operation and source | 8 | 8 / 8 |
| Validation messages | 3 | 3 |
| Prohibit modification | 80 | 80 |
| Value list on layout fields | 61 | 61 |
| Sorted portals | 43 | 43 (2 sort on a field FileMaker reports missing; shown as such) |
| Value lists custom / field / external | 17 / 23 / 4 | 17 / 23 / 4 |
| Run with full access | 35 | 35 |
| Custom privilege rows: layouts / scripts / tables | 711 / 249 / 138 | 711 / 249 / 138 |
| Scripts with steps and no "Called By" | 106 before | 58 (templates, tests, post-migrations, callbacks run by name) |
| Redactions in Post-Migration 1.8 (base64 images) | false positive | 0 |
