"""Where converted docs live (C3): --docs-root / FM_SAXML_DOCS_ROOT, docs.json, find_docs(), staged rebuilds."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fm_saxml.cli as cli
from fm_saxml import DocsNotFoundError, find_docs, load
from fm_saxml.api import DOCS_ROOT_ENV
from fm_saxml.cli import app

ROOT = Path(__file__).resolve().parent.parent
BY_TYPE = ROOT / "samples" / "by_type"
BAGEL = BY_TYPE / "whole" / "EverythingBagel.xml"
runner = CliRunner()
BUILD = ["build", "-y", "--disable-scrubbing"]  # unscrubbed: the sample trips backlog B1


@pytest.fixture(autouse=True)
def _need_samples(monkeypatch):
    if not BY_TYPE.exists():
        pytest.skip("samples/by_type fixture not present")
    monkeypatch.delenv(DOCS_ROOT_ENV, raising=False)


def _build(*args, env=None):
    result = runner.invoke(app, [*BUILD, *map(str, args)], env=env)
    assert result.exit_code == 0, result.output
    return result


def _catalog(folder: Path) -> dict:
    return json.loads((folder / "docs.json").read_text(encoding="utf-8"))


def _siblings(out: Path) -> list[str]:
    return sorted(p.name for p in out.parent.iterdir() if p.name.startswith(f"{out.name}."))


def test_cli_and_api_use_the_same_variable():
    assert cli.DOCS_ROOT_ENV == DOCS_ROOT_ENV == "FM_SAXML_DOCS_ROOT"


# ---------------------------------------------------------------------------
# Docs root and solution names
# ---------------------------------------------------------------------------

def test_docs_root_option(tmp_path):
    _build(BAGEL, "--docs-root", tmp_path / "root")
    out = tmp_path / "root" / "EverythingBagel"
    assert (out / "index.md").is_file()
    assert _catalog(out)["solution"] == "EverythingBagel" and _catalog(out)["kind"] == "single"


def test_docs_root_environment_variable(tmp_path):
    _build(BAGEL, env={DOCS_ROOT_ENV: str(tmp_path / "root")})
    assert (tmp_path / "root" / "EverythingBagel" / "docs.json").is_file()


def test_solution_name_comes_from_the_export_not_the_input_file_name(tmp_path):
    timestamped = tmp_path / "in" / "EverythingBagel 2026-10-21 1530.xml"
    timestamped.parent.mkdir()
    shutil.copyfile(BAGEL, timestamped)
    _build(timestamped, "--docs-root", tmp_path / "root")
    assert [p.name for p in (tmp_path / "root").iterdir()] == ["EverythingBagel"]


def test_solution_option_and_slug(tmp_path):
    _build(BAGEL, "--docs-root", tmp_path / "root", "--solution", "Bagel: Prod")
    out = tmp_path / "root" / "Bagel_ Prod"
    assert _catalog(out)["solution"] == "Bagel: Prod"


def test_out_wins_over_docs_root(tmp_path):
    _build(BAGEL, "--docs-root", tmp_path / "root", "-o", tmp_path / "here")
    assert (tmp_path / "here" / "docs.json").is_file() and not (tmp_path / "root").exists()


def test_batch_catalog(tmp_path):
    _build(BY_TYPE / "second_file", "--docs-root", tmp_path / "root")
    out = tmp_path / "root" / "second_file"  # a folder of exports: the folder's name
    cat = _catalog(out)
    assert cat["kind"] == "batch" and cat["solution"] == "second_file"
    assert {f["name"] for f in cat["files"]} == {"EverythingBagel", "Empty"}
    for f in cat["files"]:
        assert (out / f["folder"] / "entities.json").is_file()
    assert any(p["dataSource"] == "Empty" and p["targetFolder"] for p in cat["pairings"])
    assert cat["synthesizedManifest"] is False


def test_no_include_json_writes_no_catalog(tmp_path):
    _build(BAGEL, "-o", tmp_path / "out", "--no-include-json")
    assert not (tmp_path / "out" / "docs.json").exists() and (tmp_path / "out" / "index.md").exists()


def test_render_writes_the_catalog(tmp_path):
    model = tmp_path / "model.json"
    assert runner.invoke(app, ["parse", str(BAGEL), "-o", str(model), "--disable-scrubbing"]).exit_code == 0
    result = runner.invoke(app, ["render", "markdown", "-m", str(model), "-o", str(tmp_path / "docs"), "-y",
                                 "--disable-scrubbing"])
    assert result.exit_code == 0, result.output
    assert _catalog(tmp_path / "docs")["kind"] == "single"


# ---------------------------------------------------------------------------
# find_docs
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docs_root(tmp_path_factory) -> Path:
    if not BY_TYPE.exists():
        pytest.skip("samples/by_type fixture not present")
    root = tmp_path_factory.mktemp("docs_root")
    _build(BAGEL, "--docs-root", root)
    _build(BY_TYPE / "second_file", "--docs-root", root, "--solution", "Two Files")
    (root / "not docs").mkdir()
    return root


def test_find_docs_by_folder_solution_and_file(docs_root):
    assert find_docs("everythingbagel", docs_root) == docs_root / "EverythingBagel"
    assert find_docs("EverythingBagel.fmp12", docs_root) == docs_root / "EverythingBagel"
    assert find_docs("two files", docs_root) == docs_root / "Two Files"
    empty = find_docs("Empty", docs_root)  # a file inside a batch: that file's own folder
    assert empty.parent == docs_root / "Two Files" and load(empty).name == "Empty"


def test_find_docs_reads_the_environment(docs_root, monkeypatch):
    monkeypatch.setenv(DOCS_ROOT_ENV, str(docs_root))
    assert find_docs("EverythingBagel") == docs_root / "EverythingBagel"


def test_find_docs_errors(docs_root, tmp_path):
    with pytest.raises(DocsNotFoundError) as exc:
        find_docs("Invoices", docs_root)
    assert "EverythingBagel" in str(exc.value) and "Two Files (" in str(exc.value)
    with pytest.raises(DocsNotFoundError, match=DOCS_ROOT_ENV):
        find_docs("Invoices")
    with pytest.raises(DocsNotFoundError, match="not a folder"):
        find_docs("Invoices", tmp_path / "missing")


def test_find_docs_ambiguous(tmp_path):
    _build(BAGEL, "--docs-root", tmp_path, "--solution", "A")
    _build(BAGEL, "--docs-root", tmp_path, "--solution", "B")
    with pytest.raises(DocsNotFoundError, match="several"):
        find_docs("EverythingBagel.fmp12", tmp_path)  # no folder or solution named that; two files are


# ---------------------------------------------------------------------------
# Staged rebuild
# ---------------------------------------------------------------------------

def test_rebuild_replaces_the_folder_and_leaves_nothing_behind(tmp_path):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    _build(BAGEL, "-o", out)
    assert not (out / "stale.md").exists() and (out / "docs.json").is_file()
    assert _siblings(out) == []


def test_failed_build_keeps_the_old_docs(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    before = sorted(p.relative_to(out) for p in out.rglob("*"))

    def boom(*_a, **_k):
        raise RuntimeError("renderer crashed")
    monkeypatch.setattr(cli, "_render_markdown_with_progress", boom)
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code != 0
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == before
    assert _siblings(out) == []


def _lock(monkeypatch, *paths: Path) -> None:
    """Make renaming any of ``paths`` fail, every time."""
    real_replace = os.replace

    def locked(src, dst):
        if Path(src) in paths:
            raise PermissionError(13, "The process cannot access the file")
        return real_replace(src, dst)
    monkeypatch.setattr(cli.os, "replace", locked)
    monkeypatch.setattr(cli, "_SWAP_DELAYS", (0,) * 5)


def test_swap_that_cannot_move_the_old_folder_replaces_its_contents(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    _lock(monkeypatch, out)
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code == 0, result.output
    said = " ".join(result.output.split())  # the console wraps long lines
    assert "its contents were replaced instead of the folder" in said
    assert not (out / "stale.md").exists() and (out / "docs.json").is_file()
    assert _siblings(out) == []


def test_swap_with_a_file_held_in_the_old_folder_keeps_both(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    before = sorted(p.relative_to(out) for p in out.rglob("*"))
    _lock(monkeypatch, out, out / "entities.json")
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code == 1
    said = " ".join(result.output.split())
    assert "Could not replace" in said and "is in use by another program" in said
    # a path longer than the console is folded mid-word, so match it with the whitespace gone
    assert f"{out / 'entities.json'}isinusebyanotherprogram" in "".join(result.output.split())
    assert "the new docs are in" in said and "the previous ones are unchanged" in said
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == before
    staged = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    assert _siblings(out) == [staged.name] and (staged / "docs.json").is_file()
    shutil.rmtree(staged)


def test_swap_contents_puts_everything_back_when_a_new_entry_cannot_move_in(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    before = sorted(p.relative_to(out) for p in out.rglob("*"))
    staged = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    _lock(monkeypatch, out, staged / "index.md")
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code == 1
    assert f"{staged / 'index.md'}isinusebyanotherprogram" in "".join(result.output.split())
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == before
    assert _siblings(out) == [staged.name]
    assert (staged / "docs.json").is_file() and (staged / "index.md").is_file()
    shutil.rmtree(staged)


@pytest.mark.skipif(sys.platform != "win32",
                    reason="only Windows refuses to rename a folder that a program uses as its current folder")
def test_rebuild_while_a_program_has_the_docs_as_its_current_folder(tmp_path, monkeypatch):
    """A terminal or File Explorer window in the docs folder: the folder stays, its contents are replaced."""
    import subprocess

    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    monkeypatch.setattr(cli, "_SWAP_DELAYS", (0,))
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=out)
    try:
        result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    finally:
        holder.kill()
        holder.wait()
    assert result.exit_code == 0, result.output
    assert not (out / "stale.md").exists() and (out / "docs.json").is_file()
    assert _siblings(out) == []


def _lock_staged(monkeypatch, out: Path, times: int) -> list[int]:
    """Make renaming the staged folder fail ``times`` times (antivirus scanning the new files)."""
    real_replace, failures = os.replace, [0]

    def locked(src, dst):
        if Path(src).name.startswith(f"{out.name}.tmp-") and failures[0] < times:
            failures[0] += 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)
    monkeypatch.setattr(cli.os, "replace", locked)
    monkeypatch.setattr(cli, "_SWAP_DELAYS", (0,) * 5)
    return failures


def test_swap_retries_moving_the_new_docs_in(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    failures = _lock_staged(monkeypatch, out, times=3)
    _build(BAGEL, "-o", out)
    assert failures[0] == 3
    assert not (out / "stale.md").exists() and (out / "docs.json").is_file()
    assert _siblings(out) == []


def test_swap_that_cannot_move_the_new_docs_in_restores_the_old(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    (out / "stale.md").write_text("from an older build", encoding="utf-8")
    before = sorted(p.relative_to(out) for p in out.rglob("*"))
    _lock_staged(monkeypatch, out, times=1000)
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code == 1
    said = " ".join(result.output.split())
    assert "Could not move the new docs into" in said and "The previous docs are back in" in said
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == before
    staged = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    assert _siblings(out) == [staged.name] and (staged / "docs.json").is_file()
    shutil.rmtree(staged)


def test_swap_into_a_new_folder_that_stays_locked(tmp_path, monkeypatch):
    out = tmp_path / "docs"
    _lock_staged(monkeypatch, out, times=1000)
    result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    assert result.exit_code == 1
    said = " ".join(result.output.split())
    assert "Could not move the new docs into" in said and "previous docs" not in said
    staged = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    assert not out.exists() and (staged / "docs.json").is_file()
    shutil.rmtree(staged)


def test_rebuild_with_a_file_open_in_the_docs(tmp_path, monkeypatch):
    """A reader holding a file open: Windows refuses the swap (clear error, old docs kept); POSIX swaps."""
    out = tmp_path / "docs"
    _build(BAGEL, "-o", out)
    monkeypatch.setattr(cli, "_SWAP_DELAYS", (0,))
    with open(out / "entities.json", "rb"):
        result = runner.invoke(app, [*BUILD, str(BAGEL), "-o", str(out)])
    if sys.platform == "win32":
        assert result.exit_code == 1 and "Could not replace" in result.output
        assert (out / "docs.json").is_file()
        shutil.rmtree(out.with_name(f"{out.name}.tmp-{os.getpid()}"))
    else:
        assert result.exit_code == 0, result.output
        assert (out / "docs.json").is_file() and _siblings(out) == []
