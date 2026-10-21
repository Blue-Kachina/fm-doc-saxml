# EverythingBagel: Mac run of agentic-fm Explode XML

Run date: 2026-10-21, 16:29 local time (America/Toronto).

## Versions

| Item | Value |
|---|---|
| FileMaker Pro | 26.0.3 (CFBundleVersion 26.0.3), `/Applications/FileMaker Pro.app`. The SaXML header says `Source="26.0.3"`, `FMSaveAsXML version="2.3.0.0"`. |
| fm-xml-export-exploder | 0.6.1, `~/bin/fm-xml-export-exploder`, sha256 `03efac61602973b63a19452dec3bc0f110895f908c83aa6e5b8b1447d6beef03` |
| agentic-fm | version.txt 1.0.0, commit `b2669b604f4947b6a5e3a594c85176f89e908b1c` (2026-10-14, "Merged from internal"), origin `petrowsky/agentic-fm`, working tree clean |
| companion_server.py | 1.0.0 (same repo), default bind 127.0.0.1:8765 |
| macOS | 26.5.2 (25F84), arm64 |
| Python | 3.14.7 |
| xmllint | libxml 20913 |

## Flags and config

- No `agent/config/*.json` files. companion.json, automation.json and removals.json are all absent, so the run used all defaults.
- fmparse.sh ran with defaults: `--output_tree domain`, no `--all-lines`, no `--lossless`. `--obfuscate-passwords` was not added because fmparse.sh only adds it when the exploder version is above 0.6.1.
- The exploder path came from the Explode XML script's payload (`exploder_bin_path` = `~/bin/fm-xml-export-exploder`).
- trace.py and analyze.py ran with default options (no `--deep`, no `--ensure-prerequisites`, no `--verbose`). No layout summaries were generated, because that isn't part of the default path (see the warnings in `tool_output/`).

## How it was run (the real path)

1. Made a duplicate of EverythingBagel.fmp12 in a separate folder, keeping the same file name so `Get(FileName)` stays `EverythingBagel`.
2. Opened only that file in FileMaker Pro 26.0.3.
3. Pasted **only two** agentic-fm scripts into it: "Get agentic-fm path" and "Explode XML". They came from `filemaker/agentic-fm.xml` at the commit above (exact snippet in `extras/pasted_scripts_snippet.xml`), and were pasted at the top level with no folder. Explode XML has to live in the file it exports.
4. Started `python3 agent/scripts/companion_server.py` and ran Explode XML interactively from the Script Workspace. Get agentic-fm path pointed at the agentic-fm repo root.
5. The script did Save a Copy as XML to `~/Desktop/EverythingBagel.xml`, then POSTed to `/explode`. fmparse.sh archived the XML, ran the exploder, then ran fmcontext.sh. Full log: `run_log/companion_server.log`. The script ended on the "Finished" dialog.

**Difference from your file:** the SaXML contains the two pasted scripts (IDs 3 and 4 here). Apart from that it should match yours. The Desktop copy and the archived copy in `xml_exports/` are byte-identical (sha256 `9306b9d4ffefe8692306ed181988abb4639a848262b790f29fd3a098264e13ad`).

## Contents

- `xml_parsed/`: the whole `agent/xml_parsed/` tree (EverythingBagel is the only solution in it, 78 files).
- `saxml/EverythingBagel.xml`: the Save a Copy as XML file the script produced.
- `tool_output/`: `trace_build.txt`, `trace_dead_{fields,scripts,custom_functions,layouts,value_lists}.txt`, `analyze_stdout.txt`, the three `solution-profile` files analyze.py wrote to `agent/sandbox/`, the resulting `xref.index`, and `exit_codes.txt` (every command exited 0).
- `extras/agent_context_EverythingBagel/`: the index files from fmcontext.sh plus xref.index.
- `extras/pasted_scripts_snippet.xml`: what was pasted into the file.
- `clipboard/`: menu and menu set copied from Manage > Custom Menus, saved with `clipboard.py read` (UTF-16 as written).
- `run_log/filemaker_paste_Import.log`: FileMaker's Import.log from pasting the two scripts (23 and 62 steps, error 0).
- `display_styles/`: the follow-up display-style test (see "Field display styles"). It is not part of the main run.
- `run_log/companion_server.log`: companion server and fmparse.sh output for the run. The /health line includes a plug-in probe; the plug-in was not running and wasn't used.

