# Layout preview: plan

Status (2026-11-20): P0 done (findings in section 7); P1 and P2 built (section 8); P3 built
(section 9); P4 built, with P2's "fully covered" badge (section 10); P5 built (section 11);
review findings fixed (section 12). Not covered yet: tab / slide control toggles on a real export.

## 1. Goal

The HTML viewer draws each layout as FileMaker shows it in Layout mode: parts, every object at its
real position and size, and (later) theme styling and icons. The main use is **finding things**:

- "Where is the `Licence::cleLicense` field on this layout?"
- "What is that button in the top right, and what script does it run?"
- "Which objects are hidden: in a closed popover, on another tab panel, behind something else,
  or outside the visible area?"

The same features are WebMCP tools (`window.FMDocs.tools`), so an agent can answer the same
questions and show the answer on the preview.

The preview is a viewer-only feature. The Markdown pages stay as they are (plain for LLMs and
GitHub), as with the fmscript blocks.

## 2. What we already have

Checked against `exports/2026-11-20_B_disRenewalUniverse`:

| Need | Source | Status |
|---|---|---|
| Object bounds, type, part, parent object, field, label, hide condition, tooltip, triggers | `layoutObject` records (`_viewer/data/<key>/layoutObject.js`, `bounds` already there) | ✅ in the model |
| Tab/slide/popover containment | `_derive_layout_object` → `shownIn`, `inPanel` | ✅ |
| Layout width, parts and heights | layout entity (G4a: width, parts, `definitionKind`) | ✅ |
| Named style and local CSS per object | `localStyle {type,name,displayName}` (G4b) + `<LocalCSS>` CDATA in `raw/layouts.json` | ⚠️ the name is in the model; the CSS text is only in raw/ |
| Theme CSS (base + custom styles, all states) | `<CSS>` in `raw/themes.json` (never scrubbed) | ⚠️ raw only |
| Portal rows, sort, initial row | `<Portal><Options index show>` → `portal {initialRow, rows, sort}` | ✅ in the model (P0) |
| Button icons and images | `<LibraryReference key>` → `<LibraryCatalog>` (SaXML 2.3), or the icon inline on the object (SaXML 2.2); both parsed in P5 (`parser/extractors/library.py`), kept beside the model | ✅ (P5) |
| Anchoring and auto-resize | object `<Options>` bits 28–31 (P0) | ⚠️ decoded in P0, not in the model |

**Conclusion:** a geometry-only preview (phases 1 to 3) needs **no parser work**. Styling needs a
CSS step in Python, and icons need the `LibraryCatalog` parsed.

## 3. Design decisions (recommended)

1. **Use DOM elements, not Canvas.** Each object is an absolutely positioned `<div>` inside a
   scaled layout box. With DOM elements, hover, click, focus, text, borders and radii come for
   free; the theme CSS maps almost directly onto them; search highlighting is a class toggle; and
   Playwright tests can query them. Layouts hold hundreds of objects, not tens of thousands. Use
   Canvas only if a real layout turns out too slow (check the biggest layout in task_53301).
2. **Use one data file per layout, loaded on demand:** `_viewer/data/<key>/layouts/<n>.js` →
   `FMDocs.layoutPreview(key, docId, {...})`. It's a classic script, so it works over `file://`. A
   big solution must not load every layout's geometry up front.
3. **Write the preview with `--html`, not only with `--webmcp`.** Locating things helps people
   who never use an agent. The WebMCP tools build on the same files. Add an opt-out flag,
   `--no-layout-preview`.
4. **Python resolves the styles.** Python already has the theme and LocalCSS text. It does the
   cascade (theme base → named custom style → local CSS) and writes each object's final values
   as a small whitelist of plain CSS properties, deduplicated into a per-layout style table. The
   browser doesn't parse FileMaker CSS.
5. **Use the same coordinates FileMaker uses**: points, origin at the layout's top left, plus a
   zoom control (fit width / 100% / 200%).

## 4. Phases

### P0: Check the source data (short, before any UI)

- [x] **Coordinate system.** Are `Bounds` absolute to the layout, or relative to the part? Are
      objects inside a portal at their row-1 position? Are popover panel contents relative to the
      panel? Test on EverythingBagel with objects in several parts, then compare with a screenshot
      from FileMaker's Layout mode. (Data answers it, see 7.1; the screenshot check is still a
      manual step for P1.)
- [x] **Tab and slide controls.** Find the default front panel (an attribute or option?).
- [x] **Z-order.** Confirm that `ObjectList` order is back-to-front.
- [x] **Object `Options` bits.** Note which bits we can name (anchoring, "hide in Find mode" is
      already known). If nothing decodes cleanly, leave anchoring out.
- [x] **Biggest layouts.** Count objects on the five largest layouts in task_53301 and DGC_UAT, and
      check the data-file size per layout. (Done on disRenewalUniverse, NEXUS, DRCC and DGC_UAT;
      task_53301 not checked.)

