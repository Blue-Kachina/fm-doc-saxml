# Fix Gaps 2 — roadmap from the v0.5.0 re-evaluation

Date: 2026-10-15. Source: the colleague's "v0.5.0 re-evaluation" tab (same Synapse.xml as the first report: 186 scripts / 6,050 steps, 17 privilege sets). Their checkers are independent Python scripts (`eval-v0.5.0/`) that parse the XML themselves and compare it with our pages.

## Status (2026-10-15): Phases 0–4 done, Phase 5 not started

Verified on **Synapse itself**, which is part of the production export `task_53301/SaXML_PROD_2026-10-14`. Every count matches the colleague's report:

| Finding | Before | Now (Synapse) |
|---|---|---|
| Layout rows with a level | names only | 711 / 711 (616 view only, 77 modifiable, **18 no access**), plus records level 711 / 711 |
| Script rows with a level | names only | 249 / 249 (241 executable only, **8 no access**) |
| Field-level privileges | "Custom" | 156 / 156 (150 modifiable, 6 view only) |
| `refresh_token=` in qbo_getOauth_refreshToken | `[REDACTED:token#4]` | shown as written. It was `credential_variable` (`$refreshToken`). It is the only redaction that changed across all 25 files |
| `DeepL-Auth-Key` | `[REDACTED:token#2]` | shown as written |
| Multi-path data sources | run together | 6 of 6 split, 39 / 39 paths |
| AGFM_OpenChat step 3 | `Allow User Abort` | `Allow User Abort [ Off ]` |

Tests: 1,000 passed (49 new in `tests/test_competitor_gaps2.py` + 1 in `test_scrub_structural.py`), plus 25 / 25 WebMCP browser tests (`uv run --with playwright`). The production build with `--coverage` reports 1,824 / 1,824 checks complete.

What was built, beyond the plan below:
- The WebMCP `who_can_access` / `what_can_access` / `joinAccess` tools also cover **fields** (`analyze/access.py` `field` kind).
- `index.md` has a scrubbing notice (scrubbed with counts, or "Not scrubbed") and a "Reading These Docs" section. `llms.txt` has the same rules. **Scrubbing stays on by default.**
- The parameter-name guard applies only to rules that infer a secret from a nearby *name* (`keyword_assignment`, `json_credential`, `json_set_element`, `comment_credential`, `credential_variable`, `credential_field`). A password passed *positionally* (`CURL.SetOptionPassword … "sftpPass"`) is still redacted.

Not done: Phase 5 (independent checkers in CI). Commit `samples/has_restricted_access_to_scripts/` too: the end-to-end privilege tests skip without it.

---

Headline: all 18 gaps from round 1 are closed except **privilege-set detail**. They also found two scrubber false positives and two small rendering bugs, and noted that our coverage report counted privilege rows as complete without checking what each row said.

## 1. Verification

I checked each claim against the code and our local samples (EverythingBagel, NEXUS, disRenewalUniverse). None of our samples have custom Layout, Script, Value List or field-level privileges. disRenewal has one custom `Records` set and that's all. That is why our tests and coverage report never caught the privilege gap.

