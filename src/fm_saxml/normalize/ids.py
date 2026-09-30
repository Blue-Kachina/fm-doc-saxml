"""DocId generation — stable, human-readable documentation identifiers."""

from __future__ import annotations


def table_doc_id(name: str) -> str:
    return f"table:{name}"


def field_doc_id(table_name: str, field_name: str) -> str:
    return f"field:{table_name}::{field_name}"


def to_doc_id(name: str) -> str:
    return f"to:{name}"


def relationship_doc_id(name: str) -> str:
    return f"relationship:{name}"


def layout_doc_id(name: str) -> str:
    return f"layout:{name}"


def layout_object_doc_id(layout_name: str, object_id: str, fallback_index: int = 0) -> str:
    """Build a stable docId for a single layout object.

    ``object_id`` is the FileMaker-assigned id within the layout. When the id
    is missing we fall back to the object's positional index, prefixed with
    'idx' so it can't collide with a real id.
    """
    if object_id:
        return f"layoutObject:{layout_name}::{object_id}"
    return f"layoutObject:{layout_name}::idx{fallback_index:04d}"


def script_doc_id(name: str) -> str:
    return f"script:{name}"


def script_step_doc_id(script_name: str, index: int) -> str:
    return f"scriptStep:{script_name}:{index:04d}"


def custom_function_doc_id(name: str) -> str:
    return f"customFunction:{name}"


def value_list_doc_id(name: str) -> str:
    return f"valueList:{name}"


def privilege_set_doc_id(name: str) -> str:
    return f"privilegeSet:{name}"


def account_doc_id(name: str) -> str:
    return f"account:{name}"


def extended_privilege_doc_id(name: str) -> str:
    return f"extPriv:{name}"


def custom_menu_doc_id(name: str) -> str:
    return f"customMenu:{name}"


def custom_menu_set_doc_id(name: str) -> str:
    return f"customMenuSet:{name}"


def theme_doc_id(name: str) -> str:
    return f"theme:{name}"


def file_reference_doc_id(ref_type: str, display_name: str) -> str:
    return f"fileRef:{ref_type}:{display_name}"


# ---------------------------------------------------------------------------
# File-scoped docIds
#
# Within one file's model, docIds stay short and unscoped ("script:Name") —
# they name Markdown files and key every lookup. To make entities from two
# files unambiguous when merged, or to point at an entity in another file,
# prefix a *scope*:   <scope>/<docId>     e.g.  "<fileUuid>/script:Name"
#
# Scope forms (the text before the first "/", which can never contain one):
#   <file UUID>         a file whose UUID is known (from the FMSaveAsXML root)
#   file:<fmp name>     fallback when an export has no file UUID
#   ds:<data source>    PROVISIONAL: "the file that data source <uuid> names".
#                       An export knows its data sources but not the target
#                       file's own UUID; a multi-file run rewrites ds:... to
#                       the real file UUID once it has paired the files.
# DocIds themselves may contain "/" (script names can), so always split on
# the first "/" only, via split_scoped_doc_id().
# ---------------------------------------------------------------------------

import re as _re

_SCOPE_RE = _re.compile(
    r"^((?:ds:|file:)[^/]*|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})/(.+)$", _re.DOTALL
)


def _escape_scope_text(text: str) -> str:
    return text.replace("%", "%25").replace("/", "%2F")


def file_scope(file_uuid: str | None, fmp_file_name: str | None, fallback_name: str = "") -> str:
    """Scope identifying a file: its UUID, else ``file:<fmp file name>``."""
    if file_uuid:
        return file_uuid
    return f"file:{_escape_scope_text(fmp_file_name or fallback_name or 'unknown')}"


def provisional_scope(data_source_uuid: str | None, data_source_name: str) -> str:
    """Scope for a file only known through a data source of another file."""
    return f"ds:{_escape_scope_text(data_source_uuid or data_source_name)}"


def scoped_doc_id(scope: str, doc_id: str) -> str:
    return f"{scope}/{doc_id}"


def split_scoped_doc_id(value: str) -> tuple[str | None, str]:
    """Split ``<scope>/<docId>`` into ``(scope, docId)``; ``(None, value)`` if unscoped."""
    m = _SCOPE_RE.match(value)
    return (m.group(1), m.group(2)) if m else (None, value)