### P1: Wireframe preview (geometry only)

- [x] `render/html/layout_preview.py`: model → per-layout data file: `{width, parts:[{type, top,
      height}], objects:[{id, type, bounds, part, parentId, label, field, z, flags}]}`. Use short
      keys and compact JSON.
- [x] Show it on the layout page: a **Preview** block above the Markdown (folded by default on
      small screens), plus a full-page route `#/layout?doc=<docId>&file=<key>`.
- [x] Draw parts as labelled bands. Give each object type a neutral outline and fill (field, text,
      button, portal, panel and so on), with the label or `<<field>>` text clipped inside.
- [x] Hover shows a tooltip: type, name, field, bounds. Clicking shows a details panel with a link
      to the object's page (`LayoutObjects/<layout>/<id>.md`).
- [x] Both themes work (nord / nord-dark), and the page works at phone width (preview scrolls
      inside its own box).

### P2: Finding things (the main value)

- [x] **Search box on the preview**: matches label, field name, object name, script name and
      tooltip. Matches get a strong outline, everything else dims. Show a hit count and next/previous
      buttons, and scroll the hit into view.
- [x] **Deep links**: `#/layout?doc=…&select=<objectDocId>` (or `&highlight=id,id,…`) opens with the
      objects selected. Add a "Show on layout" link to:
      - every layout object page,
      - every `layoutObject` row in the results view (`#/results`),
      - each field page's "Used on layouts" list, which highlights all objects showing that field.
- [x] **Layers panel**: choose which panel is shown for each tab and slide control; show or hide
      popover contents (drawn as a floating panel next to their button); toggle objects that have a
      hide condition (striped outline).
- [x] **Stacked objects**: clicking a point lists every object under it, front to back, so you can
      pick one that's covered by another.
- [x] **Problem badges** (counts in the preview header, each a filter):
      - outside the layout (left < 0, right > width, or below the last part). The existing tool
        description says these are "not detected"; now they are.
      - zero or tiny size (≤ 2 pt in either direction),
      - [x] fully covered by an opaque object above it (needs styles, so this badge came with P4),
      - exact duplicates (same type, field and bounds).

### P3: WebMCP / `window.FMDocs`

Add these tools to `templates/webmcp.js`. They use the same per-layout data, and the results view
can link back to the preview.

- [x] Page tool on layout pages: `show_on_this_layout({ query?, docIds?, objectType?, field? })`
      highlights matches on the preview and returns them with bounds.
- [x] `locate_layout_object({ layout?, field?, text?, script?, file? })` works across layouts:
      "where is X shown?". Each result has `layout`, `part`, `bounds`, `shownIn`, a `previewUrl`, and
      a plain-language position ("Body, top right, inside the 'Devis' tab").
- [x] `objects_at({ layout, x, y } | { layout, rect })`: hit test, front to back.
- [x] `layout_problems({ layout?, kinds? })` returns the P2 badges as rows.
- [x] JS API for other scripts and agents without WebMCP:
      `FMDocs.preview.open(docId, {highlight})`, `FMDocs.preview.highlight(ids)`, `FMDocs.preview.clear()`.
- [x] URL route for agents that can only read pages:
      `#/results?q={"tool":"locate_layout_object",…}&format=json` works like the other tools.
- [x] Add the new tools to the `#/agents` guide and `llms.txt` (collected by `_TOOL_NAME_RE`).

Not planned: returning an image of the preview to the agent. The bounds plus the position text
are enough for an agent, and a person sees the highlight on screen.

### P4: Theme styling

- [x] `analyze/layout_css.py`: parse theme `<CSS>` and `<LocalCSS>` (the FileMaker dialect:
      `rgba(%,%,%,a)`, `-fm-font-family(a,b,…)`, `-fm-text-vertical-align`, `self:normal .self`,
      `.inner_border`, `.text`). Resolve each object's `:normal` style: theme element style →
      `<element>.<FM-custom-style>` → local CSS.
- [x] Keep only these properties: background-color, border colours/widths/styles/radii, color,
      font-family/size/weight/style, text-align, vertical alignment, padding. Leave gradients and
      images out at first.
- [x] Add a per-layout style table, with each object pointing to an entry. A toggle switches
      between "Styled" and "Wireframe" (decided: Styled is the default when styles exist; the
      choice is remembered per browser).
- [x] Unit tests on EverythingBagel themes, plus a fixture for every dialect function we handle.

### P5: Icons and images

- [x] Parse `<LibraryCatalog>` (key → streams; SVG, PNG, JPEG, GIF), and inline icons (SaXML 2.2).
      The key is kept per object in the preview data (`ic` / `im`), not in the contract model.
- [x] Write each image once per file, `_viewer/data/<key>/library/<libKey>.js`, and use it for
      button icons and graphics. (Container placeholders: none seen in any export, not done.)
