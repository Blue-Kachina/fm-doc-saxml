"""File path generation for documentation output."""

from __future__ import annotations

from pathlib import PurePosixPath

from .names import safe_slug, folder_parts


def table_path(table_name: str) -> str:
    return f"Tables/{safe_slug(table_name)}.md"


def field_path(table_name: str, field_name: str) -> str:
    return field_path_in(safe_slug(table_name), field_name)


def field_path_in(table_dir: str, field_name: str) -> str:
    """Field page path inside an already-slugged (and de-duplicated) table folder."""
    return f"Fields/{table_dir}/{safe_slug(field_name)}.md"


def table_occurrence_path(to_name: str) -> str:
    return f"TableOccurrences/{safe_slug(to_name)}.md"


def relationship_path(rel_name: str) -> str:
    return f"Relationships/{safe_slug(rel_name)}.md"


def layout_path(layout_name: str) -> str:
    return f"Layouts/{safe_slug(layout_name)}.md"


def layout_object_path(layout_name: str, object_id: str) -> str:
    """Path for a single layout-object detail page (one per object)."""
    return layout_object_path_in(safe_slug(layout_name), object_id)


def layout_object_path_in(layout_dir: str, object_id: str) -> str:
    """Layout-object page path inside an already-slugged (and de-duplicated) layout folder."""
    return f"LayoutObjects/{layout_dir}/{safe_slug(object_id) or 'object'}.md"


def script_path(script_name: str, folder: str | None = None) -> str:
    if folder:
        parts = folder_parts(folder)
        folder_seg = "/".join(safe_slug(p) for p in parts)
        return f"Scripts/{folder_seg}/{safe_slug(script_name)}.md"
    return f"Scripts/{safe_slug(script_name)}.md"


def custom_function_path(cf_name: str) -> str:
    return f"CustomFunctions/{safe_slug(cf_name)}.md"


def value_list_path(vl_name: str) -> str:
    return f"ValueLists/{safe_slug(vl_name)}.md"


def privilege_set_path(ps_name: str) -> str:
    return f"Privileges/{safe_slug(ps_name)}.md"


def account_path(name: str) -> str:
    return f"Accounts/{safe_slug(name)}.md"


def extended_privilege_path(name: str) -> str:
    return f"ExtendedPrivileges/{safe_slug(name)}.md"


def custom_menu_path(name: str) -> str:
    return f"CustomMenus/{safe_slug(name)}.md"


def custom_menu_set_path(name: str) -> str:
    return f"CustomMenuSets/{safe_slug(name)}.md"


def theme_path(name: str) -> str:
    return f"Themes/{safe_slug(name)}.md"


def file_reference_path(doc_id: str) -> str:
    slug = safe_slug(doc_id.replace("fileRef:", "").replace(":", "_"))
    return f"FileAccess/{slug}.md"


def dedupe_paths(paths: dict[str, str]) -> dict[str, str]:
    """Return ``paths`` with every value unique, ignoring case.

    Windows and macOS file systems are case-insensitive, so ``Scripts/Foo.md``
    and ``Scripts/foo.md`` would overwrite each other. Distinct names can also
    collapse to one slug (``a:b`` and ``a_b``), and an entity named "index"
    would overwrite its section's ``index.md``. In each case the first entry
    (sorted by path, then key) keeps its path and the rest get ``-2``, ``-3``…
    appended to the file name. The result is deterministic and independent of
    input order, so it is safe to compute once and share across renderers.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for key, path in paths.items():
        groups.setdefault(path.lower(), []).append((path, key))

    # Section index pages are written by the renderer into every directory.
    reserved = {str(PurePosixPath(path).parent / "index.md").lower() for path in paths.values()}

    result: dict[str, str] = {}
    taken: set[str] = set()
    losers: list[tuple[str, str]] = []
    for lowered in sorted(groups):
        members = sorted(groups[lowered])
        if lowered in reserved:
            losers.extend(members)
            continue
        (path, key), *rest = members
        result[key] = path
        taken.add(lowered)
        losers.extend(rest)

    for path, key in sorted(losers):
        p = PurePosixPath(path)
        n = 2
        while True:
            candidate = str(p.with_name(f"{p.stem}-{n}{p.suffix}"))
            if candidate.lower() not in taken and candidate.lower() not in reserved:
                break
            n += 1
        result[key] = candidate
        taken.add(candidate.lower())
    return result


def relative_md_link(from_path: str, to_path: str) -> str:
    """Return a relative path from `from_path` to `to_path` (POSIX-style)."""
    from_parts = PurePosixPath(from_path).parent
    to_parts = PurePosixPath(to_path)
    try:
        rel = to_parts.relative_to(from_parts)
        return str(rel)
    except ValueError:
        pass
    # Compute ../../.. prefix
    from_depth = len(from_parts.parts)
    backs = "../" * from_depth
    return backs + to_path
