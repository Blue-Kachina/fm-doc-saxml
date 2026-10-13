"""--html: the file://-friendly index.html viewer over the generated Markdown."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from fm_saxml.cli import app
from fm_saxml.render.html import VIEWER_DIR, render_html_viewer
from fm_saxml.render.markdown.renderer import _render_section_index

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _call_args(js: str, fn: str) -> list:
    """Parse ``FMDocs.<fn>(a, b, ...);`` back into Python values."""
    prefix = f"FMDocs.{fn}("
    assert js.startswith(prefix) and js.endswith(");\n"), js[:80]
    return json.loads("[" + js[len(prefix):-3] + "]")


def _manifest(out: Path) -> dict:
    return _call_args((out / VIEWER_DIR / "manifest.js").read_text(encoding="utf-8"), "manifest")[0]


def _build(tmp_path: Path, *extra: str) -> Path:
    xml = tmp_path / "Sample.xml"
    xml.write_bytes((FIXTURES / "small_sample.xml").read_bytes())
    result = runner.invoke(app, ["build", str(xml), *extra])
    assert result.exit_code == 0, result.output
    return tmp_path / "Sample_docs"


def test_build_without_html_writes_no_viewer(tmp_path):
    out = _build(tmp_path)
    assert not (out / "index.html").exists()
    assert not (out / VIEWER_DIR).exists()


def test_build_with_html_covers_every_markdown_page(tmp_path):
    out = _build(tmp_path, "--html")
    assert (out / "index.html").exists()

    manifest = _manifest(out)
    md_pages = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md"))
    assert sorted(p["p"] for p in manifest["pages"]) == md_pages

    for page in manifest["pages"]:
        js = (out / VIEWER_DIR / "pages" / page["f"]).read_text(encoding="utf-8")
        path, meta, body = _call_args(js, "page")
        assert path == page["p"]
        source = (out / path).read_text(encoding="utf-8")
        assert source.endswith(body)
        assert not body.startswith("---")  # frontmatter is passed separately, not rendered


def test_sidebar_sections_follow_root_index(tmp_path):
    out = _build(tmp_path, "--html")
    sections = _manifest(out)["sections"]
    assert sections, "root index lists sections"
    assert sections[0] == {"dir": "Tables", "label": "Tables", "target": "Tables/index.md"}
    assert {"dir": "Reports", "label": "Reports", "target": "Reports/summary.md"} in sections


def test_render_command_accepts_html(tmp_path):
    xml = tmp_path / "Sample.xml"
    xml.write_bytes((FIXTURES / "small_sample.xml").read_bytes())
    model = tmp_path / "model.json"
    assert runner.invoke(app, ["parse", str(xml), "-o", str(model)]).exit_code == 0
    out = tmp_path / "docs"
    result = runner.invoke(app, ["render", "-m", str(model), "-o", str(out), "--html"])
    assert result.exit_code == 0, result.output
    assert (out / "index.html").exists()
    assert (out / VIEWER_DIR / "manifest.js").exists()


def test_page_scripts_cannot_break_out_of_script_context(tmp_path):
    (tmp_path / "index.md").write_text("# Root\n", encoding="utf-8")
    nasty = "Calc: \"</script><script>alert(1)</script>\" <!--   été\n"
    (tmp_path / "Scripts").mkdir()
    (tmp_path / "Scripts" / "x.md").write_text(f"---\nname: </script>\n---\n\n# Script: x\n\n{nasty}", encoding="utf-8")

    render_html_viewer(tmp_path)

    manifest = _manifest(tmp_path)
    entry = next(p for p in manifest["pages"] if p["p"] == "Scripts/x.md")
    js = (tmp_path / VIEWER_DIR / "pages" / entry["f"]).read_text(encoding="utf-8")
    assert "<" not in js
    assert " " not in js
    _, meta, body = _call_args(js, "page")
    assert meta == {"name": "</script>"}
    assert body.endswith(nasty)
    assert "été" in js  # non-ASCII stays readable (and visible to the scrubbing guard)


def test_title_is_html_escaped(tmp_path):
    (tmp_path / "index.md").write_text("---\ntitle: A & <B>\n---\n\n# A & <B>\n", encoding="utf-8")
    render_html_viewer(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<title>A &amp; &lt;B&gt;</title>" in page
    assert "{{TITLE}}" not in page


def test_page_titles(tmp_path):
    (tmp_path / "index.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "Tables").mkdir()
    (tmp_path / "Tables" / "index.md").write_text("# Tables\n", encoding="utf-8")
    (tmp_path / "Tables" / "T.md").write_text("---\nentityType: table\nname: Contacts\n---\n\n# Table: Contacts\n", encoding="utf-8")
    (tmp_path / "Tables" / "9.md").write_text("---\nentityType: layoutObject\n---\n\n# Layout Object: A::b\n", encoding="utf-8")
    render_html_viewer(tmp_path)
    titles = {p["p"]: p["t"] for p in _manifest(tmp_path)["pages"]}
    assert titles == {"index.md": "Root", "Tables/index.md": "Tables", "Tables/T.md": "Contacts", "Tables/9.md": "A::b"}


def test_section_index_keeps_multiline_names_in_one_row(tmp_path):
    """A text layout object's name can span lines; it must not end the index table early."""
    entities = [
        SimpleNamespace(doc_id="a", name="<<T::Adresse>>\n<<T::Ville>> | x"),
        SimpleNamespace(doc_id="b", name="Plain [tag"),
    ]
    links = SimpleNamespace(path_for=lambda doc_id: f"LayoutObjects/L/{doc_id}.md")
    out = tmp_path / "index.md"
    _render_section_index(
        entities, out,
        section_title="Layout Objects", entity_type_label="layout object",
        extra_header="Layout", extra_col_fn=lambda e: "L\nM",
        index_path="LayoutObjects/index.md", links=links,
    )
    rows = [line for line in out.read_text(encoding="utf-8").splitlines() if line.startswith("| [")]
    assert rows == [
        r"| [<<T::Adresse>> <<T::Ville>> \| x](L/a.md) | L M |",
        r"| [Plain \[tag](L/b.md) | L M |",
    ]
