# Comparing two exports (`diff`)

```bash
# Compare two SaveAsXML exports (or model.json files — either input can be either format)
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml

# Write a Markdown diff report
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml --out ./diff-report.md

# Exit non-zero if anything differs (useful in CI to catch unreviewed schema drift)
fm-saxml diff ./old/MySolution.xml ./new/MySolution.xml --strict
```

`diff` compares every entity type (tables, fields, layouts, scripts, relationships, etc.) by its stable `docId`, which is derived from names rather than FileMaker's internal numeric/UUID identifiers — so the same field is recognized as "the same" across two independent exports as long as it wasn't renamed. It reports:

- **Added** / **Removed** entities per type.
- **Changed** entities — any scalar field that differs (old → new value, truncated for long text), and any list-of-references field whose *membership* changed (shown as a `+N/-M` delta, not just a raw count, so a same-size swap doesn't look unchanged).
- **Script step changes**, separately — script step `docId`s are position-based (`script + index`), so a raw added/removed diff on them would show a wall of unrelated churn whenever a single step is inserted or removed mid-script. Instead, each script's step list is compared by content (name + enabled + raw text) using a sequence alignment, and reported as a single `+added/-removed` count per script.

`--strict` exits with status 1 if the diff found any difference at all (added, removed, changed, or script step changes).

Scrubbing applies to `diff` too. Placeholders are numbered per run, so two separately saved `model.json` files can't be compared value by value; set `FM_SAXML_SCRUB_SALT` for placeholders that stay the same across runs (see [Scrubbing](./scrubbing.md#stable-placeholders-across-runs)).

**Limitation:** the script-step comparison tells you how many steps were added/removed per script, not exactly which ones or where — open the two `Scripts/<name>.md` pages side by side for that level of detail.