- [x] **Scrubbing:** decided: SVG button icons by default, pictures and SVG graphics only with
      `--layout-images`; 256 KB cap per image, skips counted in the build output.
- [x] Coverage report: move `LibraryCatalog` from "skipped" to "parsed" (and a graphic's `<Graphic>`).

### Out of scope

- Record data (portal rows, field contents, web viewers, charts): placeholders only.
- Browse mode behaviour: script triggers, button actions, resizing with anchoring (unless P0 finds
  the bits).
- Matching FileMaker's text rendering pixel for pixel.

## 5. Tests

- Python: per-layout data-file golden tests on EverythingBagel (parts, bounds, parent links,
  z-order); CSS resolution unit tests (P4); `LibraryCatalog` parse (P5).
- Browser (Playwright, `uv run --with playwright pytest`, skipped without Chrome): preview draws
  the right number of objects; search highlights the expected ids; a deep link selects the object;
  tab and popover toggles change what's visible; the new WebMCP tools return bounds and
  `previewUrl` (stub `document.modelContext` as in `tests/test_webmcp.py`).
- Manual: compare 3 or 4 disRenewalUniverse layouts (`Contrat - Fiche`, `Contrat - Liste`, one
  with popovers) side by side with FileMaker Layout mode.

## 6. Open questions

1. Preview on by default with `--html`, or opt in like `--webmcp`? (Recommended: on by default,
   with `--no-layout-preview`.)
2. Where does it go on the layout page: inline above the Markdown, a separate route, or both?
   (Recommended: both, inline folded.)
3. Images and icons (P5): include them by default? They can show logos or client artwork that
   scrubbing can't catch.
4. Is styling (P4) worth doing, or is a wireframe enough for finding things? P1–P3 work without it.
5. Should the preview also go into the Markdown as an SVG file for GitHub/IDE readers?
   (Recommended: no; it would break the "Markdown stays plain" rule.)

## 7. P0 findings (2026-11-20)

Checked on EverythingBagel (root and `samples/EverythingBagel_mac_run`), `disRenewalUniverse.xml`
(FM 22, SaXML 2.2.3), `NEXUS_saxml.xml` (FM 22), and the ignored `samples/has_indirection/DRCC.xml`
and `DGC_UAT.xml` (FM 26, SaXML 2.3; 37,000 objects, 814 layouts). The scripts are throwaway
(session scratchpad `p0/`). Note: the existing `2026-11-20_B_disRenewalUniverse` export was built
from a newer FM 26.1.1 / SaXML 2.3.0.1 export, not the FM 22 `disRenewalUniverse.xml` in the repo.

### 7.1 Coordinates: nested, not flat

- **Top-level objects** (`<Part><ObjectList>`) are **absolute to the layout's top left**, not
  relative to their part. `<Part><Definition absolute size>` gives each part's top and height.
  Proof: thousands of objects whose top is inside their part's absolute range but would be outside
  it if relative (e.g. Footer objects at top ≥ 677 in a 28 pt footer); no object fits only the
  relative reading. (EverythingBagel alone can't tell: its one Body starts at 110 and is 658 high.)
- **Children of a container are relative to the container's top left**: portal rows, tab and
  slide panels, button bar segments, button groups / grouped objects (`<GroupedButton>`), popover
  panel contents. Thousands of children fit only inside `[0,0,h,w]` of their parent, never inside
  the parent's absolute rect.
  - **Portal**: children are at their **row-1** position (top 0 = top of the first row; 4,621 of
    4,639 children end inside `portal height / rows`; the rest hang over the row edge).
  - **Tab / slide panel**: the `Panel` object's bounds are `0,0,h,w` (the whole control,
    including the tab strip), so panel contents are effectively relative to the control.
  - **Popover**: the `PopoverPanel` bounds are **absolute** (layout coordinates), even when its
    Popover Button is nested in a portal, button bar or group. `PopoverPanel@position` is the
    side: `0` right, `1` below, `2` left, `3` above, usually 11 pt (the arrow) from the button's
    absolute rect; about a third (225 of 649) were moved by hand and are not adjacent. Contents are relative
    to the panel.
- **The model stores the raw bounds.** `layoutObject.bounds` (Markdown "Bounds" table, viewer
  data, WebMCP records) is relative for every nested object. P1 must compute absolute rects:
  add each ancestor's top/left, stopping at (and not adding to) a `PopoverPanel`.

### 7.2 Z-order

- `ObjectList` order is **back to front**. No attribute holds it: a `LayoutObject` only has
  `hash id type name kind` (popover panels add `Options position`). A rectangle that encloses a
  sibling comes before it 4,106 times and after it 17 times (DGC_UAT; 261/0 in NEXUS, 154/0 in
  DRCC).
- It is **not id order** (555 of 3,876 object lists in DGC_UAT are not in id order). The parser
  walks objects pre-order in document order (`fallback_index` in `_collect_layout_objects`), which
  is the right paint order (container, then its children), but the model does not keep that index.
  P1 should keep it as `z`.

### 7.3 Default tab / slide panel

- `<TabControl default visible height modifier Location>`: `default` is the **0-based index of
  the default front tab** (values 0, 2, 3 seen; always < the panel count). `visible` was equal to
  `default` in all 51 controls, so it can't be told apart. `height` = tab strip height;
  `Location` is 0–4 (likely tab justification) and `modifier` a width setting (not confirmed).
- `<TabPanel size absolute>` = each **tab's label width and x offset** in the strip (115 at 0,
  115 at 114). The tab label is the panel's `<Calculation><Text>`.
