# Summary.xml: FileMaker's manifest, and what happens without one

When FileMaker Pro 26 saves several files as XML at once, it adds a `Summary.xml` to the folder. fm-saxml finds it by its root element (`FMPReport type="Summary"`), not by its name.

```xml
<FMPReport CreationDate="2026-10-14" CreationTime="10:19:47 AM" type="Summary" version="2.3.0.0" membercount="2">
  <File name="FileA.fmp12" path="C:\Users\Admin\Downloads\TwoFileTest\">
    <XML path="C:\Users\Admin\Downloads\TwoFileTest\SaXML\FileA.xml"></XML>
  </File>
  ...
</FMPReport>
```

## What it's used for

- **Completeness checks.** A file the manifest lists with no export in the folder prints a warning and fails `--strict`, and it appears under "Not Converted" in index.md. An export the manifest doesn't list prints an info line and appears under "Not Listed in Summary.xml" in `Reports/batch-summary.md`.
- **Two rows of index.md:** "XML Created At" (`CreationDate` and `CreationTime`) and "Exported From" (each `File/@path`: the server for a hosted file, the folder for a local one; scrubbed as a host).
- **The "Summary.xml" row** of index.md and batch-summary.md, saying where the manifest came from.

**Pairing never uses it.** Data sources are paired with files from the exports alone, so a folder pairs the same way with or without a manifest.

## A folder without one

A scripted export, or a folder put together by hand, often has no `Summary.xml`. When a folder holds two or more exports and no manifest, fm-saxml builds one **in memory** from the exports. A folder with one export doesn't need one and builds as a single file.

| Manifest field | Synthesized from |
|---|---|
| `File/@name` | the export's root `File` attribute. A v1 export has none, so its XML's name plus `.fmp12`. |
| `XML/@path` | the local path. A separate-catalogs folder ends with a path separator, like FileMaker's. |
| `version`, `membercount` | not kept. Each export's root `version` is in its own docs (`source.saxmlVersion`). |
| `CreationDate`, `CreationTime` | **nothing.** An export holds no export time. A file's modification time changes when it's copied or unzipped, so it's never shown as "XML Created At". |
| `File/@path` (host or folder) | **nothing.** It isn't in the export. |

Rules:

- It's **never written to disk**. Input folders may be read-only, and a second manifest in the folder would be skipped and fail `--strict`.
- It always agrees with the exports, so it never reports missing or unlisted files. `--strict` passes on that count.
- index.md and batch-summary.md say `Summary.xml: not present (built from N exports)`, with no "XML Created At" or "Exported From" row.
- `docs.json` has `"synthesizedManifest": true` (see [contract.md](contract.md)).

## A manifest written by another tool

A tool that exports by script can write a FileMaker-shaped `Summary.xml` itself, so the completeness checks and the time and host rows work again. It should add a `generator` attribute to the root, e.g. `generator="agentic-fm"`. fm-saxml reads the manifest as usual, and the "Summary.xml" row says `present (written by agentic-fm)`. Whether agentic-fm's export script will write one is open (roadmap Q4).

## Unknowns

- Whether FileMaker counts files that failed to export in `membercount`.
- Whether `CreationTime`'s format depends on the locale. fm-saxml shows it as written.
