# Multi-File SaXML (FileMaker 26)

Plan for converting a folder of FileMaker Save a Copy as XML exports in one run, with working links between files.

Status: **proposal, not implemented.** Shipping it bumps the version to **0.4.0** (`src/fm_saxml/__init__.py`).

This plan replaces [`multi-file-conversion.md`](multi-file-conversion.md), which was written before we had a real multi-file export. Most of that design still holds: per-file subfolders, two-pass pipeline, target resolution, cross-file links and the combined index. This document changes the CLI shape and the file-pairing rule, and adds what the FM26 output needs. Where a section here says "as before", it means that document's section is still correct.

---

## 1. What FileMaker 26 Produces

FileMaker Pro 26 can Save a Copy as XML for several files at once, either **split** (one XML per file) or **combined** (all files in one XML).

### 1.1 Split output (we have a sample)

Sample: `D:\Dev\FMDev\disRenewalUniverse\task_53301\SaXML_PROD_2026-10-14` (25 files, 222 MB, the largest 41 MB).

```text
SaXML_PROD_2026-10-14/
├── Summary.xml              5 KB  manifest
├── BLITZ.xml               41 MB
├── Synapse.xml             17 MB
├── idiClients.xml          22 MB
└── ... 21 more
```

**Per-file XMLs** are ordinary v2 exports, identical in shape to what `build` already reads:

```xml
<FMSaveAsXML version="2.3.0.0" Source="26.0.3" File="BLITZ.fmp12"
             UUID="000FAD7E-..." locale="English" Has_DDR_INFO="True"
             binary_under_lo="False" split_catalogs="False">
```

**`Summary.xml`** has a different root and contains no schema:

```xml
<FMPReport type="Summary" version="2.3.0.0" membercount="24" CreationDate="2026-10-14" ...>
  <File name="BLITZ.fmp12" path="filemaker.srv.directimpactsolutions.com">
    <XML path="/Volumes/Macintosh HD/Users/.../SaXML_PROD_2026-10-14/BLITZ.xml"></XML>
  </File>
  ...
</FMPReport>
```

- `File/@name` is the FileMaker file; `File/@path` is the host it was exported from.
- `XML/@path` is an absolute path **on the exporting machine** (a macOS path in this sample). It is useless on another machine, so we match on the base name only.
- Today `build Summary.xml` falls through to the v1 parser and fails with "doesn't contain any FileMaker tables". In a folder run it must be recognized and used as a manifest, not rendered.

### 1.2 Combined output (no sample yet)

We don't know the root element or how files are delimited. Phase 4 is blocked until we get a sample (see section 10). Until then, a combined export given to `build` should either work as a single file, if it happens to look like one, or fail with a clear message. It should never produce partial output silently.

### 1.3 How the files reference each other (verified against the sample)

External data source in `idiRenewalUniverse.xml`:

```xml
<ExternalDataSource name="idiClients" type="FileMaker" id="3">
  <File><UniversalPathList>file:idiClients</UniversalPathList></File>
  <UUID ...>71722C46-59D7-446E-92B5-43FF3DB1C5A2</UUID>
</ExternalDataSource>
```

External table occurrence and cross-file Perform Script in the same file:

```xml
<TableOccurrence name="idiClients" type="External">
  <BaseTableSourceReference type="ExternalDataSourceReference">
    <DataSourceReference id="3" name="idiClients" UUID="71722C46-..."/>
    <BaseTableReference id="129" name="idiClients" UUID="AB4658F4-CAC5-43DB-9BC0-8F9A3B285705"/>
  ...
<DataSourceReference id="3" name="idiClients" UUID="71722C46-..."/>
<ScriptReference id="350" name="Trig_Changer_Langue" UUID="02CC57F4-1900-48B6-9E2D-307380529D2F"/>
```

Checked against `idiClients.xml`:

| Claim | Result |
|---|---|
| Data source UUID (`71722C46…`) equals `idiClients.xml`'s file UUID | **No.** It is the data source's own UUID, defined in the referencing file. |
| Base table UUID (`AB4658F4…`) exists in `idiClients.xml` | Yes |
| Script UUID (`02CC57F4…`) exists in `idiClients.xml`, with `id="350"` and the same name | Yes |

Two consequences:

1. **The old plan's pairing rule #1 (data source UUID equals file UUID) can never match.** Pairing has to use the `UniversalPathList` file name (section 5).
2. **Once a pair is made, uuid-first target resolution works.** Object UUIDs and ids survive across files, so the old plan's section 7 holds.