- `<SlideControl>` has **no default attribute** (`<Options>` 0/1/3, probably navigation dots /
  swipe). Show the first panel.

### 7.4 Object `<Options>` bits

| Bit | Value | Meaning | Confidence |
|---|---|---|---|
| 28 | 0x10000000 | anchor **top** | high (with 29–31: geometry correlation) |
| 29 | 0x20000000 | anchor **left** (on for 99%) | high |
| 30 | 0x40000000 | anchor **right**: those objects end 0–11 pt from the layout's right edge | high |
| 31 | 0x80000000 | anchor **bottom**: portals, tab/slide controls, background rectangles that stretch down | high |
| 2 | 4 | has a "Hide object when" calc (4,622 of 4,622) | high |
| 8 | 256 | "Apply in Find mode" (covers every `findMode="True"`, also left on after the calc is removed); the model already reads `findMode` | medium |
| 14 | 16384 | has a tooltip | medium |
| 3 | 8 | goes with `<TabOrder>` (in tab order?) | low |
| 16 | 65536 | only on buttons / grouped buttons | unknown |
| 0, 1, 4, 6, 9, 12, 13, 15, 24 | | type-specific (12/13 only on lines; 4/6 on edit boxes, portals, lines) | unknown |

Anchoring is usable for a "how it resizes" hint and for P2 badges, but FileMaker screenshots
should confirm bits 28–31 before the viewer resizes anything (still out of scope).

### 7.5 Portal rows

Already in the model: `layoutObject.portal = {initialRow, rows, allowDeletion, sort}` from
`<Portal><Options index show>`. Row height = portal height / `rows`; draw row 1 with the
children and the other rows as empty copies.

### 7.6 Sizes

Object counts (all nesting levels) of the five biggest layouts, and the size of a compact
per-layout JSON (id, type, absolute bounds, part, parent, label ≤ 60 chars, field, name, options):
about **100 bytes per object**.

| File | Biggest layouts (objects → compact JSON) | All layouts |
|---|---|---|
| disRenewalUniverse (34 layouts) | Contrat - Fiche 220 → 22 KB; CONTRAT_pourMigration 141 → 14 KB; Contrat - Liste 88 → 8 KB; Recherche Detaillée 84 → 8 KB; LICENCE 74 → 7 KB | 127 KB |
| NEXUS (87) | ITEM List 148 → 13 KB; Detail View 145 → 12 KB; GROUP List 129 → 11 KB; OPTION List 124 → 11 KB; OPTION Export 85 → 8 KB | 210 KB |
| DRCC (189) | Member Main 272 → 26 KB; MEMBER_STAGING 200; Member Advanced Search Criteria 180; Payment Schedule 164; Member Payment 155 | 574 KB |
| DGC_UAT (814) | Globals 1,065 → 114 KB; Invoice List Create 969 → 92 KB; Surplus List Create 957; Discount List Create 924; Globals backup 877 | 3.7 MB |

So one lazily loaded file per layout is right (≤ ~115 KB before styles), and DOM elements are fine
(≈ 1,000 positioned divs is the worst case seen).

### 7.7 LibraryCatalog and icons

- `<LibraryCatalog><BinaryData><LibraryReference id key/><StreamList><Stream name type size>`.
  `MAIN` (type `id`) names the main stream: `SVG ` (note the space), `PNGf`, `JPEG`, `PDF `.
  Other streams: `SIZE` (hex, width/height as two 16-bit values), `GLPH` (SVG icon that takes the
  style's colour), `DPI_`, `FORK`, and `FNAM` (the original file name: length-prefixed strings
  XOR 0x5A, sometimes a **full Mac path with a user name**, e.g. `Macintosh HD/Users/<user>/Desktop/…`;
  never write it out unscrubbed). Seen: DGC_UAT 158 SVG, 189 PNG, 4 JPEG, 1 PDF (largest PNG
  68 KB, JPEG 206 KB base64); DRCC has one 1.4 MB PNG (the size cap matters).
