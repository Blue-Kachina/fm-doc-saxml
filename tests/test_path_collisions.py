"""Case-insensitive file-name collision handling (Windows/macOS file systems)."""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from fm_saxml.analyze.backlinks import generate_backlinks
from fm_saxml.normalize.normalize import normalize
from fm_saxml.normalize.paths import dedupe_paths
from fm_saxml.normalize.references import resolve_references
from fm_saxml.parser.saxml_reader import parse_savexml
from fm_saxml.render.markdown.renderer import render_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "small_sample.xml"


# ---------------------------------------------------------------------------
# dedupe_paths (pure function)
# ---------------------------------------------------------------------------

def test_unique_paths_unchanged():
    paths = {"a": "Scripts/Foo.md", "b": "Scripts/Bar.md"}
    assert dedupe_paths(paths) == paths


def test_case_only_difference_is_split():
    out = dedupe_paths({"a": "Scripts/Foo.md", "b": "Scripts/foo.md"})
    assert len({p.lower() for p in out.values()}) == 2
    assert out["a"] == "Scripts/Foo.md"  # uppercase sorts first and keeps its name
    assert out["b"] == "Scripts/foo-2.md"


def test_identical_slugs_from_different_names_are_split():
    out = dedupe_paths({"x": "Tables/a_b.md", "y": "Tables/a_b.md"})
    assert sorted(out.values()) == ["Tables/a_b-2.md", "Tables/a_b.md"]


def test_same_name_in_different_folders_is_not_a_collision():
    paths = {"a": "Tables/Foo.md", "b": "Scripts/foo.md"}
    assert dedupe_paths(paths) == paths


def test_entity_named_index_does_not_clobber_section_index():
    out = dedupe_paths({"a": "Tables/index.md", "b": "Tables/Other.md"})
    assert out["a"] == "Tables/index-2.md"
    assert out["b"] == "Tables/Other.md"


def test_suffix_avoids_existing_names():
    out = dedupe_paths({"a": "S/Foo.md", "b": "S/foo.md", "c": "S/foo-2.md"})
    assert len({p.lower() for p in out.values()}) == 3


def test_result_is_independent_of_input_order():
    items = [("a", "S/Foo.md"), ("b", "S/foo.md"), ("c", "S/FOO.md")]
    assert dedupe_paths(dict(items)) == dedupe_paths(dict(reversed(items)))


# ---------------------------------------------------------------------------
# End to end: render a model that contains case-colliding names
# ---------------------------------------------------------------------------

@pytest.fixture
def colliding_model():
    m = normalize(parse_savexml(FIXTURE))
    em = m.entities

    table = next(iter(em.tables.values()))
    clone = table.model_copy(update={"doc_id": "table:" + table.name.lower(), "name": table.name.lower()})
    em.tables[clone.doc_id] = clone

    field = next(f for f in em.fields.values() if f.base_table_doc_id == table.doc_id)
    twin = field.model_copy(
        update={
            "doc_id": "field:twin",
            "name": field.name.swapcase(),
            "base_table_doc_id": clone.doc_id,
        }
    )
    em.fields[twin.doc_id] = twin
    # same field name, different table whose folder differs only by case
    twin2 = field.model_copy(update={"doc_id": "field:twin2", "base_table_doc_id": clone.doc_id})
    em.fields[twin2.doc_id] = twin2

    script = next(iter(em.scripts.values()))
    em.scripts["script:swapped"] = script.model_copy(
        update={"doc_id": "script:swapped", "name": script.name.swapcase()}
    )
    em.tables["table:index"] = table.model_copy(update={"doc_id": "table:index", "name": "index"})

    m = resolve_references(m)
    return generate_backlinks(m)


def _md_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md")]


def test_rendered_files_are_unique_ignoring_case(colliding_model, tmp_path):
    render_markdown(colliding_model, tmp_path)
    rels = [p.relative_to(tmp_path).as_posix().lower() for p in _md_files(tmp_path)]
    assert len(rels) == len(set(rels))


def test_every_entity_gets_its_own_page(colliding_model, tmp_path):
    render_markdown(colliding_model, tmp_path)
    em = colliding_model.entities
    pages = len(em.tables) + len(em.fields) + len(em.scripts)
    written = [
        p for p in _md_files(tmp_path)
        if p.relative_to(tmp_path).parts[0] in {"Tables", "Fields", "Scripts"}
        and p.name != "index.md"
    ]
    assert len(written) == pages


def test_all_relative_links_resolve(colliding_model, tmp_path):
    render_markdown(colliding_model, tmp_path)
    link = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
    broken = []
    for page in _md_files(tmp_path):
        for target in link.findall(page.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://")):
                continue
            if not (page.parent / unquote(target)).resolve().exists():
                broken.append((page.relative_to(tmp_path).as_posix(), target))
    assert not broken, broken[:10]
