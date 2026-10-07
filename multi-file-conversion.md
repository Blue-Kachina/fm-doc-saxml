# Multi-File Conversion

Plan for converting several FileMaker SaveAsXML exports in a single command, resolving external file references between them, and keeping the generated Markdown cross-linked.

Status: **proposal, not implemented.**

---

## 1. Goal

FileMaker solutions are frequently split across several files. Files reference each other through external data sources: table occurrences, relationships, scripts, layouts, and fields in calculations can all point into another file.

Today `fm-saxml build` converts one file. External targets are parsed and modeled, but they render as plain text with no link, because the link resolver only knows about the one model it was built from.

**Goals**

- Convert N exports with one command.
- When the target of an external reference is among the files being converted, resolve it and render a working relative link.
- Keep each file's output in a strictly named subfolder so links between outputs are predictable and stable.

**Non-goals**

- Changing single-file `build` behavior or output layout.
- Resolving references into files that are not part of the batch (these stay as plain text and are reported as unresolved).
- Reading `.fmp12` files directly. Input remains SaveAsXML.

---

## 2. Current State (what we build on)

| Area | Where | Notes |
|---|---|---|
| CLI | `src/fm_saxml/cli.py` | `build` takes one `input_xml`. `_run_pipeline` runs `parse_savexml → normalize → resolve_references → generate_backlinks → generate_warnings → validate_model` for one file. |
| External data sources | `parser/extractors/external_data_sources.py`, `model/document_model.py::ExternalDataSource` | `name, fmpId, uuid, type, paths` (paths like `file:idiClients`). |
| External targets | `model/references.py::ExternalTarget` | Carries `targetDocId`, provisional `scopedDocId` (`ds:<uuid>/<docId>`), target type, name, fmpId, uuid, table occurrence and base table. Match order documented as uuid, then fmpId, then name. |
| Scoped ids | `normalize/ids.py` | `file_scope` uses the file UUID, else `file:<fmpname>`. Comments already anticipate rewriting `ds:...` once files are paired. |
| JSON sidecar | `render/json/writer.py` → `external-references.json` | Intended to let a later multi-file run avoid re-parsing each XML. |
| Links | `render/markdown/link_resolver.py::LinkResolver` | Built per model. External targets get a title only, no href. `_encode_href` already percent-encodes spaces. |
| Paths | `normalize/paths.py`, `normalize/names.py::safe_slug` | All output paths are relative to a single root. |
| File identity | `parser/saxml_reader.py::_parse_v2` | `fmp_file_name` from the root `File` attribute, `solution_name` is that minus `.fmp12`/`.fmp7`, `file_uuid` from root `UUID`. v1 exports have no UUID. |

---

## 3. CLI

Add a way to pass several inputs. Preferred shape is a new command so `build` stays simple:

```text
fm-saxml build-all <input>... [--out ./saxml2doc] [--force] [--yes] [--strict]
```

`<input>` may be explicit files, a directory (all `*.xml` inside), or a glob. This is a separate command; `build` is unchanged and keeps taking a single file.

Behavior of shared options:

- `--out` is the **parent** directory. Each file gets its own subfolder (section 4).
- `--force` / `--yes` apply to the parent directory confirmation only. Only the subfolders this run writes are wiped, never unrelated siblings.
- `--strict` fails the run on unresolved external sources or ambiguous pairings, in addition to existing strict checks.

---

## 4. Output Layout

Each file's documentation lives in a strictly named subfolder of the output directory:

```text
saxml2doc/
├── index.md                      (combined index, section 8)
├── idiClients/
│   ├── index.md
│   ├── Tables/
│   ├── Scripts/
│   ├── Layouts/
│   ├── Reports/
│   └── external-references.json
└── Nexus Main/
    ├── index.md
    ├── Tables/
    └── ...
```

**Naming rule:** `<FileFolder> = safe_slug(solution_name)`, using the FileMaker file name from the export (root `File` attribute minus `.fmp12`), **not** the XML file's name. That makes the folder name stable no matter what the export was saved as, so cross-links do not break when someone renames the XML.

- `safe_slug` preserves case and spaces; spaces are percent-encoded in hrefs by `_encode_href`.
- If two files produce the same slug (compared case-insensitively), the run fails before writing anything, with an error naming both source paths. There is no suffixing, since folder names are part of the link contract.
- Falls back to the XML filename stem when the export has no file name (some v1 exports).

Inside a subfolder, the layout is identical to today's single-file output. Each folder remains self-contained and still works when viewed alone; cross-file links are an addition.

---

## 5. Pipeline

Two passes.

**Pass 1: per file (independent)**

1. `parse_savexml`
2. `normalize`
3. `resolve_references` (within the file)
4. `generate_backlinks`
5. `generate_warnings`

Output: a `DocumentModel` per file plus its path index (doc id → output path), so no rendering is needed yet.

**Pass 2: across files**

1. Compute folder names (section 4) and check for collisions.
2. Pair files (section 6).
3. Resolve external targets (section 7).
4. Run `validate_model` per file.
5. Render each file with a cross-file-aware `LinkResolver` (section 8).
6. Write JSON sidecars and the optional combined index.

Pass 1 can be parallelized later; it is deliberately free of cross-file state.

---

## 6. File Pairing

Pairing decides which batch file an `ExternalDataSource` points at.

Match an external data source to a batch file by, in order:

