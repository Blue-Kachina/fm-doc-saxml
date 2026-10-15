# next_level.md — Opt-in coverage + WebMCP-enabled HTML viewer

## Status (2026-10-14): implemented, uncommitted

- **Coverage.** `--coverage` on `build`/`parse`/`render`. `--fail-on-coverage-gap` turns it on. Without it there's no XML inventory, no `Reports/coverage.md`, no index line, no summary section and no batch column. `build_coverage` is cached per model.
  - The real cost was one function: `_step_calcs` used a `ParameterValues//Calculation` XPath that took **38 s** on the 33 MB NEXUS export. It's now a per-step walk taking 0.16 s, with the same count (3,225).
  - NEXUS build: 40 s → **4.6 s** without `--coverage`, **5.1 s** with it.
  - Production (25 files): every coverage check is still complete (1,752 checks, nothing unrecognised).
- **Guard.** Scans `.js`, and matches the `<`/` `-escaped form the viewer writes.
- **WebMCP.** `--webmcp` on `build`/`render` (turns on `--html`).
  - Files: `render/html/webmcp.py` (data shards), `analyze/access.py` (effective access), `render/html/templates/webmcp.js` (tools, results view, search, step highlight), `index.html` hooks.
  - All the planned tools are implemented, plus `describe_schema` and `get_current_page`, and `traverse` has `direction:"both"` for table-occurrence paths. The page tools are `query_entities` wrappers, so their results views still work after leaving the page.
- **Tests.** `tests/test_webmcp.py`: 18 tests. The 6 browser tests need `uv run --with playwright pytest tests/test_webmcp.py` and are skipped otherwise. `tests/webmcp_questions.md`: 30 questions plus 6 acceptance queries.
- **Production check (task_53301, `--html --webmcp`, default output).** The build takes 134 s and the guard is clean.
  - `_viewer/data/` is **128 MB**, more than the 30–60 MB estimate. That's mostly script steps (41 MB), layout objects (38 MB) and references (27 MB).
  - Tool calls across all 25 files take 0.01–0.6 s each.
- **Follow-up: localhost serving and status badge.** ChatGPT's browser found no tools on a `file://` page, because browsers only offer WebMCP to real, secure origins.
  - `fm-saxml serve <docs>` and `--serve`/`--port` on `build`/`render` (`src/fm_saxml/serve.py`). Both work only with `--webmcp`.
  - The server binds to 127.0.0.1, refuses other Host headers (DNS rebinding), stays inside the folder, and sends `no-store`.
  - The header badge (in `webmcp.js`) shows on / opened from disk / not in this browser. On a page opened from disk, clicking it copies the `serve` command for that folder.
  - Registration retries until 5 s after load, in case the browser adds `document.modelContext` late.
  - Tests: serve (Host check, path traversal, needs a `--webmcp` build), badge states over `file://` and `http`, late registration.
- **Follow-up: agents without WebMCP.** ChatGPT and Gemini work over `serve`. Claude in Chrome has no WebMCP (`document.modelContext` never exists there), so the same tools now have two other routes:
  - `#/results?q=…&format=json` shows any tool's result as JSON text (`<pre id="fm-result-json">`).
  - A `#/agents` guide page, with a header link "For AI agents", lists every tool with its schema and runnable example links.
  - `llms.txt` at the docs root (`--webmcp` only) points agents there; its tool names are read from `webmcp.js`.
  - All of this also works from `file://`.
- **Not done or open:**
  - Objects placed off the visible layout area: needs layout width and part sizes from the parser.
  - Step-order queries ("Commit with no Set Error Capture before it") take two calls. Add a pipeline operator if this comes up.
  - CodeMirror's own line-number gutter covers the step numbers on script pages. This predates this work.
  - No live test against a browser with real WebMCP; the tools were tested through a stubbed `document.modelContext`.

## Context

fm-saxml already produces strong Markdown, JSON and HTML output. This plan covers two upgrades:

