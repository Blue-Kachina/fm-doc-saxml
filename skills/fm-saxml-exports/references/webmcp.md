# WebMCP / `window.FMDocs` (the `--webmcp` viewer)

Only present if built with `--webmcp` (which implies `--html`). Read-only; nothing executes agent-written code
(`query` takes JSON pipelines only). Tools run against the model, so they are faster and more reliable than
page scraping for cross-cutting questions. They are per-file: in a multi-file build, see "Multi-file solutions"
in `SKILL.md` before trusting an empty result.

There are 17 tools (`Object.keys(FMDocs.tools)` lists them; the header badge may show a smaller count, and the three page-scoped tools only appear on a matching page). Results carry the entity's Markdown `path` and, for `find_unreferenced`, a `caveat`.

Core tools: `describe_schema` (start here: lists queryable types and fields), `get_solution_overview`,
`get_entity`, `search_entities`, `query_entities` (one type, several via `types`, or all; `sort`; unknown
fields are skipped and reported in `skippedTypes`), `find_script_steps`, `find_references`,
`find_unreferenced`, `find_indirection`, `rename_impact`, `traverse`, `who_can_access`, `what_can_access`,
`query` (JSON pipeline: `from where join joinRefs joinAccess select groupBy sort limit`), `navigate_to`,
`show_results`. Page-scoped: `list_steps_in_this_script`, `list_fields_in_this_table`,
`list_objects_on_this_layout` (the last finds hidden objects, including those in tab panels, slide panels
and popovers).

Observed on the live server: calls took 0.1 to 0.4 s each even on a 28k-reference solution. `search_entities({query, types:[...], limit})` returns `{total, items, truncated, query}` and is the way to get an exact docId; `who_can_access` with a docId that does not exist returns `{error, hint}` ("Check the docId with search_entities"), so look the id up first. A `who_can_access` answer lists each privilege set with `allowed`, `access`, `reason` and its `accounts` (with `enabled` and `external` flags).

## Calling the tools

Three ways, in order of preference:

1. **Native WebMCP** (`document.modelContext`): available only in WebMCP-capable browsers, and only when the
   viewer is served over HTTP. `fm-saxml serve <docs>` (or `build ... --webmcp --serve`) serves it at
   `http://127.0.0.1:8766`.
2. **By URL** (works without WebMCP, e.g. Claude in Chrome, and from a `file://` page; the header badge then reads "WebMCP not in this browser" or "WebMCP off: opened from disk"):
   `index.html#/results?q=<URL-encoded {"tool":"<name>","args":{...}}>&format=json`
   returns JSON text in `<pre id="fm-result-json">`. Without `&format=json` you get the human results view.
3. **In-page JS**: `FMDocs.tools.<name>.execute({...})`.

Pass `display:false` to skip opening the results view when you only need data. Without a browser at
all, the same data is in `_viewer/data/` and the JSON contract; use the Python API instead.

## Discovery and examples

The header's **For AI agents** link (`#/agents`) lists every tool with its argument schema and
example links for *this* solution; `llms.txt` at the docs root points there. Both work from disk.
`tests/webmcp_questions.md` in the fm-saxml repo has ~30 worked question-to-call examples. Examples:

- References to all fields of table X: `find_references({targetType:"field", parentDocId:"table:X", direction:"incoming", groupBy:"target"})`
- Who can run script X: `who_can_access({docId:"script:X", action:"run"})`
- Everything that eventually calls script X: `traverse({from:"script:X", direction:"incoming", relationshipTypes:["usesScript","triggersScript"]})`
- Hidden fields on a layout: `query_entities({type:"layoutObject", where:[{field:"layoutDocId",op:"eq",value:"layout:X"},{field:"isField",op:"eq",value:true},{any:[{field:"hasHideCondition",op:"eq",value:true},{field:"inPanel",op:"eq",value:true}]}]})`
