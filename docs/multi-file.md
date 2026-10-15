# Multi-file solutions (FileMaker 26 folder exports)

FileMaker Pro 26 can Save a Copy as XML for several files at once. Point `fm-saxml` (or `fm-saxml build`) at the folder it wrote:

```bash
fm-saxml ./SaXML_PROD_2026-10-14
```

Each file gets its own subfolder (named after the FileMaker file, e.g. `Clients/`), laid out exactly like a single-file build. References from one file into another (external table occurrences, relationship predicates, layout fields, Perform Script from another file, Go to Related Record) become links to the other file's pages, and the target's "Used By" / "Referenced By" lists show callers from the other files.

At the top of the output folder:

- A combined `index.md` lists every file with what it references and what references it.
- `Reports/batch-summary.md` shows how each external data source was paired with a file.
- `Reports/redactions.md` is the master list of what was scrubbed: each placeholder and the files it appears in, plus everything flagged for review. Placeholders are shared across the files, so the same secret has the same placeholder everywhere.

## Details

- Both export styles work: one XML per file, or **separate catalogs** (one folder per file with one XML per catalog). A single file's catalog folder can also be built on its own.
- `Summary.xml` is used to warn about files it lists that are missing from the folder.
- Data sources are paired with files by their file path (`file:Clients` → `Clients.fmp12`). References into files that aren't in the folder stay plain text and are listed in the index.
- A file that can't be converted is reported and skipped; the others are still built, and the exit code is 1.
- `--strict` also fails on files missing from `Summary.xml`, skipped XMLs, ambiguous pairings and cross-file targets that don't exist. `--model-out` isn't supported for folders.
- `inspect` and `validate` accept a folder too.
