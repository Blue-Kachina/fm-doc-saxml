"""HTML viewer: an index.html that browses the generated Markdown, opened straight from disk.

Browsers block fetch() and local ES modules on file:// pages, so the viewer can't
read the .md files itself. Instead each page is copied into a small classic script
(``_viewer/pages/pNNNNN.js``) that the viewer loads on demand with a ``<script>``
tag, which file:// does allow. The Markdown is rendered by Milkdown Crepe, loaded
from a CDN.
"""

from __future__ import annotations

import html
import json
import re
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

from ...utils.file_writer import write_text

VIEWER_DIR = "_viewer"

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
# "# Script: Foo" -> "Foo" for sidebar labels (the section already says what kind it is).
_KIND_PREFIX_RE = re.compile(r"^[^:]+:\s+")
# Root index "Sections" list: "- [Table Occurrences](TableOccurrences/index.md)".
_SECTION_LINK_RE = re.compile(r"^- \[([^\]]+)\]\(([^)/]+/[^)]+\.md)\)$", re.MULTILINE)


def render_html_viewer(output_dir: Path) -> int:
    """Write ``index.html`` plus ``_viewer/`` over the Markdown already in ``output_dir``.

    Returns the number of pages the viewer can show.
    """
    md_files = sorted(
        (p for p in output_dir.rglob("*.md") if p.relative_to(output_dir).parts[0] != VIEWER_DIR),
        key=lambda p: p.relative_to(output_dir).as_posix().lower(),
    )

    pages = []
    root_meta: dict[str, str] = {}
    root_body = ""
    for i, path in enumerate(md_files):
        rel = path.relative_to(output_dir).as_posix()
        meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        if rel == "index.md":
            root_meta, root_body = meta, body
        js_name = f"p{i:05d}.js"
        write_text(
            output_dir / VIEWER_DIR / "pages" / js_name,
            f"FMDocs.page({_js_literal(rel)},{_js_literal(meta)},{_js_literal(body)});\n",
        )
        pages.append({"p": rel, "t": _page_title(path, meta, body), "f": js_name})

    root_heading = _HEADING_RE.search(root_body)
    title = root_meta.get("title") or (root_heading.group(1).strip() if root_heading else output_dir.name)
    manifest = {
        "title": title,
        "generatedAt": root_meta.get("generatedAt", ""),
        # Sidebar section order and labels follow the root index's "Sections" list.
        "sections": [
            {"dir": unquote(target.split("/")[0]), "label": label, "target": target}
            for label, target in _SECTION_LINK_RE.findall(root_body)
        ],
        "pages": pages,
    }
    write_text(output_dir / VIEWER_DIR / "manifest.js", f"FMDocs.manifest({_js_literal(manifest)});\n")

    template = resources.files(__package__).joinpath("templates/index.html").read_text(encoding="utf-8")
    write_text(output_dir / "index.html", template.replace("{{TITLE}}", html.escape(title)))
    return len(pages)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def _page_title(path: Path, meta: dict[str, str], body: str) -> str:
    heading = _HEADING_RE.search(body)
    if path.name == "index.md" and heading:
        return heading.group(1).strip()
    if meta.get("name"):
        return meta["name"]
    if heading:
        text = heading.group(1).strip()
        return _KIND_PREFIX_RE.sub("", text, count=1) if meta.get("entityType") else text
    return path.stem


def _js_literal(value: object) -> str:
    """JSON safe to embed in a script: no '<' (so no '</script>' or '<!--'), no raw U+2028/2029."""
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
