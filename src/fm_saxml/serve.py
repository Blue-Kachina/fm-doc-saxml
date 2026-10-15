"""``fm-saxml serve``: the --webmcp viewer over http://127.0.0.1, so browsers give it WebMCP.

Browsers expose WebMCP (``document.modelContext``) only to pages with a real, secure
origin. A page opened from disk (file://) has neither, but ``localhost`` counts as
secure, so serving the docs folder locally is enough. The server binds to 127.0.0.1
only, serves nothing outside the folder, and turns away requests addressed to any
other host name (so a web page can't reach it through DNS rebinding).
"""

from __future__ import annotations

import http.server
from pathlib import Path

from .render.html.viewer import VIEWER_DIR

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def has_webmcp(docs_dir: Path) -> bool:
    """Whether ``docs_dir`` holds a viewer built with --webmcp."""
    return (docs_dir / "index.html").is_file() and (docs_dir / VIEWER_DIR / "webmcp.js").is_file()


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                      ".json": "application/json; charset=utf-8"}
    allowed_hosts: frozenset[str] = frozenset()

    def _host_ok(self) -> bool:
        if (self.headers.get("Host") or "").lower() in self.allowed_hosts:
            return True
        self.send_error(421, "Misdirected request")
        return False

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        if self._host_ok():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._host_ok():
            super().do_HEAD()

    def end_headers(self) -> None:
        # A rebuild should show on reload, not a cached copy of the old pages.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (base class signature)
        pass


def make_server(docs_dir: Path, port: int = DEFAULT_PORT) -> http.server.ThreadingHTTPServer:
    """A server for ``docs_dir`` on ``port`` (0: any free port), or on a free port if that one is taken."""
    try:
        return _bind(docs_dir, port)
    except OSError:
        if port == 0:
            raise
        return _bind(docs_dir, 0)


def _bind(docs_dir: Path, port: int) -> http.server.ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {})
    server = http.server.ThreadingHTTPServer(
        (HOST, port), lambda *a, **kw: handler(*a, directory=str(docs_dir), **kw))
    bound = server.server_address[1]
    handler.allowed_hosts = frozenset({f"127.0.0.1:{bound}", f"localhost:{bound}"})
    return server


def url_for(server: http.server.ThreadingHTTPServer) -> str:
    return f"http://{HOST}:{server.server_address[1]}/index.html"