1. **Coverage is slow and always on.** `xml_inventory` (`parser/coverage.py:282`) runs about 69 full-tree XPaths and 27 context walks during every v2 parse. `build_coverage` (`analyze/coverage.py:276`) then runs 3–4 times per model without caching (`renderer.py:141`, `renderer.py:727`, `cli.py:131`, `batch/report.py:79`). Most runs don't need it, so it should only run when asked for.
2. **The HTML viewer should be agent-ready.** Today the `--html` viewer is a file:// SPA: Crepe renders Markdown, and search covers titles only. The upgrade registers **WebMCP** tools (`document.modelContext ?? navigator.modelContext`) backed by the JSON model. Agents could then run structured queries the UI can't, for example:
   - "every Set Field step that targets `Invoices::Total`"
   - "unstored calc fields in table X"
   - "layouts that show field Y"
   - "scripts with no callers"
   - jumping straight to any of the results

Decisions made:
- WebMCP is **opt-in via `--webmcp`**, which implies `--html`.
- Tools register natively when the browser supports WebMCP.
- The same tools are **always exposed on `window.FMDocs.tools`**, so browser-driving agents and tests can call them.
- No third-party polyfill.
- Unscripted questions go through a **declarative JSON `query` pipeline** with joins. There is deliberately no tool that runs agent-written JavaScript (no `eval`, no `'unsafe-eval'` CSP).
- Security questions ("who can run/view X") go through an **access matrix computed at build time**. Agents don't have to work out privilege rules themselves.

---

## Part 1 — `--coverage` switch

**Behavior**
- Coverage is **off by default**.
- `--coverage` turns on the XML inventory, `Reports/coverage.md`, the coverage line on `index.md`, the Coverage section in `Reports/summary.md`, the batch-summary column and the console line.
- `--fail-on-coverage-gap` turns on `--coverage` automatically.

**Changes**
- `cli.py`:
  - Add a `CoverageOpt` next to `FailOnCoverageOpt` (`:120`).
  - Add it to `build` (`:244`) and `parse` (`:515`); `parse` needs it so `model.json` can include the inventory.
  - Pass it through `_run_pipeline` → `_analyze` → `_parse_and_scrub` (`:978`), and through `_build_batch` (`:331`).
  - `_report_coverage` (`:127`) does nothing when coverage is off.
- Parser: `_parse_v2` (`parser/saxml_reader.py:197`) only calls `xml_inventory(root)` when asked. Add a `coverage: bool = False` parameter on the public parse entry point.
- `normalize.py:135`: `model.coverage_inventory` stays `None` when coverage is off. It is already optional in `document_model.py:207`, so check that serialization handles `None`.
- **Compute once.** Call `build_coverage(model)` a single time in the CLI and pass the `CoverageReport | None` to `render_markdown(model, out, ..., coverage=report)` and to the batch report. Remove the repeated calls in `renderer.py:141` and `:727` and in `batch/report.py:79`. This also speeds up `--coverage` runs.
- Templates: when coverage is `None`, leave out the coverage pieces:
  - `index.md.j2:42-43`
  - `reports/summary.md.j2:33-40`
  - the `batch_summary.md.j2:23-26` column
  - the `coverage.md` write
- `render` command: if the loaded `model.json` has a `coverageInventory` and `--coverage` is given, render it. Without `--coverage`, skip it.
- Optional perf win, inside `--coverage` only: memoize `step_text(step)` per call (`model/step_text.py:108`) and the repeated `_OBJECTS` / `_STEPS` node sets inside `xml_inventory`. Do this only if timings show it's needed.

**Tests and docs**
- `tests/test_coverage.py`:
  - Add `--coverage` to `test_coverage_report_page_and_ci_flag`.
  - Add `test_coverage_is_off_by_default`: no `Reports/coverage.md`, no index line, `coverageInventory` null.
  - Add `test_fail_on_gap_implies_coverage`.
  - Direct calls to `xml_inventory` and `build_coverage` stay as they are.
- `README.md`:
  - Rewrite the Coverage section (`:161-163`) and the flags table (`:115-159`).
  - Mark `coverage.md` as optional in the output tree (`:301`).

---

## Part 2 — WebMCP in the HTML viewer (`--webmcp`)

### Architecture

The viewer must keep working on file:// with no `fetch` and no local modules. Everything therefore loads as classic `<script>` shards that call `FMDocs.*` registration functions, the same way the page scripts do today.

The data comes from the **in-memory `DocumentModel`**, not from re-reading `entities.json`. That gives all 18 entity maps; `entities.json` leaves out 7 of them. It also lets `LinkResolver` give the real deduplicated page path for each docId.

