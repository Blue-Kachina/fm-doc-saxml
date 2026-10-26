# Changelog

## Unreleased

### Changed

- `fm-saxml serve`, and `--serve` on `build`/`render`, now use port **8766** by default instead of 8765. The agentic-fm companion server also defaults to 8765, so the two used to clash. To keep the old port, pass `--port 8765`. As before, if the port is taken, a free one is used.