## Things noticed in this run

1. **custom_functions.index is empty.** The exploder wrote `custom_functions/EverythingBagel/Test - ID 1.xml`, and trace.py counts 1 custom function. But fmcontext.sh reads CFs from `custom_function_stubs/`, which exploder 0.6.1 did not create, so the index has 0 rows.
2. **value_lists.index has empty names and IDs.** fmcontext.sh reads `/ValueList/ValueListReference/@name` and `@id`, but the exploded files have `/ValueList/@name` and `@id`. Both rows come out as `||Custom|A,B,C` and `||FromField|`. As a result, `trace.py dead -t value_lists` reports "1 high … out of 1 total" with a blank name, although the file has 2 value lists.
3. No layout summaries, so trace.py warns that dead results for fields, scripts and value lists are unreliable. For example, every field and both layouts come up "unused".

## Optional questions

### Menu UUIDs: the clipboard and SaXML match

| Object | Clipboard | SaXML | Exploded file |
|---|---|---|---|
| Custom Custom Menu (id 25) | `4B4D221B-C372-2D48-A740-DBC9A2913258` | same | same |
| its menu item | `F4499B88-6E8F-E942-A6B6-305F3316AC9A` | same | dropped (default, not lossless) |
| CustomMenuCatalog | `F0D02DB4-BAD4-304F-A1F5-BE97F56A225E` | same | n/a |
| Custom Menu Set (id 2) | `4629F04A-F682-3448-A37F-2D33ED047415` | same | same |
| CustomMenuSetCatalog | `BFA80551-FDB7-3D44-9B03-648D46B61ACB` | same | n/a |

UUID `modifications`, `userName`, `accountName` and `timestamp` attributes also match. Differences that are not UUIDs:

- `CustomMenuItem hash` differs: the clipboard has `12FFBC77…` and the SaXML has `B685C265…`.
- The action's `<Step>` differs. The clipboard has the snippet form (`<StepText>`, `<DisableStepCollapsed>`, no hash). The SaXML has the SaXML form (`hash`, `index`, `<UUID>`, `<OwnerID>`, `<Options>`). In the SaXML the step's `<UUID>` equals the menu item's UUID.
- The clipboard wraps the object in its catalog (`CustomMenuCatalog` or `CustomMenuSetCatalog` with SortOrder, CustomOrderList and catalog UUID) plus a `PasteIndexList`. The clipboard class was `ut16`.

### Field display styles

Checked with a follow-up test after the main run. The test was on the working copy, so it is not part of `xml_parsed/` or `saxml/`. Four textField objects were added to the EverythingBagel layout (checkbox set, radio button set, drop-down calendar, concealed edit box). The file was then exported again with **Tools > Save a Copy as XML** (`display_styles/EverythingBagel_styles.saxml.xml`, `Has_DDR_INFO="True"`). The layout objects were also copied to the clipboard and saved with `clipboard.py read` (`display_styles/layout_objects.clipboard.xml`, class XML2).

| SaXML `<Display Style>` | XML2 clipboard `FieldObj displayType` | Control (SaXML `LayoutObject type`) |
|---|---|---|
| 0 | 0 | Edit Box (also used for Container objects and for the field inside a Portal object) |
| 1 | 1 | Drop-down List |
| 2 | 2 | Pop-up Menu |
| 3 | 3 | Checkbox Set |
| 4 | 4 | Radio Button Set |
| 5 | n/a | not seen |
| 6 | 6 | Drop-down Calendar |
| 7 | 7 | Concealed Edit Box |

- The SaXML numbers and the clipboard numbers are the same for every object (matched by SaXML `id` = XML2 `key`: 26, 28, 30, 33, 35, 37, 39).
- The SaXML also names the control in `LayoutObject type`, so no inference was needed.
- A concealed edit box is its own style (7), not style 0 plus a flag. In XML2 its `FieldObj flags` is 2138146; a plain edit box's is 32.

### Layout bounds

Bounds are in points:

- Claris Help says FieldBounds and GetLayoutObjectAttribute report coordinates in points.
- In the follow-up test the SaXML `<Bounds>` and the XML2 clipboard `<Bounds>` are identical for all seven objects (for example, the checkbox set is `top=592 left=407 bottom=624 right=660` in both; XML2 writes them as `592.0000000`).
- So both formats use the same origin and the same unit, and the unit is the one the Inspector shows by default (pt).
