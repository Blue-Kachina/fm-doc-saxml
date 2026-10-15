# HTML viewer and WebMCP

## Browsing the docs in a web browser (`--html`)

```bash
fm-saxml build ./MySolution.xml --html
```

`--html` adds `index.html` to the output folder. Double-click it to browse the documentation in any modern browser, with a sidebar, page filter, breadcrumbs and working links between pages. It runs straight from disk, so no web server is needed.

- Browsers don't let a page opened from disk read other files, so each Markdown page is also written as a small script under `_viewer/pages/` (one per page). That's why it's opt-in.
- The Markdown is rendered with [Milkdown Crepe](https://milkdown.dev/), loaded from a CDN (esm.sh and jsDelivr). Viewing needs internet access, at least until the browser has cached it. The `.md` files are unchanged and still work on their own.
- Calculations are written as ` ```filemaker ` code blocks, and the viewer highlights them with FileMaker calculation syntax via [fmscriptui](https://github.com/Blue-Kachina/fmscriptui). If that can't load, calculations still show, just without highlighting.
- Keep `index.html` and `_viewer/` together if you move or zip the folder.

## Agent-ready HTML (`--webmcp`)

```bash
fm-saxml build ./MySolution.xml --webmcp --serve    # build, then serve at http://127.0.0.1:8765
fm-saxml serve ./MySolution_docs                     # serve docs built earlier
```

`--webmcp` adds [WebMCP](https://github.com/webmachinelearning/webmcp) tools to the viewer (and turns on `--html`). An AI agent working in the browser can then ask the solution questions that would take a person many clicks, and open the answers in the viewer. The tools work from the model behind the docs, not the rendered pages. Every entity type and attribute, the reference graph, and each privilege set's effective access are written under `_viewer/data/` and loaded as needed.

| Tool | Answers |
|---|---|
| `describe_schema` | Which entity types exist, and the fields of each that can be queried |
| `get_solution_overview`, `get_current_page`, `get_entity` | What's in the solution, what's on screen, and everything about one entity |
| `search_entities` | Find anything by name, or by comment, calculation or step text |
| `query_entities` | Filter one type by its attributes ("unstored calcs that use related fields", "layout objects with a hide condition") |
| `find_script_steps` | Steps by name, text, regex, script or folder, or by what they set ("every Set Field on `Invoices::Total`") |
| `find_references` | What uses an entity, or every field of a table, and what it uses |
| `find_unreferenced` | Dead-code candidates: scripts, layouts, value lists, custom functions or fields nothing references |
| `traverse` | References followed more than one step: everything that eventually calls a script, or the path between two table occurrences |
| `who_can_access`, `what_can_access` | Which privilege sets and accounts can run a script, open a layout, or view, edit, create or delete records, and why |
| `query` | A JSON pipeline (`from`, `where`, `join`, `joinRefs`, `joinAccess`, `select`, `groupBy`, `sort`, `limit`) for questions no other tool covers |
| `navigate_to`, `show_results` | Open a page (for a script step, its script, with the step highlighted), or show a list of entities picked by hand |

On a script, table or layout page there are also tools for that entity: `list_steps_in_this_script`, `list_fields_in_this_table` and `list_objects_on_this_layout`. The last one finds hidden objects: those with a "Hide object when" calculation, and those that only show in a tab panel, slide panel or popover.

- **Results show in the viewer.** Every query tool also opens a results view, grouped by type (steps under their script, objects under their layout, accounts under their privilege set) and by file in a multi-file build. Pass `display: false` to skip it. The view has a link that runs the query again, so it can be bookmarked or shared, and it keeps a list of recent queries. With `--webmcp`, the search box looks up every entity name in every file, grouped by type. Press Enter to also search text, and use the Advanced search form for common filters.
- **Access answers explain themselves.** Each one gives the reason: `[Full Access]`, a setting for the whole category, the object's own row in a custom list, or the "[Any new …]" row. External accounts (identity-provider groups) and disabled accounts are flagged.
- **Status badge.** The viewer's header shows whether the tools reached the browser: "WebMCP · 15 tools", "WebMCP off: opened from disk", or "WebMCP not in this browser". Click it for the reason and what to do. On a page opened from disk, clicking copies the `fm-saxml serve` command for that folder.
- **Read-only.** No tool changes anything. No tool runs code an agent writes: `query` only takes JSON steps. The data is written from the scrubbed model, and the scrubbing guard checks `.js` files too.
- `tests/webmcp_questions.md` lists 30-odd plain-English questions and the calls that answer them.

### Open it from localhost, not from disk

Browsers only give WebMCP to pages served from a web address. A page opened by double-clicking `index.html` (`file://`) doesn't get it, so agents in the browser can't see the tools. `fm-saxml serve <docs folder>` (or `--serve` on `build`/`render`) serves the folder at `http://127.0.0.1:8765` and opens it there. Localhost counts as a secure origin, so WebMCP works.

- The server listens on 127.0.0.1 only.
- It serves nothing outside the folder.
- It refuses requests addressed to any other host name.
- `--port` picks the port (a free one is used if it's taken), `--no-open` skips opening the browser, and Ctrl+C stops it.
- Both work only on a `--webmcp` build.

### Agents without WebMCP

Some browser agents have no WebMCP. Claude in Chrome is one: it never gets `document.modelContext`. They can reach the same tools in two other ways:

- **By URL.** `index.html#/results?q=<URL-encoded {"tool": "<name>", "args": {...}}>&format=json` runs a tool and shows the result as JSON text (`<pre id="fm-result-json">`). Without `&format=json`, the same link shows the grouped results view.
- **In JavaScript in the page.** Call `FMDocs.tools.<name>.execute(...)`.

The **For AI agents** link in the header (`#/agents`) lists every tool with its argument schema and example links that run against this solution. `--webmcp` also writes an `llms.txt` at the top of the docs folder that points agents there. Both work on a page opened from disk too.

### Browser support

WebMCP is still a draft. It's in Chrome from version 149 as an origin trial (or turned on under `chrome://flags`) and in Edge 147 behind a flag. ChatGPT's desktop browser calls it "site tools": it's on in Settings > Browser > Permissions, for models that support it.

The viewer registers its tools through `document.modelContext` (or the older `navigator.modelContext`), including when the browser adds it after the page has loaded. The same tools are always available on `window.FMDocs.tools`, so an agent that drives the browser can use them anywhere, and so can a script:

```js
await FMDocs.tools.query_entities.execute({type: "field", where: [{field: "global", op: "eq", value: true}]})
```