1. `ExternalDataSource.uuid` equals the other file's `file_uuid`.
2. A `paths` entry such as `file:idiClients` equals the other file's `fmp_file_name` stem (case-insensitive, extension stripped). Paths with directories or `fmnet:`/`fmp:` hosts are compared on the final file name only.
3. `ExternalDataSource.name` equals the other file's `solution_name`, as a weak last resort.

Outcomes:

| Result | Behavior |
|---|---|
| Exactly one match | Paired. |
| No match | Unresolved. Rendered as plain text like today. Reported in `Reports/unresolved-references.md` and the summary. |
| More than one match | Ambiguous. Not paired. Warning (error under `--strict`). |
| Matches the file itself | Treated as unresolved and warned (self-reference by file path). |

---

## 7. Resolving External Targets

For each `ExternalTarget` whose data source is paired with a batch file:

1. Look up the target in that file's model, using the match order from `model/references.py`: **uuid, then fmpId, then name** (for fields: base table plus name).
2. On a hit, rewrite the provisional `scopedDocId` (`ds:<uuid>/<docId>`) to the real scope from `normalize/ids.py`, and record the resolved file and target doc id on the `ReferenceRecord`.
3. On a miss (file paired, object not found), mark unresolved with a distinct reason. This commonly means the target was renamed or deleted.

`ReferenceRecord.confidence` stays `"external"` for cross-file references. We add resolution fields rather than inventing a new confidence level:

```json
{
  "confidence": "external",
  "externalTarget": {
    "targetType": "script",
    "name": "Log Error",
    "dataSource": "idiClients",
    "resolved": true,
    "resolvedFile": "idiClients",
    "resolvedDocId": "script:42"
  }
}
```

Backlinks: a resolved external reference also generates a backlink on the target in the other file, so "Referenced by" sections show callers from other files. These are labeled with the source file.

---

## 8. Link Rendering

`LinkResolver` is currently constructed from a single model. Extend it with an optional **external registry**: a mapping of file folder name to that file's path index.

- Same-file links are unchanged.
- A resolved external link is a relative path from the current page to the other folder:

  ```text
  ../idiClients/Scripts/Log%20Error.md
  ```

  built by the existing `_relative` logic, rooted at the shared parent directory, then passed through `_encode_href` (spaces become `%20`).
- Titles for external links show the file, for example `Log Error (idiClients)`.
- Unresolved external targets keep the current plain-text rendering.

Pages to update:

- `table_occurrence.md.j2` ("External — table X in file Y") and `layout.md.j2` get real links when resolved.
- `Reports/summary.md` shows resolved versus unresolved external reference counts.
- `Reports/unresolved-references.md` lists unresolved external sources with the reason.

**Combined index** at `<out>/index.md` (part of the first version): lists each file with a link to its `index.md`, entity counts, and which files it references or is referenced by. It also lists unpaired external data sources, so missing files are visible at a glance. Useful for navigation and for AI consumption of the whole corpus.

---

## 9. Reusing `external-references.json`

Each file already writes `external-references.json` with its data sources, external table occurrences and references. A later phase can let `build-all` accept previously built output directories as inputs to the pairing and resolution pass, so a large solution does not need every XML re-parsed. This is a refinement, not required for the first working version.

---

## 10. Edge Cases

- **Circular references** (A references B, B references A): fine, since pass 1 is independent and pass 2 only reads other files' indexes.
- **Referenced file not in the batch:** unresolved, not an error. This is the normal case when converting a subset.
- **Same file name in different directories:** collides on slug, so the run fails with both paths named.
- **v1 exports:** no UUID and no `fmp_file_name`. Pairing is name-based only, with lower confidence, and is flagged as such.
- **Renamed files:** name-based pairing fails; UUID pairing still succeeds when UUIDs are present.
- **Windows and case sensitivity:** folder names are compared case-insensitively for collision checks, since the output may live on a case-insensitive file system.
- **Special characters:** handled by `safe_slug` for folders and `_encode_href` for links. Parentheses and brackets are covered by existing escaping.
- **`--strict`:** unresolved sources, ambiguous pairings and missing targets in paired files fail the run.

---

## 11. Open Questions

Decided:

- New `build-all` command; `build` is unchanged.
- Slug collisions fail the run.
- The combined top-level `index.md` is included in the first version.

- Every file in a batch gets its own subfolder, including files with no cross-references, so the layout is uniform.

No open questions remain.

---

## 12. Testing

- Two small linked fixtures in `tests/fixtures/` (for example `file_a.xml` and `file_b.xml`) where A references a script, a field and a table occurrence in B.
- Pairing: UUID match, file-name match, no match, ambiguous match, self-reference.
- Resolution: found by uuid, by fmpId, by name; paired file with missing target.
- Links: relative href correctness, including a file name with spaces and parentheses.
- Fallback: unresolved source renders plain text exactly as today.
- Single-file `build` output unchanged (regression).
- Extend `tests/test_cli_paths.py` for the new command and the parent-directory confirmation behavior.

---

## 13. Phases

1. **CLI and layout:** `build-all`, input expansion, per-file subfolders, collision detection, basic combined index (file list and counts). Each file converts independently with no cross-links yet.
2. **Pairing and resolution:** file pairing, target resolution, scoped id rewrite, resolution fields on references, unresolved report.
3. **Cross-file links:** extended `LinkResolver`, template updates, cross-file backlinks, summary counts, combined index gains the referenced-by relationships and unpaired sources.
4. **Refinement:** reuse `external-references.json`, parallel pass 1, `--strict` polish.
