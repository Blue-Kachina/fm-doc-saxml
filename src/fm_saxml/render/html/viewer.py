"""HTML viewer: an index.html that browses the generated Markdown, opened straight from disk.

Browsers block fetch() and local ES modules on file:// pages, so the viewer can't
read the .md files itself. Instead each page is copied into a small classic script
(``_viewer/pages/pNNNNN.js``) that the viewer loads on demand with a ``<script>``
tag, which file:// does allow. The Markdown is rendered by Milkdown Crepe, bundled
into ``_viewer/vendor/`` (built by viewer-vendor/ in the repo) so the viewer needs
no network.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

from ...model.step_kinds import CLOSES, COLOURED, CONTINUES, OPENS
from ...utils.file_writer import write_bytes, write_text

VIEWER_DIR = "_viewer"
VENDOR_DIR = "vendor"
# The bundled renderer (package data in ./vendor), copied as-is into _viewer/vendor/.
_VENDOR_FILES = ("crepe.js", "crepe.css", "nord.css", "nord-dark.css", "THIRD_PARTY_LICENSES.txt")

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
# "# Script: Foo" -> "Foo" for sidebar labels (the section already says what kind it is).
_KIND_PREFIX_RE = re.compile(r"^[^:]+:\s+")
# Root index "Sections" list: "- [Table Occurrences](TableOccurrences/index.md)".
_SECTION_LINK_RE = re.compile(r"^- \[([^\]]+)\]\(([^)/]+/[^)]+\.md)\)$", re.MULTILINE)


def viewer_pages(output_dir: Path) -> list[Path]:
    """The Markdown pages the viewer shows, in its order: each becomes one page script."""
    return sorted(
        (p for p in output_dir.rglob("*.md") if p.relative_to(output_dir).parts[0] != VIEWER_DIR),
        key=lambda p: p.relative_to(output_dir).as_posix().lower(),
    )


def script_field_links(model, folder: str = "",
                       cross_file: dict[str, tuple[str, str]] | None = None) -> dict[str, dict[str, str]]:
    """Per script page (its path in the output): each ``TO::field`` its steps write -> href of the field's page.

    Steps name fields by table occurrence while the page's Referenced Entities link text uses the
    base table, so the viewer needs this to link the field names in a ```fmscript block.
    ``folder``/``cross_file``: the file's folder and cross-file links in a multi-file build.
    """
    from ..markdown.link_resolver import LinkResolver, _encode_href  # not at import: scrub.guard imports this module

    links = LinkResolver(model, cross_file)
    steps = model.entities.script_steps
    out: dict[str, dict[str, str]] = {}
    for script in model.entities.scripts.values():
        page = links.path_for(script.doc_id)
        if page is None:
            continue
        fields: dict[str, str] = {}
        for step_id in script.steps:
            step = steps.get(step_id)
            for ref in step.references if step else ():
                raw = ref.get("rawText")
                if ref.get("kind") != "field" or not raw or "::" not in raw or raw in fields:
                    continue
                href = links.href(page, ref["targetDocId"])
                if href is not None:
                    fields[raw] = _encode_href(href)
        if fields:
            out[f"{folder}/{page}" if folder else page] = fields
    return out


def render_html_viewer(output_dir: Path, webmcp_files: list[dict] | None = None,
                       md_files: list[Path] | None = None,
                       on_page: Callable[[], None] | None = None,
                       field_links: dict[str, dict[str, str]] | None = None,
                       preview_files: list[dict] | None = None) -> int:
    """Write ``index.html`` plus ``_viewer/`` over the Markdown already in ``output_dir``.

    ``webmcp_files`` (one entry per file, from ``webmcp.write_webmcp_data``) turns on the
    WebMCP tools: ``_viewer/webmcp.js`` is added and the manifest lists the files' data.
    ``preview_files`` (one entry per file, from ``layout_preview.write_layout_previews``)
    turns on the layout preview the same way: ``_viewer/layout-preview.js``.
    ``md_files`` is ``viewer_pages(output_dir)`` when the caller already has it; ``on_page``
    is called after each page script is written, for progress. ``field_links`` (from
    ``script_field_links``, keyed by page path) goes into each script page's script for its steps.
    Returns the number of pages the viewer can show.
    """
    if md_files is None:
        md_files = viewer_pages(output_dir)

    pages = []
    root_meta: dict[str, str] = {}
    root_body = ""
    for i, path in enumerate(md_files):
        rel = path.relative_to(output_dir).as_posix()
        meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        if rel == "index.md":
            root_meta, root_body = meta, body
        js_name = f"p{i:05d}.js"
        fields = (field_links or {}).get(rel)
        extra = f",{_js_literal({'fields': fields}, compact=True)}" if fields else ""
        write_text(
            output_dir / VIEWER_DIR / "pages" / js_name,
            f"FMDocs.page({_js_literal(rel)},{_js_literal(meta)},{_js_literal(body)}{extra});\n",
        )
        page = {"p": rel, "t": _page_title(path, meta, body), "f": js_name}
        if meta.get("folder"):
            page["g"] = _sidebar_dirs(rel, meta)
        pages.append(page)
        if on_page is not None:
            on_page()

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
        # Script steps the viewer folds (block opens/continues/closes) and colours in ```fmscript fences.
        "stepKinds": {
            "opens": sorted(OPENS),
            "continues": sorted(CONTINUES),
            "closes": sorted(CLOSES),
            "coloured": sorted(COLOURED),
        },
    }
    templates = resources.files(__package__).joinpath("templates")
    webmcp_tag = ""
    if webmcp_files is not None:
        manifest["webmcp"] = {"files": [{k: f[k] for k in ("key", "label", "dir")} for f in webmcp_files]}
        script = templates.joinpath("webmcp.js").read_text(encoding="utf-8")
        write_text(output_dir / VIEWER_DIR / "webmcp.js", script)
        webmcp_tag = f'<script src="{VIEWER_DIR}/webmcp.js"></script>'
        write_text(output_dir / "llms.txt", _llms_txt(title, webmcp_files, _tool_names(script, preview_files is not None),
                                                      layout_preview=preview_files is not None))
    preview_tag = ""
    if preview_files is not None:
        manifest["layoutPreview"] = {"files": [{k: f[k] for k in ("key", "dir")} for f in preview_files]}
        write_text(output_dir / VIEWER_DIR / "layout-preview.js",
                   templates.joinpath("layout-preview.js").read_text(encoding="utf-8"))
        preview_tag = f'<script src="{VIEWER_DIR}/layout-preview.js"></script>'
    write_text(output_dir / VIEWER_DIR / "manifest.js", f"FMDocs.manifest({_js_literal(manifest)});\n")
    vendor = resources.files(__package__).joinpath(VENDOR_DIR)
    for name in _VENDOR_FILES:
        write_bytes(output_dir / VIEWER_DIR / VENDOR_DIR / name, vendor.joinpath(name).read_bytes())

    template = templates.joinpath("index.html").read_text(encoding="utf-8")
    page = (template.replace("{{TITLE}}", html.escape(title)).replace("<!--WEBMCP-->", webmcp_tag)
            .replace("<!--LAYOUT_PREVIEW-->", preview_tag))
    write_text(output_dir / "index.html", page)
    return len(pages)


