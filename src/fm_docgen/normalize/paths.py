"""File path generation for documentation output."""

from __future__ import annotations

from pathlib import PurePosixPath

from .names import safe_slug, folder_parts


def table_path(table_name: str) -> str:
    return f"Tables/{safe_slug(table_name)}.md"


def field_path(table_name: str, field_name: str) -> str:
    return f"Fields/{safe_slug(table_name)}/{safe_slug(field_name)}.md"


def table_occurrence_path(to_name: str) -> str:
    return f"TableOccurrences/{safe_slug(to_name)}.md"


def relationship_path(rel_name: str) -> str:
    return f"Relationships/{safe_slug(rel_name)}.md"


def layout_path(layout_name: str) -> str:
    return f"Layouts/{safe_slug(layout_name)}.md"


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