```
out/
  index.html                       (+ <script src="_viewer/webmcp.js"> when --webmcp)
  _viewer/
    manifest.js                    (unchanged; + webmcp:true, files:[{key,label,dir}])
    pages/pNNNNN.js                (unchanged)
    webmcp.js                      static asset: tool definitions + query engine
    data/<fileKey>/
      catalog.js   FMDocs.catalog(fileKey, {counts, docmap:{docId:[path,title,type]}})
      <type>.js    FMDocs.shard(fileKey, type, [compact records])   lazy, per entity type
      steps.js     FMDocs.shard(fileKey, "scriptStep", [...])       lazy
      refs.js      FMDocs.refs(fileKey, [[src,tgt,relType,role], ...])  lazy
      access.js    FMDocs.access(fileKey, {...})   lazy: effective-access matrix (see below)
```

- **Effective-access matrix** (`access.js`), computed in Python at build time so it can be tested. For each privilege set, and for each script, layout, value list and table, it stores the effective access plus the *reason*:
  - `fullAccess`: the built-in `[Full Access]`
  - `blanket`: one category-wide setting, e.g. "All executable"
  - `customRow`: the object's own row in a custom list
  - `newFallback`: no row of its own, so the `[Any New …]` row (`targetDocId` = None) applies
  - `limitedCalc`: record access limited by a calculation, with the calc text
  - `noAccess`

  It also stores `accounts: {privilegeSetDocId: [{docId, name, enabled, accountType}]}` and the extended privileges for each set (`ExtendedPrivilegeEntity.privilegeSetDocIds`).

  Sources: `PrivilegeSetEntity.records/layouts/valueLists/scripts` (`PrivilegeCategory.summary/settings/custom[PrivilegeItem.targetDocId, access]`) and `AccountEntity.privilegeSetDocId`.

  Caveats the tools must report:
  - **External accounts** are groups, not people.
  - **Disabled accounts** are listed but flagged.
  - **"Run with full access privileges"** on a script changes what the script can do, not who can start it. It's flagged on the result.

- **Compact records.** Each record keeps `docId`, `name`, `path` and the type-specific attributes useful for querying. Examples:
  - fields: table, dataType, fieldType (normal/calc/summary), storage, indexed, global, auto-enter, validation, calc text
  - steps: `scriptDocId`, index, step name, `fmText`, enabled
  - layouts: base TO, folder
  - layout objects: type, field, `tableOccurrenceDocId`, `layoutDocId`, `part`, `parentObjectDocId`, bounds, script trigger, button script, plus flattened calc roles:
    - `hideCondition`: the "Hide object when" calc text from `calculations[role=hideCondition]`
    - `hasHideCondition`
    - `tooltip`
    - `hasConditionalFormatting`
    Flattening these means `where` filters don't need to reach into arrays.
  - references (refs shard): also store the target's **parent** next to each edge. For a field, that's its base table (field docIds are `field:<BaseTable>::<Field>`). This makes "all references to any field in table X" a single filter.
- Records **never include `sourceXml`**. That keeps the size down and avoids publishing raw XML.
- **Lazy loading.** A `loadShard(fileKey, type)` helper adds a script tag and resolves when `FMDocs.shard` fires. It uses the same pattern as `loadPage()` (template `:359`) and caches the result.
- **Batch builds.** Each file in the batch gets its own `data/<fileKey>/` folder. Cross-file queries go through the file list in the manifest. Queries take an optional `file` argument, and the default is all files. Shards keep memory bounded, which matters on task_53301: 66k pages, and BLITZ alone has 29 MB of entities.

### Tools (all read-only except `navigate_to`, which only changes the viewer route)