# The tools webmcp.js defines: ``tool('search_entities', ...`` and, only with the layout preview,
# ``layoutTool('locate_layout_object', ...``.
_TOOL_NAME_RE = re.compile(r"^    (?:tool|layoutTool)\('([a-z_]+)'", re.MULTILINE)
_LAYOUT_TOOL_RE = re.compile(r"^    layoutTool\('([a-z_]+)'", re.MULTILINE)


def _tool_names(script: str, layout_preview: bool) -> list[str]:
    """The global tools in ``webmcp.js``, without the layout tools when there is no layout preview."""
    layout_tools = set() if layout_preview else set(_LAYOUT_TOOL_RE.findall(script))
    return [n for n in _TOOL_NAME_RE.findall(script) if n not in layout_tools]


def _llms_txt(title: str, files: list[dict], tool_names: list[str], layout_preview: bool = False) -> str:
    """Plain-text pointer for agents that read a site's llms.txt before its pages."""
    labels = ", ".join(f["label"] for f in files)
    example = '{"tool":"describe_schema","args":{}}'
    layouts = ", and where objects are on layouts" if layout_preview else ""
    layout_notes = """- Layout objects: locate_layout_object, objects_at and layout_problems give bounds that are absolute
  (points from the layout's top left), plus shownIn, visibleAtOpen, a position in words and a previewUrl.
  The layoutObject records' bounds are FileMaker's own: relative to the container for nested objects.
  `index.html#/layout?doc=<layout docId>&highlight=<docId>,<docId>` shows objects on the layout preview.
""" if layout_preview else ""
    return f"""# {title}

> Documentation of a FileMaker solution ({labels}), generated by fm-saxml. The HTML viewer
> (index.html) has {len(tool_names)} query tools (none change anything) over the solution's model: search,
> filters, script steps, references, dead code, multi-step traversal, who can access what{layouts}.

## Using the tools

- WebMCP: the viewer registers the tools on document.modelContext when the browser offers it
  (open it from http://127.0.0.1 via `fm-saxml serve`, not from disk).
- JavaScript in the page: `await FMDocs.tools.<name>.execute({{...args}})`, or
  `await FMDocs.webmcp.call("<name>", {{...args}})` for the plain result object.
- By URL, for agents that only open and read pages:
  `index.html#/results?q=<URL-encoded {example}>&format=json`
  shows the result as JSON text in <pre id="fm-result-json">.

## Reading the results

- Who can run, view or change something: use who_can_access / what_can_access (scripts, layouts,
  value lists, fields, tables). Each answer gives the reason, so don't work it out from the lists.
- No callers doesn't mean unused: other files, server schedules, fmp:// URLs and Perform Script
  by name don't appear.
- Reports/coverage.md (a --coverage build) says which areas of the XML fully reached the docs.
- [REDACTED:...] marks a value that scrubbing replaced. That code isn't the file's real code.
{layout_notes}
## Reference

- [Tool guide with argument schemas and runnable examples](index.html#/agents)
- [Overview](index.html#/index.md)
- Tools: {", ".join(tool_names)}
"""


def _sidebar_dirs(rel: str, meta: dict[str, str]) -> list[str]:
    """The sidebar folders of a layout or script page: its section's folders (``Scripts``, or ``File/Scripts`` in a
    multi-file build), then its FileMaker folders by their real names (not the slugs in the page's path)."""
    folders = meta["folder"].split(" › ")
    dirs = rel.split("/")[:-1]
    if meta.get("entityType") == "script":
        dirs = dirs[:len(dirs) - len(folders)]  # a script's path has one directory per folder; a layout's has none
    return [*dirs, *folders]


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


def _js_literal(value: object, compact: bool = False) -> str:
    """JSON safe to embed in a script: no '<' (so no '</script>' or '<!--'), no raw U+2028/2029."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":") if compact else None)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
