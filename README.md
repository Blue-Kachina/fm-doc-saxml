# fm-saxml-converter

[![PyPI version](https://img.shields.io/pypi/v/fm-saxml-converter)](https://pypi.org/project/fm-saxml-converter/)
[![Python versions](https://img.shields.io/pypi/pyversions/fm-saxml-converter)](https://pypi.org/project/fm-saxml-converter/)
[![License: MIT](https://img.shields.io/pypi/l/fm-saxml-converter)](LICENSE)
[![CI](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/ci.yml/badge.svg)](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/ci.yml)
[![Release](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/release.yml/badge.svg)](https://github.com/Blue-Kachina/fm-doc-saxml/actions/workflows/release.yml)

Generate structured, navigable documentation from FileMaker Pro **Save a Copy as XML** exports.

`fm-saxml-converter` turns a FileMaker `SaveAsXML` file into a folder of cross-linked Markdown pages — one file per table, field, layout, layout object, script, relationship, custom function, and value list — backed by a normalized JSON model of the solution. Optionally it adds a browser viewer, and tools that let AI agents query the solution.

The CLI is exposed as `fm-saxml`.

## Why this exists

A FileMaker `SaveAsXML` export contains everything about a solution, but the raw XML is not readable, not navigable, and not stable across FileMaker versions. This project produces a documentation layer that is:

- **Human-readable** — Markdown pages with consistent headings, summary tables, and per-entity backlinks.
- **AI-readable** — predictable structure, machine-parseable front matter, and JSON sidecars for indexing.
- **Linkable** — every reference between entities (script step → field, layout → table occurrence, calculation → custom function) becomes a link, with "Used By" lists on the other end.
- **Safe to share** — credentials and other secrets are replaced with placeholders before anything is written.

## Requirements

- A FileMaker Pro `Save a Copy as XML` export
- Python 3.11+ (not needed if you use the standalone executable)

## Quick start

1. In FileMaker Pro: **Tools → Save a Copy as XML…**
2. Run the converter on that file:

   ```bash
   fm-saxml MySolution.xml
   ```

   (On Windows you can also drag the XML file onto `fm-saxml.exe`.)
3. Open the new `MySolution_docs` folder that appears next to your XML file.

Add `--open` to have the folder opened for you. Run `fm-saxml doctor` if something doesn't work and include its output in any bug report.

## Installation

**Easiest — no Python needed:** download the `fm-saxml` executable for Windows, macOS or Linux from the project's Releases page.

<details>
<summary>macOS and Linux: making the download runnable</summary>

A file downloaded through a browser isn't marked as executable, and on macOS Gatekeeper blocks it because the build isn't signed by an Apple developer ID. In Terminal, in the folder you downloaded it to:

```bash
chmod +x fm-saxml-macos                              # make it executable (Linux: fm-saxml-linux)
xattr -d com.apple.quarantine fm-saxml-macos         # macOS only: clear the download quarantine flag
./fm-saxml-macos --version
```

Or download it with `curl`, which skips the quarantine flag:

```bash
curl -L -o fm-saxml https://github.com/Blue-Kachina/fm-doc-saxml/releases/latest/download/fm-saxml-macos
chmod +x fm-saxml
```

The macOS executable is for Apple Silicon Macs. On an Intel Mac, install with Python instead (below).

</details>

**With Python 3.11+:**

```bash
pipx install fm-saxml-converter      # or run without installing: uvx --from fm-saxml-converter fm-saxml MySolution.xml
```

To install from source, see the [technical README](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/README_technical.md#installing-from-source).

### Updating

Check your version with `fm-saxml --version`, then upgrade the same way you installed:

| Installed with | Update command |
|---|---|
| `pipx` | `pipx upgrade fm-saxml-converter` |
| `uv tool install` | `uv tool upgrade fm-saxml-converter` |
| `pip` | `pip install -U fm-saxml-converter` |
| `uvx` | `uvx --from fm-saxml-converter@latest fm-saxml ...` |
| Executable | Download the new file from the Releases page |

When a newer version exists, `fm-saxml` prints a one-line notice after a run (checked at most once a day, never blocks, silent in CI and when output is piped). Disable it with `FM_SAXML_NO_UPDATE_CHECK=1`.

## Usage

Most of the time, this is all you need:

```bash
fm-saxml <export file or folder>
```

The docs are written to `<input name>_docs` next to the input. Use `--out <folder>` (or `-o`) to put them somewhere else. If the output folder already has files in it, you'll be asked before they're overwritten; `--force` (or `-f`) skips the question.

### Multi-file solutions

FileMaker Pro 26 can Save a Copy as XML for several files at once. Point `fm-saxml` at the folder it wrote:

```bash
fm-saxml ./SaXML_PROD_2026-10-14
```

Each file gets its own subfolder, and references from one file into another become links between them. See [Multi-file solutions](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/multi-file.md) for the details.

### Commands

`fm-saxml <file>` is shorthand for `fm-saxml build <file>`.

| Command | What it does |
|---|---|
| `build <file or folder>` | Parse the export and write the documentation (the default) |
| `parse <file>` | Parse the export into the normalized `model.json` only |
| `render markdown --model <model.json>` | Write documentation from a `model.json` made earlier |
| `inspect <file or folder>` | Print entity counts and warnings without writing anything |
| `validate <file or folder>` | Exit non-zero if the model has critical issues |
| `diff <old> <new>` | Compare two exports and report what changed — see [Comparing exports](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/diff.md) |
| `scrub <file>` | Write a copy of the XML with secrets redacted — see [Scrubbing](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/scrubbing.md#scrubbing-the-xml-itself-scrub) |
| `serve <docs folder>` | Serve a `--webmcp` build at `http://127.0.0.1:8765` so browser agents get its tools |
| `doctor` | Print environment details for bug reports |

### Common options

| Option | What it does |
|---|---|
| `--out <path>` / `-o` | Write the output somewhere other than `<input name>_docs` |
| `--force` / `-f` (or `--yes` / `-y`) | Overwrite an existing output folder without asking |
| `--open` | Open the output folder when finished |
| `--html` | Also write an `index.html` for browsing the docs in a web browser — see [HTML viewer](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/html-viewer.md) |
| `--webmcp` | Make the HTML viewer agent-ready, with tools that query the solution — see [HTML viewer](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/html-viewer.md#agent-ready-html---webmcp) |
| `--coverage` | Check that everything in the export reached the docs and write `Reports/coverage.md` |
| `--scrub-level secrets\|standard\|strict` | How much to redact (default `secrets`) — see [Scrubbing](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/scrubbing.md) |
| `--disable-scrubbing` | Turn secret scrubbing off |
| `--strict` | Exit non-zero if any reference is left unresolved |

Run `fm-saxml <command> --help` for every option. The [technical README](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/README_technical.md) covers the rest, including CI flags, the output layout, and known limitations.

## Documentation

| Document | Covers |
|---|---|
| [HTML viewer and WebMCP](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/html-viewer.md) | `--html`, `--webmcp`, `serve`, and the agent tools |
| [Secret and personal-data scrubbing](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/scrubbing.md) | What is redacted, scrub levels, and the `scrub` command |
| [Multi-file solutions](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/multi-file.md) | Building a folder of exports from FileMaker 26 |
| [Comparing exports](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/docs/diff.md) | The `diff` command |
| [Technical README](https://github.com/Blue-Kachina/fm-doc-saxml/blob/master/README_technical.md) | Pipeline, output layout, coverage report, development, FileMaker XML notes, known limitations |

## License

[MIT](./LICENSE)

The secret-detection rules in `src/fm_saxml/scrub/` are adapted from the [FileMaker XML Scrubber](https://github.com/andykear/FileMaker-XML-scrubber) by Andrew Kear, Clockwork Creative Technology, used under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