| Tool | Purpose |
|---|---|
| `get_solution_overview` | Files, entity counts per type, generatedAt, whether scrubbing was applied |
| `get_current_page` | Current route's docId/type/name plus the **full compact record**. This is the "page knows its JSON" requirement |
| `search_entities` | Text match on name, comment and calc text. Filters: `types[]`, `file`, `limit`. Returns docId, type, name, path |
| `query_entities` | Structured filter over one type: `{type, where:[{field, op: eq\|contains\|regex\|exists\|in, value}], file, limit, fields[]}`. Covers "unstored calcs", "global fields", "layouts on TO X" and similar |
| `find_script_steps` | Step-level search: `stepName`, `textContains`/`regex`, `scriptFolder`, `targetDocId` (e.g. every Set Field on a field) |
| `get_entity` | Full compact record for one docId (scoped `fileUuid/docId` in batches) |
| `find_references` | Target is `docId`, **or** `targetType` + `parentDocId` (e.g. every field in `table:Invoices`), **or** `docIds[]`. Takes `direction: incoming\|outgoing\|both`, optional `relationshipType`/`sourceType`, and `groupBy: target\|source`. Uses refs shards |
| `find_unreferenced` | Entities of a type with zero incoming references, for dead-code hunting (scripts, layouts, value lists, custom functions, fields) |
| `traverse` | Walks the reference graph more than one step: `{from: docId, direction, relationshipTypes[], maxDepth, stopAt: types[]}`. Returns the nodes reached, each with its path. Covers transitive script callers/callees, call cycles, "everything reachable from layout X's buttons and triggers", and the path between TO A and TO B |
| `who_can_access` | `{docId, action}`. Actions: `run` (script), `view`/`modify` (layout, value list), `create`/`edit`/`delete`/`view` (table records). Returns each privilege set with its access, reason and calc, plus its accounts, with disabled and external accounts flagged. Uses `access.js` |
| `what_can_access` | The reverse of `who_can_access`: `{account \| privilegeSet, type, action}` lists the objects that account or set can use, with reasons |
| `query` | Declarative pipeline for questions no other tool covers. Input is a JSON array of steps (details below). No custom code is executed, by design |
| `navigate_to` | Opens a docId's or path's page in the viewer, optionally at a heading anchor. This turns query results into navigation |

**The `query` pipeline.** This is the general tool for questions nobody wrote a tool for. Steps run in order over rows:
- `{from: type, file?}`: start from one entity type, or `"reference"` for the edges
- `{where: [...]}`: the same operators as `query_entities`, plus `not`/`any` grouping and dotted paths
- `{join: {on: field, as, type?}}`: follow a docId-valued field, such as `scriptDocId`, `layoutDocId` or `privilegeSetDocId`
- `{joinRefs: {direction, relationshipType?, as}}`: follow reference edges
- `{joinAccess: {action, as}}`: attach the effective-access rows
- `{select: [fields]}`
- `{groupBy: field, agg: count|list}`
- `{sort}`
- `{limit}`

Rules:
- Rows are flat objects, and a joined entity is nested under its `as` name.
- Each step's output is capped. The response includes the row count after every step, so the agent can see where a query went empty.
- Unknown fields or types are errors that list the valid names, never silent empty results, so agents can fix their own queries.
- `describe_schema` (one more read-only tool) returns the queryable fields of each type with examples. Agents call it first.

**Page-contextual tools.** When the route changes, `show()` (template `:400`) calls `FMDocs.webmcp.onRoute(meta)`. That registers a few tools scoped to the current entity and unregisters the previous page's set:
- **script page:** `list_steps_in_this_script`
- **table page:** `list_fields_in_this_table`
- **layout page:** `list_objects_on_this_layout`, with filters `objectType`, `fieldsOnly` and `hidden: hideCondition|any`

**What "hidden" means on a layout.** FileMaker has several meanings, and the tools say which ones they cover:
- **Covered:** "Hide object when" (`hideCondition`). This is what `hidden: "hideCondition"` returns.
- **Covered:** objects that only appear when a tab panel, slide panel or popover is opened, found by walking the container chain through `parentObjectDocId`. Each comes back with its container. `hidden: "any"` returns these as well as hide conditions. Portal rows don't count as hidden.
- **Not covered yet:** objects placed off the visible area, such as past the right edge or in a zero-height part. That needs the layout's width and part sizes, which the parser doesn't extract today (there is no width on the layout entity). It's a follow-up in the parser.

**Acceptance queries.** Each must work in one tool call and be covered by the Playwright smoke test:
- "Show me all references to fields from table X" → `find_references({targetType:"field", parentDocId:"table:X", direction:"incoming", groupBy:"target"})`
- "Show me all the hidden fields on layout X" → `query_entities({type:"layoutObject", where:[{field:"layoutDocId",op:"eq",value:"layout:X"},{field:"fieldDocId",op:"exists"},{field:"hasHideCondition",op:"eq",value:true}]})`. On layout X's page, use `list_objects_on_this_layout({fieldsOnly:true, hidden:"hideCondition"})`.
- "Which accounts can run script X?" → `who_can_access({docId:"script:X", action:"run"})`
- "Which accounts can access layout Y?" → `who_can_access({docId:"layout:Y", action:"view"})`
- "Everything that eventually calls script X" → `traverse({from:"script:X", direction:"incoming", relationshipTypes:["performsScript"]})`. Use the real relationship-type names in `references.py`.
- "Privilege sets that can run a script containing a Delete Record step" → `query([{from:"scriptStep"},{where:[{field:"stepName",op:"eq",value:"Delete Record/Request"}]},{join:{on:"scriptDocId",as:"script"}},{joinAccess:{action:"run",as:"access"}},{groupBy:"access.privilegeSetDocId",agg:"list"}])`

