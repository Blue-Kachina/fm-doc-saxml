# HTML viewer and WebMCP

## Browsing the docs in a web browser (`--html`)

```bash
fm-saxml build ./MySolution.xml --html
```

`--html` adds `index.html` to the output folder. Double-click it to browse the documentation in any modern browser, with a sidebar, page filter, breadcrumbs and working links between pages. It runs straight from disk, so no web server is needed.

- Browsers don't let a page opened from disk read other files, so each Markdown page is also written as a small script under `_viewer/pages/` (one per page). That's why it's opt-in.
- The Markdown is rendered with [Milkdown Crepe](https://milkdown.dev/), bundled into `_viewer/vendor/` (about 1.7 MB, with its licence notices). The viewer makes no network requests, so it works offline. The `.md` files are unchanged and still work on their own.
- Calculations are written as ` ```filemaker ` code blocks, and the viewer highlights them with FileMaker calculation syntax via [fmscriptui](https://github.com/Blue-Kachina/fmscriptui). Other code blocks show without highlighting.
- Keep `index.html` and `_viewer/` together if you move or zip the folder.

## Layout preview

With `--html` (or `--webmcp`), the viewer draws each layout the way FileMaker's Layout mode shows it: its parts as bands and every object at its real position and size, with the theme's colours, borders and fonts (*Styled*) or as outlines coloured by kind (*Wireframe*: field, text, button, portal, tab or slide control, popover, shape). It is for finding things: where a field is shown, what the button in the corner runs, what's hidden on another tab, in a popover, or off the edge of the layout. `--no-layout-preview` leaves it out. The Markdown pages don't change.

- **Where it shows.** A *Layout preview* block above each layout page's Markdown (folded on narrow screens), and a full page at `#/layout?doc=<layout docId>&file=<file>`. Layout object pages and field pages have *Show on layout* links, and so does every layout object in the `--webmcp` results view. In a multi-file build, a field's page also links to the layouts of other files that show it.
- **Containers.** Portals, popovers, tab and slide controls, button bars and groups aren't labelled with their object names, as in FileMaker; *Wireframe* shows the name as a small caption in the container's corner. The click details name the container an object is in (`portal "portal_lines"`), and the side panel names each popover by its title, its button's label, or its own name.
- **Find on this layout** searches labels, field names, object names, scripts, button actions, tooltips, tab labels and object types. Matches are outlined, everything else dims; ↑ / ↓ (or Enter / Shift+Enter) step through them, opening the tab or popover a match is in.
- **Click** an object for its details (type, field, script, hide condition, bounds, z-order) and a link to its page. When several objects are under the point, they are listed front to back, so a covered one can still be picked. Hover shows a short summary.
- **Panels and popovers.** The side panel chooses which tab or slide each control shows (the tab strip in the drawing works too), opens popovers, and hides the objects that have a hide condition (they are drawn with a red striped outline). Tab controls open on their default tab.
- **Problem badges** count objects outside the layout (left or above its edge, past its width, or below its last part), tiny ones (2 pt or less in either direction; lines aren't counted), exact duplicates (same type, field, position, container, label, script, calculations and triggers) and, when the docs have styles, covered ones (see below). Click a badge to step through them. Popover panels aren't checked against the edges: they float over the layout, and are often placed away from their button.
- **Deep links:** `&select=<object docId>` opens with that object selected, `&highlight=<docId>,<docId>` with a set outlined, `&q=<text>` with a search. Object ids alone (the part after `::`) work too.
- **Zoom:** Fit (the default), 100% and 200%. One point is one CSS pixel at 100%.
- **Styled / Wireframe.** *Styled* (the default when the docs have styles) uses the theme: each object's and part's normal-state style, worked out when the docs are built from the theme's CSS, the object's named style and its own local CSS. Only background and text colours, borders (colour, width, style, corner radius), font family, size, weight and style, text alignment (both ways) and padding are drawn; gradients, background images, shadows, hover and focus states and the text's own character formatting aren't. *Wireframe* is the outline view, easier for finding small or overlapping objects. The choice is remembered in the browser. Styles need the scrubbed theme and layout XML that `build` writes to `raw/`: a build with `--no-raw-xml` or `--no-include-json`, or a `render` from `model.json`, is wireframe only (the build says so).
- **Covered objects.** With styles, a fourth badge counts objects hidden under an opaque object in front of them that shows whenever they do (not on another tab, in a popover or with a hide condition). An object's own contents don't count: button bar segments fill their bar.
- **Icons and images.** Button and popover button icons are drawn where FileMaker puts them (icon only, or above, below, left or right of the label, at the icon's size). An icon FileMaker paints in the style's icon colour (a "glyph", most SVG icons) takes that colour in *Styled* (the theme's `-fm-icon-color`) and the kind's colour in *Wireframe*; other images are drawn as they are, faded in *Wireframe*. With `--layout-images`, graphics show their picture too. They come from the export's `<LibraryCatalog>` (FileMaker 26), or from the icon stored on the object itself (FileMaker 22). Click an object to see its icon or image, and why one wasn't included.

**Which images are included.** SVG button icons are included by default. Pictures (PNG, JPEG, GIF) and SVG graphics are included only with `--layout-images`, because they can show logos or client artwork, and the scrubber can't check what's in a picture. Each image is written once per file, as `_viewer/data/<file>/library/<key>.js`, and loaded when a layout that uses it is shown. An image over 256 KB, a PDF, or another kind a browser can't show isn't written; the build prints how many were written and how many were skipped, and why. SVGs are written as text (so the scrubbing guard reads them too), stripped of scripts, event attributes, links to other files, comments, metadata and editor-only markup, and shown only as images (`<img>` or a CSS mask), where scripts never run. FileMaker's record of each image's original file name (sometimes a full path with a user name) is never written, and is also taken out of `raw/layouts.json`. Without `--layout-images`, `raw/layouts.json` also leaves out the pictures stored on layout objects (graphics, and PNG or JPEG icons; SVG button icons stay): the element keeps its `MAIN` stream, which says what the picture was, but not its bytes. SVGs also lose animation elements, CSS `@import`, `image-set()` and backslash escapes, and `<a>` links are unwrapped (their shapes stay). A docs folder rendered from a `model.json` has no images.

Coordinates are points from the layout's top left. FileMaker stores a nested object's bounds relative to its container (portal, tab panel, button bar, popover panel); the preview adds them up, so its bounds are absolute. The *Bounds* table on a layout object's page, and `bounds` in `entities.json` and the WebMCP records, keep FileMaker's relative numbers. The data is one small script per layout, `_viewer/data/<file>/layouts/<n>.js` (about 100 bytes per object, plus a small table of the layout's distinct styles that objects point into), loaded when the layout is shown, plus an `index.js` that lists the layouts and which objects show each field. A docs folder rendered from a `model.json` (`fm-saxml render`) has no tab-strip geometry: every control opens on its first tab, with tabs of equal width.

Scripts in the page (and agents without WebMCP) can drive the preview, with or without `--webmcp`:

```js
await FMDocs.preview.open("layout:Contrat - Fiche", {highlight: ["12", "47"]})  // or {select: docId} / {q: "text"}
FMDocs.preview.highlight(["layoutObject:Contrat - Fiche::12"])  // on the preview on screen; returns the docIds found
FMDocs.preview.clear()
```

`open` takes a layout docId or name (`file` narrows it in a multi-file build). It uses the preview already on screen, unfolds the layout page's block, or else opens the full page, and resolves once it is drawn, with `{layout, file, url, highlighted}`.

## Agent-ready HTML (`--webmcp`)

```bash
fm-saxml build ./MySolution.xml --webmcp --serve    # build, then serve at http://127.0.0.1:8766
fm-saxml serve ./MySolution_docs                     # serve docs built earlier
```

`--webmcp` adds [WebMCP](https://github.com/webmachinelearning/webmcp) tools to the viewer (and turns on `--html`). An AI agent working in the browser can then ask the solution questions that would take a person many clicks, and open the answers in the viewer. The tools work from the model behind the docs, not the rendered pages. Every entity type and attribute, the reference graph, and each privilege set's effective access are written under `_viewer/data/` and loaded as needed.

| Tool | Answers |
|---|---|
| `describe_schema` | Which entity types exist, and the fields of each that can be queried |
| `get_solution_overview`, `get_current_page`, `get_entity` | What's in the solution, what's on screen, and everything about one entity |
| `search_entities` | Find anything by name, or by comment, calculation or step text |
| `query_entities` | Filter one type, several (`types`) or every type by their attributes ("unstored calcs that use related fields", "layout objects with a hide condition", "everything changed since a date"), optionally sorted (`sort`). Types that lack a field in the filter are skipped and listed in `skippedTypes` |
| `find_script_steps` | Steps by name, text, regex, script or folder, or by what they set ("every Set Field on `Invoices::Total`") |
| `find_references` | What uses an entity, or every field of a table, and what it uses (places that name it in text are marked `byName`; `includeByName: false` leaves them out) |
| `find_unreferenced` | Dead-code candidates: scripts, layouts, value lists, custom functions or fields nothing references |
| `find_indirection` | Places that name a field, script, layout or object in text (`GetField`, Perform Script by name, `ExecuteSQL` ...), by class: hardcoded, traced, opaque, broken, safe — see [Names written in text](./indirection.md) |
| `rename_impact` | Before a rename: what names the entity in text and would break, what captures its name safely, and what takes a name from data |
| `traverse` | References followed more than one step: everything that eventually calls a script, or the path between two table occurrences |
| `who_can_access`, `what_can_access` | Which privilege sets and accounts can run a script, open a layout, or view, edit, create or delete records, and why |
| `query` | A JSON pipeline (`from`, `where`, `join`, `joinRefs`, `joinAccess`, `select`, `groupBy`, `sort`, `limit`) for questions no other tool covers |
| `navigate_to`, `show_results` | Open a page (for a script step, its script, with the step highlighted), or show a list of entities picked by hand |
| `locate_layout_object` | Where something is shown on the layouts: by field (docId, `Table::Field`, which is tried as the docId first, or a TO::field or field name), text, the script a button runs, or object type, on one layout or all. In a multi-file build a field docId also finds the other files' layouts that show the field |
| `objects_at` | Hit test on a layout: the objects at a point or in a rectangle, front to back |
| `layout_problems` | Objects outside the layout, tiny ones, exact duplicates and covered ones (the preview's badges), as rows |

On a script, table or layout page there are also tools for that entity: `list_steps_in_this_script`, `list_fields_in_this_table` and `list_objects_on_this_layout`. The last one finds hidden objects: those with a "Hide object when" calculation, and those that only show in a tab panel, slide panel or popover. A layout page, and its full-page preview, also has `show_on_this_layout` (`query`, `docIds`, `objectType`, `field`): it highlights the matches on the preview on screen, opening it if it is folded, and returns them.

The three layout tools and `show_on_this_layout` read the [layout preview](#layout-preview)'s data, so a build with `--no-layout-preview` doesn't have them. Each object they return has:

- `bounds` `{top, left, bottom, right, width, height}`, **absolute**: points from the layout's top left. The `bounds` of a `layoutObject` record (from `get_entity`, `query_entities` …) are FileMaker's own, relative to the container for nested objects.
- `part`, `shownIn` (the tab panel, slide panel or popover it only shows in, nearest first, with the tab's `label`), `visibleAtOpen` (on the default tab, not in a popover) and `z` (paint order, 1 = back).
- `style`: its resolved normal-state style as plain CSS (`background-color`, `color`, `font-size`, `border-color` …, and `icon-color`), when the docs have styles; `coveredBy`: the docId of the opaque object that hides it.
- `icon` (buttons) `{placement, size, libraryKey, kind, included, glyph?, note?}` and `image` (graphics) `{libraryKey, kind, included, note?}`: `note` says why an image wasn't included.
- `position`: where it is in words, e.g. "Body, top right, inside the 'Devis' tab", or "Header, outside the layout (214 pt past its right edge)".
- `previewUrl`: opens the preview with the object selected. Results also carry `layouts`, one per layout with a `previewUrl` that highlights all of its matches; the results view shows these as *Show on layout* links.

- **Results show in the viewer.** Every query tool also opens a results view, grouped by type (steps under their script, objects under their layout, accounts under their privilege set) and by file in a multi-file build. Pass `display: false` to skip it. The view has a link that runs the query again, so it can be bookmarked or shared, and it keeps a list of recent queries. With `--webmcp`, the search box looks up every entity name in every file, grouped by type. Press Enter to also search text, and use the Advanced search form for common filters.
- **Access answers explain themselves.** Each one gives the reason: `[Full Access]`, a setting for the whole category, the object's own row in a custom list, or the "[Any new …]" row. External accounts (identity-provider groups) and disabled accounts are flagged.
- **Status badge.** The viewer's header shows whether the tools reached the browser: "WebMCP · 15 tools", "WebMCP off: opened from disk", or "WebMCP not in this browser". Click it for the reason and what to do. On a page opened from disk, clicking copies the `fm-saxml serve` command for that folder.
- **Read-only.** No tool changes anything. No tool runs code an agent writes: `query` only takes JSON steps. The data is written from the scrubbed model, and the scrubbing guard checks `.js` files too.
- `tests/webmcp_questions.md` lists 30-odd plain-English questions and the calls that answer them.

### Open it from localhost, not from disk

Browsers only give WebMCP to pages served from a web address. A page opened by double-clicking `index.html` (`file://`) doesn't get it, so agents in the browser can't see the tools. `fm-saxml serve <docs folder>` (or `--serve` on `build`/`render`) serves the folder at `http://127.0.0.1:8766` and opens it there. Localhost counts as a secure origin, so WebMCP works.

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
// Everything changed since a date, across every type, newest first
await FMDocs.tools.query_entities.execute({where: [{field: "modified.timestamp", op: "gte", value: "2026-10-03"}],
    fields: ["modified.timestamp", "modified.accountName"], sort: {field: "modified.timestamp", desc: true}})
```