Other facts from the sample:

- All 24 files are `Source="26.0.3"`, `version="2.3.0.0"`, `split_catalogs="False"`.
- `Synapse.xml` has 33 external data sources; `idiRenewalUniverse.xml` has 3.
- `idiRenewalUniverse.xml` references `file:devIndividus`, which is not in the folder. This is the normal "file not in the batch" case. It must render as unresolved, not as an error.

---

## 2. Goals and Non-Goals

**Goals**

- `fm-saxml build <folder>` converts every export in the folder in one run. No new command to learn, and dragging a folder onto the executable works.
- References between files in the folder become working relative links.
- `Summary.xml` is used to check completeness and is never rendered as a solution file.
- Giving `build` a single file behaves exactly as it does today.
- Scrubbing, `--strict`, `--html` and `--fail-on-secrets` work across the whole batch.
- The 222 MB sample builds on a normal workstation, with peak memory reported (section 6).

**Non-goals (0.4.0)**

- Recursive folder scanning.
- `diff` between two folders (section 9 lists it as a follow-up).
- Reusing `external-references.json` from a previous build (old plan section 9; still a follow-up).
- Reading `.fmp12` files.

---

## 3. CLI: a Directory Means a Batch

This replaces the old plan's `build-all` command.

```text
fm-saxml build <file-or-folder> [--out DIR] [--force] [--yes] [--strict] [--html] [scrub options]
fm-saxml <file-or-folder>          # same thing via _DefaultToBuildGroup (drag and drop)
```

### 3.1 Input classification

When the input is a folder, list its top-level `*.xml` files (case-insensitive extension, not recursive, sorted by name). Sniff each file's **root element only**, using `lxml.etree.iterparse(..., events=("start",))` and stopping at the first element. That costs a few KB of reading even for a 41 MB file.

| Root element | Kind | Handling |
|---|---|---|
| `FMSaveAsXML` with a `File` attribute | `solution` | Converted. |
| `FMPReport` with `type="Summary"` | `manifest` | Read as a manifest (section 3.3). Not converted. |
| `FMSaveAsXML` v1 / other FileMaker roots | `solution` (v1) | Converted. Pairing is name-only with lower confidence (as before). |
| Anything else, or unparseable | `skipped` | Listed in the run summary with the reason. Not an error, except under `--strict`. |

Put the sniffer in a new `src/fm_saxml/parser/input_scan.py` so `inspect`, `validate` and `scrub` can use it too.

### 3.2 Choosing a mode

| Input | Solutions found | Behavior |
|---|---|---|
| A file | n/a | **Single-file mode**, unchanged. If the file is a `Summary.xml` manifest, fail with a hint: "This is the summary of a multi-file export; pass its folder instead." |
| A folder | 0 | Fail: "No FileMaker Save a Copy as XML files found in <folder>", plus `EXPORT_HINT`. |
| A folder | 1 | **Single-file mode** on that one file, with output as below. The manifest, if any, is still checked. |
| A folder | 2 or more | **Multi-file mode.** |

`_validate_input` currently rejects anything that isn't a file. It becomes "exists, and is a file or a folder".

### 3.3 Using the manifest

When a `Summary.xml` is present, compare its `File/@name` entries with the solutions found, matching on the `fmp12` name and also on the base name of `XML/@path`:

- A file listed in the manifest but not on disk prints a **warning**, for example when one export failed or someone deleted a file. It fails the run under `--strict`.
- A solution on disk but not in the manifest prints an **info** line. It is still converted.
- The manifest's `CreationDate`/`CreationTime` and host `path` go into the combined index header. The host name passes through the scrubber first, since hosts are a scrubbed category.

The manifest is optional. A folder that someone assembled by hand from separate exports works the same way.

### 3.4 Option semantics in multi-file mode