| Claim | Verdict | Evidence |
|---|---|---|
| Layout rows are names only (711 rows, 18 "No access") | **Reproduced** (new sample) | `privileges.py:_parse_custom_item` reads access only from *child* elements (`<View access=…>`). On a `<Layout>` item the level is an attribute of the item itself (`Layout/@access`, as their checker reads it). That attribute goes into `attributes`. Normalize carries it over (`normalize.py:1115`), but `privilege_set.md.j2` builds its columns from `item.access` only, so it is never rendered. |
| Script rows are names only (241 executable, 8 no access) | **Reproduced** (new sample) | Same path as layouts. |
| Value list rows | **Reproduced, not in their report** | Same code path. Synapse probably has no custom value-list privileges. |
| Field-level record privileges show only "Custom" (156 entries) | **Reproduced** (new sample) | `<Fields access="Custom">` has a nested per-field list. `_parse_custom_item` keeps only `access="Custom"` and never descends into it. |
| Coverage report says privileges are complete | **Confirmed** | `coverage.py:132` `_privilege_rows` counts rows. It doesn't check that each row has an access level. |
| Scrubber rewrites the header name `DeepL-Auth-Key` | **Reproduced** | `"Authorization: DeepL-Auth-Key " & $key` → `"Authorization: [REDACTED:token#1] " & $key`. The detector is `comment_credential` (`scrub/detectors/comments.py`), which runs on calc string literals. It treats the word after `Authorization:` as the token, even though here that word is the scheme name and the real key is concatenated after it. |
| Scrubber rewrites the literal `refresh_token=` | **Not reproduced in isolation** | 9 variants pass through `scrub_calc` and `scrub_text` unchanged. The most likely cause is the two-pass propagation: a value detected somewhere else equals `refresh_token=` (or contains it), and the second pass replaces it everywhere. Needs the exact `qbo_getOauth_refreshToken` step, or the scrub report for that run. |
| 6 multi-path external data sources run together | **Confirmed (by code)** | `external_data_sources.py:23` takes `text_of(UniversalPathList)` as **one** string. FileMaker stores several paths as lines in that one text (`file:a\rfile:b`), and `cell` flattens the line break. The newer `<ObjectList><Location>` form is also read as one string. |
| `Allow User Abort [ Off ]` shown as `Allow User Abort` (1 step) | **Confirmed (by code)** | `step_text()` prefers FileMaker's StepText. Here StepText leaves out the option, and `_omitted_params` (`model/step_text.py:126`) only adds back missing *calcs*, not missing On/Off options. The fallback renderer would have printed `Off`. |
| "Called By" covers only this file | **Confirmed (by design)** | Script pages without callers don't say this. Callers from other files are resolved only in multi-file builds. Scripts run by server schedules, `fmp://` URLs or Perform Script by name are never callers. |
| Default repetition `1` omitted (3 Set Field, 7 calcs) | **Not a bug** | Deliberate, and the exploder does the same. No change. |

## 2. Root causes (code locations)

- `src/fm_saxml/parser/extractors/privileges.py:83–109` (`_parse_custom_item`): reads only child `access` values. It ignores the item's own `access` (and any record-level attribute), and it doesn't descend into `<Fields>`.
- `src/fm_saxml/render/markdown/templates/privilege_set.md.j2`: builds columns from `item.access` only. `item.attributes` is never shown.
- `src/fm_saxml/analyze/coverage.py:132`: `_privilege_rows` counts rows, not access values.
- `src/fm_saxml/scrub/detectors/comments.py:~65`: the "Authorization:" rule doesn't recognise vendor scheme names (`DeepL-Auth-Key`, `Token`, `SSWS`, `Klaviyo-API-Key`, …) and redacts the scheme instead of the value after it.
- `src/fm_saxml/parser/extractors/external_data_sources.py:23`: one `paths` entry per `UniversalPathList`. It should be one entry per line or `<Location>`.
- `src/fm_saxml/model/step_text.py:126` (`_omitted_params`): checks only `kind == "calc"`.

## 3. Roadmap

### Phase 0: Fixtures first (blocking for Phase 1)

We can't test privilege detail without XML that has it, and guessing the shape is how round 1's relationship bug happened.

1. ~~Add custom privileges to EverythingBagel.~~ **Done (2026-10-15):** `samples/has_restricted_access_to_scripts/EverythingBagel.xml`, privilege set "Calculated Access". It covers custom Layouts, Value Lists, Scripts, field-level access and calculated (limited) record access. A build of it reproduces the colleague's finding exactly: the layout, value-list and script tables show names only, and `Fields` shows "Custom".
2. Ask the colleague for (a) the `qbo_getOauth_refreshToken` step that was scrubbed and (b) their `eval-v0.5.0/` checkers. A Synapse privilege snippet is no longer needed.
3. Cut a minimal `tests/fixtures/privileges_custom.xml` from the new sample for unit tests.

**Confirmed XML shape** (from the new sample):