- **References, SaXML 2.3 (FM 26)**: `<Button|PopoverButton><IconData type size><BinaryData>
  <LibraryReference id key/>` and `<Graphic><BinaryData><LibraryReference/>`; all 3,008 (DGC_UAT)
  and 480 (DRCC) references resolve by `key`. `IconData@type` 0 = no icon.
- **References, SaXML 2.2 (FM 22: disRenewalUniverse, NEXUS)**: the icon is **inline** in
  `<IconData><BinaryData><StreamList>` (same streams); the catalog there only holds unreferenced
  images (old theme pictures). The root says `binary_under_lo="False"` on 2.3 exports, so an
  option to inline binaries probably exists there too. P5 must read both forms.
- The scrubbed `raw/layouts.json` **keeps** `<IconData type size>` and `<LibraryReference id key>`
  (166 in the disRenewalUniverse export); `raw/` has no library file. File-level
  `<Options>…<Original|Large|Small|Mini>` PNGs are the file's own icon, not layout images.

### 7.8 What this changes in the plan

- P1: compute absolute rects in Python (7.1) and keep document order as `z` (7.2); draw
  tab strips from `TabPanel size/absolute` and show the `default` tab (7.3).
- P1/P3: the Markdown "Bounds" table and the WebMCP `layoutObject.bounds` are relative for nested
  objects; say so (or add absolute bounds) when the preview lands.
- P2: anchoring bits allow an "anchored right/bottom" hint; the "outside the layout" badge must use
  absolute rects, and popovers placed by hand far from their button are normal.
- P5: support inline icons (2.2) and catalog references (2.3); never emit `FNAM`.

## 8. P1 and P2 as built (2026-11-20)

