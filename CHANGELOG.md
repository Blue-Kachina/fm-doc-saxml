# Changelog

## Unreleased

### Added

- `build --progress rich|plain|json`. `plain` prints one line per stage and per file (`[3/12] Analyzing Invoices (4.2s)`); `json` prints one JSON object per line (`event`, `stage`, `file`, `index`, `total`, `elapsed`, and `seconds` when a file or stage ends), for tools that show a build's progress. Without the flag, a terminal still gets the Rich bars, and a pipe or file now gets `plain` lines instead of the bars' final state. The fields are in the README, under "Progress in scripts and pipes".

### Changed

- `fm-saxml serve`, and `--serve` on `build`/`render`, now use port **8766** by default instead of 8765. The agentic-fm companion server also defaults to 8765, so the two used to clash. To keep the old port, pass `--port 8765`. As before, if the port is taken, a free one is used.
- The scrubbing guard now checks a build's docs *before* they replace the previous ones. When it fails, the previous docs are kept and the rejected ones are left in `<folder>.tmp-<pid>`. Its message groups the leaks by value, and says when a value is also an object's name.
- Scrub engine version 6: a `model.json` saved by an earlier version is scrubbed again when rendered.

### Fixed

- A `<Function Missing>` argument that names an object in the solution, such as `<Function Missing> ( "SlidingDrawer" )` inside the custom function SlidingDrawer, is no longer redacted as a secret. The redaction could never be complete, since names are never rewritten, so the guard stopped the build (exit 2). Such values are now listed under "Needs review". This holds across files in a multi-file build, and for the strict level's high-entropy rule and comment prose too. Rules with real evidence (a password parameter, a Crypt key, a `$password = "…"` assignment) still redact, and still stop the build if the value is also a name.
- `<Function Missing>` arguments that are MIME types, plain HTTP headers (`Content-Type: …`), plugin commands (`SMTP-SetBody`), on/off or numeric options (`ssl=true`) and mode keywords (`html`) are no longer redacted.
- Windows: a rebuild could fail with `[WinError 5] Access is denied` while moving the new docs into place, when antivirus or the search indexer was still reading the freshly written files. It left the docs folder missing, with `.old-<pid>` and `.tmp-<pid>` folders behind. Both renames of the swap now retry for about 30 seconds. If the second rename still fails, the previous docs are moved back and the message names the folder that holds the new ones.
- Windows: a rebuild failed with `Could not replace <docs>: Access is denied` when a program was using the docs folder as its current folder (a terminal or File Explorer window in it), since Windows won't rename that folder. The folder now stays and its contents are replaced instead. If something inside is held open too, everything is put back as it was, and the message names the file or folder that is in use and the usual causes.
