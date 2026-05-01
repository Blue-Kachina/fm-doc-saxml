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