- **Data**: `render/html/layout_preview.py` writes `_viewer/data/<file>/layouts/<n>.js`
  (`FMDocs.layoutPreview(key, layoutDocId, {...})`) and `index.js` (`FMDocs.layoutPreviewIndex`:
  layouts `[docId, n, name, objectCount, page, problemCount]` and `fields: {fieldDocId: [[n, [ids]]]}`).
  Objects are in document order (index = z-order) with absolute `b: [top, left, bottom, right]`
  (ancestors' top/left added, stopping at a popover panel), `pa` = parent's index, short keys (see
  the `build_layout_preview` docstring). Problems `x`: `out`, `tiny`, `dup`, counted in `problems`.
- **Not in the contract**: the front tab (`TabControl@default`), tab strip height, each tab's
  `size/absolute` and `PopoverPanel@position` are parsed (`_preview_geometry` in
  `parser/extractors/layouts.py`) into a private `DocumentModel._layout_geometry`, so no schema or
  golden file changed. A `render` from `model.json` lacks it: first tab, even tab widths.
- **Viewer**: `templates/layout-preview.js` (copied to `_viewer/`, script tag in `index.html` via
  `<!--LAYOUT_PREVIEW-->`), `FMDocs.preview` (`onPage`, `renderRoute`, `urlFor`, `objectLink`,
  `current` with `select/highlight/search/clear/objectsAt`). `index.html` has a `#page-extra` slot
  above the Markdown and the `#/layout?…` route (`body.dataset.rendered = 'layout'`).
- **Flags**: on with `--html`/`--webmcp`; `--no-layout-preview` (build, render) turns it off.
- **Duplicates** are stricter than planned (same container, label, script, calculations and
  triggers too): on disRenewalUniverse the plan's rule flagged 37 objects on `Contrat - Fiche`,
  nearly all stacked buttons or fields with different hide conditions that take turns; now 0.
- **Real data** (disRenewalUniverse, FM 22): 29 layouts, 1,314 objects, 208 KB of layout data
  (largest `Contrat - Fiche`, 220 objects, 43 KB); writing it takes about 0.04 s; each layout
  draws in under 50 ms in Chrome, no console errors. The FM 22 file has popovers but no tab controls.
- **Still manual**: comparing a few layouts side by side with FileMaker Layout mode (section 5).

## 9. P3 as built (2026-11-20)

- **Tools** (`templates/webmcp.js`, section "Layouts"): `locate_layout_object({layout?, field?, text?,
  script?, objectType?, file?})`, `objects_at({layout, x, y} | {layout, rect, within?}, visibleAtOpen?)`,
  `layout_problems({layout?, kinds?})`, all query tools (results view, `display:false`, `#/results?q=…&format=json`).
  They are defined with `layoutTool(...)`, which registers nothing when the manifest has no
  `layoutPreview`; `viewer.py` (`_tool_names`) leaves them out of `llms.txt` then. The page tool
  `show_on_this_layout({query?, docIds?, objectType?, field?})` is registered on layout pages and on
  the full-page `#/layout` route (index.html calls `onRoute` there now); it highlights on the preview on
  screen (unfolding the inline block if needed) instead of opening the results view.
- **Each object**: `bounds` absolute `{top, left, bottom, right, width, height}`, `part`, `shownIn`
  (nearest first, `{docId, kind: tabPanel|slidePanel|popover, name, label}`; same shape as the model's
  plus the tab label), `visibleAtOpen`, `z`, `position` in words, `path`, `previewUrl` (full URL,
  `select=`), and the usual `parent` layout so the results view groups by layout. Results carry
  `layouts: [{layout, docId, count, previewUrl}]` (all matches highlighted), shown as *Show on layout*.
  `layout_problems` adds `problems`, `sameAs` (other duplicates) and `counts`.
- **Position words**: part, then thirds of the layout width (left / center / right) and of the part's
  height (top / middle / bottom) at the object's centre, then containers outermost first ("inside the
  'X' tab", "inside row 1 of the 'P' portal", "inside the 'More' popover"); objects outside the layout
  say how far ("214 pt past its right edge"); "(has a hide condition)" at the end.
- **JS API** (`templates/layout-preview.js`, with plain `--html` too): `FMDocs.preview.open(layout,
  {file, highlight, select, q})`, `highlight(ids)`, `clear()`, plus the data helpers the tools use
  (`describe`, `hitTest`, `matchesText`, `visibleAtOpen`, `shownIn`, `position`, `findLayout`).
  `FMDocs.preview.current` is now null once the preview has left the page.
- **Other**: `list_objects_on_this_layout` no longer says objects outside the layout are "not detected"
  (points at `layout_problems`); `get_current_page` reports `preview: {layoutDocId, selected}`.
- **Real data** (disRenewalUniverse, `--html --webmcp`, 15.5 s build): no change to `_viewer/data`
  (6.6 MB, same bytes as P1/P2); `webmcp.js` +19.8 KB (123 KB), `layout-preview.js` +12.3 KB (60 KB).
  In Chrome: `layout_problems` over all 29 layouts 15 ms (16 outside, all on 8 layouts);
  `locate_layout_object` text over all layouts 14 ms (40 hits), by field docId 2 ms (loads only the
  layouts that show it); `objects_at` 1–7 ms on `Contrat - Fiche`; `show_on_this_layout` 7 ms
  (88 buttons highlighted). No console errors.

## 10. P4 as built (2026-11-20)

- **Source**: the scrubbed `raw/themes.json` and `raw/layouts.json` the build writes just before the
  viewer (`StyleSource.load(<file's docs folder>)`). No second parse of the export, and the CSS
  goes through the same scrubbing as `raw/`. Without `raw/` (`--no-raw-xml`, `--no-include-json`,
  `render` from model.json) the preview is wireframe only and the build says so.
- **Dialect** (`analyze/layout_css.py`, seen on EverythingBagel, disRenewalUniverse, NEXUS and
  DGC_UAT): selectors `[<part> ]<element>[.<style>][:<state>][ .<sub>]` (a missing state is normal,
  a missing sub is `.self`; `header text_box:normal .self` styles text in a header); local CSS uses
  `self` as the element. `rgba(%,%,%,a)` and `rgb()`/hex → `#rrggbb` or `rgba(r,g,b,a)`;
  `-fm-font-family(Display,PostScript;generic)` → `"Display", generic` (sans-serif when none);
  `-fm-text-vertical-align` → `vertical-align: top|middle|bottom` (the viewer turns it into flex
  alignment); points → px; `Npt Npt` radii → one value. Values are rebuilt from parsed numbers or
  checked against fixed words; the viewer checks the property names and characters again.
- **Cascade** (normal state only): element style → `<part> element` → named style
  (`<element>.<LocalCSS@name>`, looked up under a related element when needed: a rectangle's custom
  styles are `shape.…`, button-bar buttons are `button_bar_segment`; that element's base style comes
  first) → the object's own `self:normal` rules. In each, `.self` gives everything, `.inner_border`
  its radii and padding, `.text` its padding. Element names: `ELEMENTS` / `element_for` (a tab
  control's `Panel` is `tab_panel`; groups, grouped buttons and slide panels have no style).
  Parts: `PART_ELEMENTS` plus their `part.FM-…` named styles; the layout background is
  `layout_background`.
- **Data**: `styles` (the layout's distinct resolved styles; four equal sides or corners are
  written as one shorthand, `compact_style`), `sy` on objects and parts, `bg` for the layout
  background. Problems gain `cov` / `covered` and `cv` (the covering object's index).
- **Covered**: an object entirely inside an opaque (`#rrggbb` background) object later in paint
  order, where the front object has no hide condition and no tab / slide panel or popover the one
  behind isn't also in. An object's own contents don't count (button bar segments fill their bar).
- **Viewer**: *Styled* / *Wireframe* buttons (shown only when the layout has styles); Styled is the
  default, the choice is kept in `localStorage` (`fm-saxml-layout-preview-mode`, in try/catch). The
  per-layout rules go into a `<style>` scoped to that preview (`.fm-lp-stage[data-lpm]`). Lines draw
  one border; hide-condition outlines are fainter in Styled. `FMDocs.preview.current.mode` /
  `setMode()`. The layout tools return `style` and `coveredBy`; `layout_problems` has a
  `covered` kind.
- **Real data** (disRenewalUniverse, FM 22, `--html --webmcp`, build 15.2 s / 15.9 s wall, same as
  P3): all 29 layouts styled, 1,313 of 1,314 objects have a style; `_viewer/data` +80,298 bytes
  (layout files 206,670 → 286,968; `Contrat - Fiche` 43 KB → 60 KB with 57 distinct styles);
  `layout-preview.js` +5.6 KB. Writing the preview data takes 0.14 s with styles vs 0.04 s without.
  Every layout opens in Chrome in under 50 ms, no console errors. No object is flagged covered.
- **Not done**: hover/focus/placeholder states, gradients and images, shadows (icon colours,
  `-fm-icon-color`, came with P5), character formatting inside text objects, portal alternate-row colours,
  tab strip styles (`.tab`), body-alternate/current-row colours. A side-by-side check with
  FileMaker Layout mode is still manual.

## 11. P5 as built (2026-11-20)

- **Parser** (`parser/extractors/library.py`): `extract_library` reads `<LibraryCatalog>` into
  `{key: {kind, data, glyph}}` (`RawModel.library`); `object_image` reads an object's
  `<BinaryData>`: a `<LibraryReference key>` (SaXML 2.3) or an inline `<StreamList>` (SaXML 2.2),
  whose key is `i` + a hash of its bytes, so the same icon on many buttons is one entry. Keys that
  aren't safe file names are hashed (`h…`). Only `MAIN`, the main stream and `GLPH` are read: never
  `FNAM`. `_preview_geometry` adds `icon`, `icon_pos` (IconData@type: 1 icon only, 2 above the
  label, 3 below, 4 left, 5 right, matched against button shapes on disRenewalUniverse and DRCC),
  `icon_size` and `image` (`<Graphic><BinaryData>`). The normalizer keeps the images in the private
  `DocumentModel._library` (catalog plus inline icons), like `_layout_geometry`: no schema or golden
  file changed, and a `render` from model.json has no images.
- **Data** (`render/html/layout_preview.py`): objects get `ic: [libKey, placement, size]` and
  `im: libKey`; each layout file a `lib` table `{libKey: {k: kind, g: 1 for a glyph}}`, or
  `{k, x: reason}` when not written (`images`, `size`, `type`, `missing`, `invalid`).
  `write_library` writes each used image once: `_viewer/data/<file>/library/<libKey>.js` →
  `FMDocs.layoutLibrary(key, libKey, {k:'svg', g, svg} | {k, m, d})`. SVG as text (the scrubbing guard
  reads it), sanitized by `sanitize_svg` (lxml without entities or network: drops `script`,
  `foreignObject`, `metadata`, `title`, `desc`, `a`, other namespaces, `on*`, non-`#` hrefs,
  non-`#` `url()`, comments, PIs, DOCTYPE); a glyph gets a rule that fills `fm_fill` / strokes
  `fm_stroke` in black (FileMaker paints those classes whatever their own `fill="none"` says).
  Pictures as base64. The cap (`IMAGE_MAX_BYTES`, 256 KB) is on the written file.
- **What is written**: SVG used as a button icon by default; pictures (PNG, JPEG, GIF) and SVG
  used as a graphic only with `build --layout-images`. PDF, BMP, TIFF: skipped (`type`). The build
  prints "Layout preview icons: N written (K KB); skipped …" with the reasons.
- **Styles**: `-fm-icon-color` from the `.icon` sub-element (theme and local CSS) is resolved as
  `icon-color`; the viewer turns it into `--lp-ic` on the object.
- **Viewer**: icons are absolutely placed inside the object (`.fm-lp-ic.ip1`…`ip5`, label padded
  by the icon's size; icon only hides the label); graphics fill the object (`ipf`, `object-fit:
  contain`). A glyph is a CSS mask (`--src: url(data:image/svg+xml,…)`) painted in `--lp-ic`
  (Styled; falls back to the text colour) or the kind colour (Wireframe); other images are `<img>`
  with a `data:` URL, faded and grey in Wireframe. Slots fill after the library scripts load
  (`.fm-lp[data-images]` = `loading`, then `done`). A graphic whose image wasn't written gets a
  dashed outline (`im-skip`). The details panel and `describe()` (so the layout tools) give `icon` /
  `image` with `libraryKey`, `kind`, `included` and a `note` when skipped.
- **Also fixed**: `raw/layouts.json` kept inline icons' `FNAM` streams (encoded original file
  names, sometimes `Macintosh HD/Users/<user>/…`); `render/json/raw_xml.py` now removes every
  `FNAM` stream from the raw XML. (`fm-saxml scrub`, which writes a whole scrubbed export, still
  keeps them.)
- **Coverage**: `LibraryCatalog` (catalogs) and `Graphic` (layout object) moved from skipped to read.
- **Real data**: disRenewalUniverse (FM 22, all icons inline), `--html --webmcp`: build 15.9 s
  (16.4 s wall), same as P4. 165 icon references → 52 distinct SVGs written, 50,958 bytes in
  `library/`; layout files 286,968 → 302,152 bytes (`ic`, `lib`, `icon-color`); `_viewer/data`
  6,692,042 → 6,758,184 bytes (+66 KB). Writing the library takes about 0.03 s. With
  `--layout-images`: identical (this file's layouts use no pictures; its catalog's 13 PNGs are
  unreferenced theme images). All 27 non-empty layouts open in Chrome with icons in under 50 ms,
  163 glyphs and 2 colour SVGs drawn, no console errors. DRCC (FM 26, catalog references,
  `--layout-images`): 66 images (144 KB), all 480 references drawn (430 glyphs, 50 pictures/colour
  SVGs, including the logo graphics), slowest layout 82 ms, no errors; without the flag 61 written,
  5 skipped (`images`).
- **Not done**: container field placeholders (no export seen has one), icon placement is
  approximate (FileMaker centres icon and label as a group; here the icon sits at the edge and the
  label is padded), icon colours for hover/pressed states, PDF graphics.

## 12. Review fixes (2026-11-20)

A review of P1-P5 on disRenewalUniverse (served and file://, desktop, dark, 390 px) and the
multi-file sample found these; all are fixed:

- **Cross-file fields** (multi-file build): a layout of FileB showing a field of FileA wasn't in any
  index, so the field page's *Show on layout* links and `locate_layout_object` with the field's
  docId missed it. `cli._cross_targets` maps each resolved cross-file reference to `(target folder,
  docId there)`; `write_layout_previews(cross_targets=…)` lists such fields in the index under
  `xfields: {fileKey: {fieldDocId: [[n, ids]]}}`. The field page reads every file's index (its own
  `fields`, the others' `xfields[<its file>]`); the tool looks in both.
- **`Table::Field` without `field:`** matched only the `TO::field` text, so objects showing the
  field through another table occurrence were dropped (1 of 4 for `Licence::cleLicense`). The tool
  now tries `field:` + value as a docId first (case-insensitive, one lowercase map per index) and
  falls back to the text only when no field has that docId. The result says `fieldDocId` when the
  docId was used.
- **`raw/layouts.json` pictures**: without `--layout-images`, `_drop_pictures` removes the picture
  stream of every `<StreamList>` in the kept elements except an SVG under `<IconData>` (the same
  icons the preview writes by default); `MAIN` / `GLPH` stay. disRenewalUniverse only has SVG
  button icons, so its raw file is unchanged (165 `SVG ` streams, 0 `FNAM`).
- **`sanitize_svg`**: `@import` is matched without case; `<style>` and attributes with
  `image-set(` or a backslash escape are dropped; animation elements (`set`, `animate*`,
  `discard`) are dropped; `<a>` is unwrapped (children kept) instead of removed.
- **Wireframe note** after `render` / `--no-include-json` blamed `--no-raw-xml`: the reason now
  comes from the caller (`styles_missing`).
- **Container names**: portals, popover panels, panels, tab / slide controls, button bars and
  groups no longer draw their object name as a centred label; *Wireframe* shows it as a small
  corner caption (`.t.cap`), *Styled* nothing.
- **Popover labels** in the layers panel, `shownIn` and the details fall back to the panel's name,
  and a merge-only label (`<<…>>`) gets the name appended (`popLabel`). The details' *In* row names
  the portal / popover / button bar.
- **Full-page route height**: the scroll box no longer has `min-height: 240px` and sits at the top
  of the row (`align-self: flex-start`, `stretch` on phones), so a short layout at Fit isn't in a
  tall empty box.
- **Favicon 404** under `fm-saxml serve`: `index.html` has `<link rel="icon" href="data:,">`.
- Found while re-checking: `fm-saxml serve` (a `ThreadingHTTPServer` with the default backlog of 5)
  refused some of the 16 parallel layout loads on Windows, so `locate_layout_object` with a field
  name failed intermittently ("Could not load …/layouts/23.js"). `request_queue_size = 64`.

Re-check on the real build (`final_out`, served, Chrome): `locate_layout_object` gives 4 objects for
`field:Licence::cleLicense`, `Licence::cleLicense`, `cleLicense` and `LICENCE::cleLicense`; no
container text visible in Styled; popovers listed as `devis.popover`, `Options.popover`, …; the
route box for Contrat - Liste equals the canvas height (229 px desktop, 103 px at 390 px, no
horizontal scroll); no console errors or 4xx.