| Option | Multi-file behavior |
|---|---|
| `--out` | **Parent** output directory. Defaults to `<folder name>_docs` next to the input folder, matching `_default_out_dir`. |
| `--force` / `--yes` | Apply to the parent directory confirmation, once. `.fm-saxml` marker at the parent. |
| `--model-out` | Rejected in multi-file mode for 0.4.0 with a clear message. A follow-up could write one model JSON per file into a folder. |
| `--include-json` | Per file, inside each subfolder, as today. |
| `--strict` | Fails on: unresolved references in any file (today's rule), missing manifest members, skipped XMLs, ambiguous pairings, and paired-but-missing targets. |
| `--html` | One viewer at the parent covering every file (section 7). |
| `--open` | Opens the parent. |
| Scrub options | One scrubber for the whole batch (section 6). |

### 3.5 Failure isolation

A file that fails to parse doesn't abort the batch. It is reported in the run summary and the combined index, and its folder is not written. The exit code is non-zero if any file failed. Today's single-file `_fail` paths become per-file errors collected by the batch runner.

---

## 4. Output Layout

As before (old plan section 4): one subfolder per solution, named `safe_slug(solution_name)`, where `solution_name` comes from the root `File` attribute, **not** the XML file name. Collisions, compared case-insensitively, fail the run before anything is written.

```text
SaXML_PROD_2026-10-14_docs/
├── index.md                 combined index
├── index.html               (--html)
├── _viewer/                 (--html)
├── Reports/
│   ├── batch-summary.md     files, counts, pairings, unresolved sources, skipped XMLs
│   └── redactions.md        rollup across all files
├── BLITZ/
│   ├── index.md
│   ├── Tables/ Scripts/ Layouts/ ...
│   └── Reports/
├── idiClients/
└── ...
```

Each subfolder is identical to today's single-file output and still works when viewed on its own.

---

## 5. File Pairing (revised)

An `ExternalDataSource` of `type="FileMaker"` is paired with a batch file by, in order:

1. **Path match.** Any entry in `UniversalPathList` is split on newlines (FileMaker allows several paths per data source, tried in order). Strip the scheme (`file:`, `fmnet:`, `filemac:`, `filewin:`, `fmp:`), take the final path segment, and strip `.fmp12`/`.fmp7`. Compare case-insensitively with each batch file's `fmp_file_name` stem.
2. **Name match** (weak). `ExternalDataSource.name` equals a batch file's `solution_name`. Used only when no path matched, and flagged as low confidence.

The old rule "data source UUID equals file UUID" is **dropped**. Section 1.3 shows it can't match.

Outcomes are as before: one match pairs; no match is unresolved and plain text; several matches are ambiguous (a warning, or an error under `--strict`); a self-match is treated as unresolved. Paths containing variables (`$path`) or ODBC sources are never paired, and the reason says so.

Pairing runs on the normalized models' `ExternalDataSource.paths`, so first check that `extract_external_data_sources` keeps every `UniversalPathList` line and not just the first.

---

## 6. Pipeline, Scrubbing and Memory

**Pass 1, per file (sequential in 0.4.0):** `parse_savexml → scrub → normalize → resolve_references → generate_backlinks → generate_warnings`. This is today's `_run_pipeline` minus `validate_model`. Refactor it so the batch runner can call it without opening its own progress bar.

**Pass 2, across files:** folder names and collision check → pairing → external target resolution → cross-file backlinks → `validate_model` per file → render each file with the cross-file `LinkResolver` → JSON sidecars → combined index and `batch-summary.md` → optional HTML viewer → guard.

Pass 2 and the link rendering are as before (old plan sections 5, 7 and 8).

**Scrubbing across files**

- Use **one scrubber instance** for the whole batch, so the same secret gets the same placeholder in every file. Otherwise `idiClients` and `Synapse` would show different placeholders for the same shared API key.
- Scrub before cross-file resolution. Resolution matches on uuid, id and name, which the scrubber doesn't touch. Add a test that a scrubbed batch still pairs and resolves.
- Each subfolder keeps its own `Reports/redactions.md`. The parent gets a rollup. `_guard_output` runs once over the parent directory, and `--fail-on-secrets` aggregates every file's `ScrubSummary`.

**Memory and progress**

- Parse one file at a time and let its lxml tree go before parsing the next. Only `DocumentModel`s are kept for pass 2.
- Measure peak RSS on the 222 MB sample and record the number in this document. If holding 24 models is too much, pass 2 can work from each model's path index plus its external-target list, re-loading models one by one to render.
- Progress shows an outer bar (files) and an inner bar (current file's steps, then pages written). Keep the existing Windows NUL-spinner caveat in mind (see memory note on secret scrubbing).
- Parallelizing pass 1 across processes is a follow-up. It's free of cross-file state by design.

---

## 7. Rendering

As before (old plan section 8): relative cross-file links such as `../idiClients/Scripts/Trig_Changer_Langue.md`, titles suffixed with the file name, unresolved targets as plain text, and "Referenced by" entries from other files labeled with their source file.

**Combined `index.md`:** manifest date and host; a table of files with entity counts, the files each references, and the files that reference it; unpaired data sources such as `devIndividus`; skipped XMLs and failed files.

**HTML viewer (`--html`):** `render_html_viewer` already walks the tree with `rglob`, so every page is picked up. The sidebar currently builds its sections from the root `index.md` "Sections" list, which assumes one file. For a batch it needs one more level, **file → section → page**. Do this with a `files` array in the manifest that the template groups by when present, so single-file output is unchanged. Re-check the CDN pins and the Playwright smoke recipe from the HTML viewer memory note. Also check page count: the sample may produce tens of thousands of pages. If load time suffers, lazy-load each file's page list.

---

## 8. Other Commands

| Command | Folder behavior in 0.4.0 |
|---|---|
| `inspect` | One row per solution (file, FM version, counts, warnings), plus manifest check. Cheap way to preview a batch. |
| `validate` | Validates each file and the pairing. Exit code reflects all of them. |
| `scrub` | Writes `<folder>.scrubbed/` with each XML scrubbed by the shared scrubber. Copies `Summary.xml` with its host and paths scrubbed. Writes one report. |
| `parse` / `render` | File-only. A folder fails with a pointer to `build`. |
| `diff` | File or model only. Folder-to-folder diff (pair by file name, diff each pair, roll up) is the first follow-up after 0.4.0. |

---

## 9. Phases

1. **Input scan and batch build without links.** Add `input_scan.py` (sniffer and manifest reader), folder mode in `build`, per-file subfolders, collision check, failure isolation, shared scrubber, basic combined index and `batch-summary.md`. Verify on the real sample. Record time and peak memory here.
2. **Pairing and resolution.** Revised pairing (section 5), target resolution, scoped id rewrite, unresolved reasons, `--strict` rules.
3. **Cross-file links.** Extended `LinkResolver`, template updates, cross-file backlinks, full combined index, multi-file HTML viewer.
4. **Combined-XML input.** Blocked on a sample (section 10).
5. **Release 0.4.0.** `inspect`/`validate`/`scrub` folder support, README section on multi-file exports, version bump in `src/fm_saxml/__init__.py`.

Follow-ups after 0.4.0: folder `diff`, parallel pass 1, `--model-out` per file, reusing `external-references.json`.

---

## 10. Open Questions

1. **Combined-XML format.** We need a small combined export, even two tiny files, to see the root element and how files are separated. Until then, phase 4 is blocked.
2. **Old plan document.** Once this one is accepted, delete `multi-file-conversion.md` or reduce it to a pointer here, so two plans don't disagree.

Decided by this plan:

- A folder input means a batch; there is no `build-all` command.
- No recursion into subfolders.
- `Summary.xml` is optional and is used only for checks and metadata.
- Pairing is by `UniversalPathList` file name. Data source UUIDs are never compared with file UUIDs.

---

## 11. Testing

**Committed fixtures** (`tests/fixtures/multi/`, small and hand-built, no production data):

- `a.xml` and `b.xml`, where A has an external data source `file:b` and references a base table, a script and a field in B by uuid/id/name. Add a second path line to test multi-path `UniversalPathList`.
- `Summary.xml` listing `a`, `b` and a missing `c`.
- `notes.xml` (non-FileMaker XML) and `broken.xml` (malformed).

**Unit tests**

- Sniffer: each root kind; stops early (assert it doesn't read the whole file).
- Mode selection: file, folder with 0/1/2+ solutions, a Summary passed as a file.
- Manifest: missing member warns, and fails under `--strict`; extra file is info; macOS `XML/@path` matched by base name.
- Pairing: path match with each scheme; multi-line paths; name fallback flagged low confidence; ambiguous; self; variable path never paired; **data source UUID ≠ file UUID does not pair** (regression for the old rule).
- Resolution: by uuid, id and name; paired file with a missing target.
- Scrubbing: same secret in two files gets the same placeholder; a scrubbed batch still resolves.
- Failure isolation: `broken.xml` doesn't stop `a`/`b`, and the exit code is non-zero.
- Single-file `build` output is byte-identical to 0.3.0 for an existing fixture (regression).
- `tests/test_cli_paths.py`: folder input, default `<folder>_docs` output, parent-directory confirmation.

**Real-sample check (manual, not in CI):** a test marked `slow`, skipped unless `FM_SAXML_MULTI_SAMPLE` points at a folder. Run it against `SaXML_PROD_2026-10-14`. It asserts that 24 subfolders exist, the manifest is fully matched, `idiRenewalUniverse → idiClients` is resolved, `devIndividus` is unresolved, and the guard passes. The sample is production data and must never be committed or copied into `tests/`.