```xml
<Layouts Custom="True">
  <Custom Create="False">                       <!-- "Allow creation of new layouts" -->
    <ObjectList membercount="2">
      <Layout type="existing" access="ReadOnly" records="ReadWrite"><LayoutReference id="1" name="…"/></Layout>
      <Layout type="New" access="NoAccess" records="NoAccess"/>
<Scripts Custom="True"><Custom Create="True"><ObjectList>
      <Script type="existing" access="ReadOnly"><ScriptReference …/></Script>   <!-- ReadOnly = Executable only -->
<ValueLists Custom="True"><Custom Create="True"><ObjectList>
      <ValueList type="existing" access="NoAccess"><ValueListReference …/></ValueList>
<Records Custom="True"> … <Table type="existing">
      <View access="Calculation"><Calculation>…<Text>If ( True ; 1 ; 0 )</Text></Calculation></View>
      <Fields access="Custom">
        <Field type="existing" access="ReadOnly"><FieldReference id="7" name="numberField"><BaseTableReference …/></FieldReference></Field>
```

Values seen: `ReadWrite`, `ReadOnly`, `NoAccess`, `Calculation`, `Custom`.

**Additional issues found in the sample** (not in the colleague's report):

- `<Custom Create="True|False">` ("Allow creation of new …") is lost: `_parse_category` reads settings from the category element only, not from `<Custom>`.
- The limited access value is `Calculation`, rendered as-is. FileMaker's dialog calls it "Limited…".
- The new-object row reads "[Any new valuelist]". It should read "[Any new value list]".

### Phase 1: Privilege-set detail (the one real gap)

1. **Parser.** In `_parse_custom_item`, turn the item's own `access` attribute into a column (and `records` on layouts). Descend into `<Fields access="Custom">` and emit `field_access: [{name, id, table, access}]` from each `<Field access>` + `<FieldReference>`. In `_parse_category`, merge `<Custom>`'s attributes (`Create`) into the category settings.
2. **Model / normalize.** Add `fieldAccess` to the custom item and resolve each field to its field docId. Keep `attributes` for anything not modelled.
3. **Labels.** `access_label` per category, with FileMaker's dialog wording:

   | XML | Layouts | Layout records | Scripts | Value lists | Records / fields |
   |---|---|---|---|---|---|
   | `ReadWrite` | Modifiable | Modifiable | Modifiable | Modifiable | Yes / Modifiable |
   | `ReadOnly` | View only | View only | Executable only | View only | View only |
   | `NoAccess` | No access | No access | No access | No access | No / No access |
   | `Calculation` | — | — | — | — | Limited |

4. **Template.**
   - Layouts table: `Layout | Layout | Records`
   - Scripts table: `Script | Access`
   - Value lists table: `Value List | Access`
   - Each category with custom access: an "Allow creation of new …: Yes/No" line from `Custom/@Create`
   - Records: under each table row with `Fields: Custom`, a nested table `Field | Access` linked to the field pages
   - Rows for new objects (`type="New"`) are labelled "Any new layout / script / value list / table", so they don't read as a real object
5. **Reverse index (cheap, high value for agents).** On each layout, script and field page, add an "Access by privilege set" table for every set that has *custom* access to it. This answers "which sets can run script X" without opening 17 pages. Leave it out for blanket-access sets so it doesn't add noise.
6. **WebMCP / JSON.** Expose the new columns in the model JSON and in the access-matrix tool from `next_level`.
7. **Coverage.** Replace the row counts with content checks: "layout rows with an access level", "script rows with an access level", "field-level entries", each compared with the XML count. A row with no level counts as missing.
8. **Tests.** Unit tests on the Phase 0 fixture for each access level, plus a golden render of one privilege-set page.

Exit criteria: on the EverythingBagel export (and on Synapse, via the colleague), every layout, script and value-list row shows its level, the "No access" rows are visibly different, every field-level entry is rendered, and the coverage report fails if any row lacks a level.

### Phase 2: Scrubber false positives

1. **Authorization scheme names.** In `comments.py` (and `credentials.py:_AUTH_HEADER_RE` for consistency), treat `Authorization: <Scheme> <value>` as scheme + value for any scheme token, not only Bearer/Basic/Token/Digest/OAuth. When the literal ends right after the scheme (value concatenated from a variable), don't redact anything.
2. **Parameter names aren't secrets.** Never accept a hit whose value is a bare credential-style *name*: it matches the keyword list and contains no other characters, such as `refresh_token`, `refresh_token=`, `client_secret`, `api_key`. Apply this both in the detectors and before a value enters the second-pass substitution table, so one bad hit can't spread across the file.
3. **Reproduce the refresh_token case** from the colleague's step (Phase 0.2) and turn it into a regression test. If it is the propagation, add a test that one bad value doesn't rewrite other scripts.
4. **Regression corpus.** Add `tests/scrub/false_positives.txt`, one known-safe line per entry (`Authorization: DeepL-Auth-Key `, `grant_type=refresh_token`, `"refresh_token="`, `token_type`, …), and assert that none of them change at any level.

### Phase 3: Small rendering fixes

1. **On/Off options missing from StepText.** In `_omitted_params`, also compare `kind == "option"` items that are a bare On/Off: if FileMaker's text has no `[ … ]`, append `[ On ]` / `[ Off ]` as the fallback would. Test with an `Allow User Abort` step whose StepText has no option.
2. **Multi-path data sources.** Split each `UniversalPathList` on `\r` / `\n` and on `<Location>` children into separate `paths` entries. Render them as a list (`<br>` in the index table, bullets on the page). Fixture: one source with two paths in each XML form.
3. **"Called By" caveat.** On a script page with no callers, print one line: *No callers found in this file. Scripts can also be run from other files, server schedules, `fmp://` URLs or Perform Script by name.* In multi-file builds, say "in these files". Add the same note to the unused-script analysis report.

### Phase 4: Scrubbing default and agent guidance

The colleague runs with `--disable-scrubbing` for internal analysis. They are right that a scrubbed build changes code.

1. **Decision (needs you): keep scrubbing on by default?** I recommend keeping it on: docs get shared, and leaking a secret costs more than a scrubbed literal. But make every change visible:
   - Add a banner at the top of `index.md` and `Reports/coverage.md`: "Scrubbing: secrets level, N values replaced in M scripts. Use --disable-scrubbing for an exact copy."
   - Add a coverage row "steps changed by scrubbing" that lists the affected steps, so an agent knows which code it can't trust as written.
2. **Agent rules in the generated output.** Add the colleague's rules to the "how to read these docs" section that agents load:
   - read privileges from the per-set tables (after Phase 1)
   - don't treat a missing "Called By" as proof a script is unused
   - check `Reports/coverage.md` before trusting an area
   - `[REDACTED:…]` in code means the literal was changed

### Phase 5: Independent verification in CI

The colleague's main point is that a self-check can share blind spots with the converter. Round 1 and round 2 both found gaps our coverage report said were complete.

1. Port their `eval-v0.5.0/` checkers (or write our own along the same lines) as `tests/acceptance/`. They parse the XML with plain `lxml`, with no imports from `fm_saxml`, and check the rendered Markdown by docId.
2. Run them on EverythingBagel, NEXUS and disRenewal in CI. Fail on any regression in the counts.
3. Add their measures to `coverage.md` where we don't have them yet: StepText exact-match rate, and Called By compared with every `ScriptReference` in the XML.

## 4. Order and size

| Phase | What | Size | Blocks on |
|---|---|---|---|
| 0 | Fixtures (sample added 2026-10-15; colleague snippets still pending) | ¼ day | The colleague, for refresh_token only |
| 1 | Privilege-set detail + reverse index + coverage | 1½–2 days | Ready to start |
| 2 | Scrubber false positives | ½–1 day | Phase 0.2 for refresh_token only |
| 3 | On/Off option, multi-path sources, Called By caveat | ½ day | — |
| 4 | Scrubbing banner + agent rules | ½ day | Default decision |
| 5 | Independent checkers in CI | 1 day | Colleague's scripts (optional) |

Phases 1, 2 and 3 can start now. Target release: **v0.6.1**, or fold into 0.6.0 if that hasn't shipped.

## 5. Open questions

- What triggered the `refresh_token=` redaction? Needs the step and that run's scrub report.
- Scrubbing default (Phase 4.1).
- Reply to the colleague's "upstream issue" list. All three items (privilege detail, multi-path sources, Allow User Abort) are covered above.