**Unscripted-query test set.** Keep a list of about 25 plain-English questions in `tests/webmcp_questions.md` (the impact, dead-code, call-graph, trigger, schema, calc-text, step-pattern, security, relationship and multi-file questions from the planning discussion). For each, record the tool call(s) that answer it. If one can't be answered, add a pipeline step or tool rather than a one-off.

### Results in the viewer (agent queries show up in the site's search results)

Agent queries shouldn't stay hidden inside the agent conversation. The viewer gets a **Results view** that replaces the current title-only search list in the sidebar (`renderSearch`, template `:333`).

**How results get there**
- Every query tool (`search_entities`, `query_entities`, `find_script_steps`, `find_references`, `find_unreferenced`, `traverse`, `who_can_access`, `what_can_access`, `query`) takes `display: true|false`, default **true**.
- When `display` is on, the tool renders its result set into the Results view, titled with the question the agent passes in (`title`) or one generated from the tool and its arguments.
- Tools called with `display` on lose `readOnlyHint`, because they change what the user sees. They still never change data.
- There's also a `show_results({title, docIds[] | rows[]})` tool, so an agent can put together a hand-picked list ("the 6 scripts I think cause this bug").

**Grouped by result type**
- One collapsible group per entity type, with counts, e.g. *Fields (12) · Script steps (40) · Layout objects (7) · Accounts (3)*.
- Groups are ordered by count, or by the order the agent asked for.
- **Nested where it helps:**
  - script steps under their script ("Invoice Post (5 steps)")
  - layout objects under their layout
  - fields under their table
  - `who_can_access` rows under their privilege set, showing the access reason and then the accounts
- In a batch, results are also split by file.
- Each row shows the entity name, a short detail (step `fmText`, field type, access reason) and links to its page.

**Jumping to the exact spot**
- Script steps don't have their own pages or anchors today.
- Clicking a step result opens the script page and then scrolls to that step and highlights it, matching on its index or text in the rendered step list. Do this as a best-effort DOM lookup in `scrollToAnchor` (template `:436`) instead of changing the Markdown.
- Layout objects, fields and other entities already have their own pages.

**Saving and sharing**
- The Results view's route is `#/results?q=<url-encoded JSON of tool + args>`.
- Reloading, bookmarking or sending the link runs the query again against the local data (no stored results).
- Back/forward moves between the results and the pages opened from them.
- The last 20 queries are kept in a "Recent queries" list in `localStorage`, wrapped in try/catch.

**People can use it too**
- When `--webmcp` data is present, the normal search box searches the docmap (every entity name in every file, not just page titles) and shows its matches in the same grouped Results view.
- An "Advanced" toggle opens a small form for the common filters: type, file, name contains, and has-hide-condition / unreferenced / triggers. It builds the same `query_entities` call an agent would make, so people and agents get identical results.
- Without `--webmcp`, search works the way it does today.

**Acceptance:** each acceptance query above, run through `FMDocs.tools`, must:
- render a grouped Results view with the right group counts
- produce a shareable `#/results?q=` link that gives the same groups when reloaded
- open the right page from a result click, and highlight the step for step results

**Tool details**
- Every tool has a JSON Schema `inputSchema` and a clear `description`.
- Results are JSON text content, capped by `limit`. The default is 50; truncated results include `truncated: true` plus the total count.
- `annotations: {readOnlyHint: true}` goes on every tool except `navigate_to` and `show_results`, and is dropped from a query tool's call when it is made with `display: true`. In every case, no tool changes data.

**Registration** in `webmcp.js`:
```js
const mc = document.modelContext ?? navigator.modelContext;
FMDocs.tools = {/* name -> {description, inputSchema, execute} */};
if (mc?.registerTool) for (const t of Object.values(FMDocs.tools)) mc.registerTool(t);
```

### Python side
- **New `src/fm_saxml/render/html/webmcp.py`**:
  - `write_webmcp_data(model, out_dir, viewer_root, file_key, resolver)` builds the compact records per type, the docmap (from `LinkResolver.path_for` / `title_for`, `link_resolver.py:176`) and the refs from `model.references`.
  - Writes the shards with the existing `_js_literal` (`viewer.py:99`), which is already safe against `</script>` and U+2028.
  - Holds one projection function per entity type, kept in a dict next to the type map.
- **New static asset `render/html/templates/webmcp.js`** is copied in by `render_html_viewer`.
- `viewer.py`:
  - `render_html_viewer(output_dir, webmcp_files=None)` adds the script tag and the manifest `files` list when WebMCP is on.
  - Add the `onRoute` hook call in the template. It is a no-op when `FMDocs.webmcp` is absent.
- `cli.py`:
  - Add a `WebMcpOpt` to `build` and `render`. `--webmcp` turns on `html=True`.
  - Single-file build: call `write_webmcp_data` while the model is still in memory, before `_render_html_viewer`.
  - Batch: call it per file inside the `_build_batch` loop, after the second scrub pass. Shards must use the re-scrubbed models.

### Secret-scrubbing hardening (required before shipping JSON in `.js`)
- In `scrub/guard.py:18`, add `.js` to `_TEXT_SUFFIXES`.
- In `_variants` (`guard.py:28`), add the `<`/` `-escaped form that `_js_literal` produces.
- Add a test: build with a planted secret, with scrubbing on and `--webmcp`. The guard must find nothing in `_viewer/**/*.js`. Then plant the raw value in a shard on purpose and confirm the guard catches it.

### Tests (`tests/test_webmcp.py`)
- Without `--webmcp`, there is no `_viewer/webmcp.js` and no `data/`. `--webmcp` implies the viewer.
- Every docId in the model appears in the docmap, and its path exists as a `.md` file.
- Shards for all 18 entity types are present when the type is non-empty. No record contains `sourceXml`.
- A batch on `samples/multi_file_export` writes one `data/<fileKey>/` per file, and the manifest `files` list matches.
- Shards cannot break out of the script context (same pattern as `test_page_scripts_cannot_break_out_of_script_context`).
- **JS behavior:** Playwright smoke test, skipped if Playwright isn't installed.
  - Open `index.html` with an init script that stubs `document.modelContext = {registerTool, unregisterTool}` to record the registrations.
  - Assert the tool names are registered.
  - Call `FMDocs.tools.query_entities.execute(...)`, `find_script_steps` and `navigate_to` on `v2_sample.xml` output.
  - Assert `body.dataset.rendered` follows navigation, and that the page-contextual tools swap when the route changes.

### Docs
- README: new "Agent-ready HTML (WebMCP)" section covering:
  - what the tools are
  - browser status (Chrome origin trial/flag, Edge flag)
  - the `FMDocs.tools` fallback
  - example agent prompts
- Add `--webmcp` to the flags table.

---

## Implementation order
1. Save this plan as `next_level.md`.
2. Part 1, coverage (small and independent). Run the full test suite.
3. Guard hardening (`.js` scanning and the escape variant).
4. `webmcp.py` data shards and Python tests. This includes the access matrix (`access.py`, with unit tests for each reason: full access, blanket, custom row, `[Any New]` fallback, limited calc, disabled/external accounts).
5. `webmcp.js` tools, the template hook, and the Playwright smoke test.
6. Results view: grouped rendering, the `#/results?q=` route, step highlighting, upgraded search box and the Advanced form. Extend the Playwright test to cover them.
7. README, then a version bump using the existing PowerShell script.

## Verification
- `uv run pytest`: everything green.
- Coverage timing: time `uv run fm-saxml EverythingBagel.xml -o <scratch> -f -y` with and without `--coverage`, and on a large export (`NEXUS_saxml.xml`). Record the speedup in `next_level.md`.
- Prod check (per memory): build task_53301 with `--html` and no `--out`. Confirm the output has no `coverage.md` and is otherwise the same.
- Run a second build with `--webmcp` into a scratch folder:
  - record the size added by `_viewer/data/`
  - open it in Chrome with WebMCP enabled, or use the Playwright stub
  - try the sample queries above
- Guard: build with `--webmcp` and default scrubbing. The redaction guard reports clean.
