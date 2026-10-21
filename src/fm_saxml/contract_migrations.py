"""Read contract files written by any version, upgrading older ones in memory.

Rules (see docs/contract.md):

* A file without ``schemaVersion`` is version **0.0**: references.json as a bare
  array, entities.json and backlinks.json without the envelope. So is an
  external-references.json with the old three-part ``"1.0.0"``, which predates
  the contract and had its own version.
* A different minor version of the current major reads as-is: unknown keys are
  ignored and missing keys take the models' defaults.
* An older major is upgraded one major at a time through ``UPGRADES``, on plain
  dicts, before validation. Nothing is written back to disk.
* A newer major fails with ``ContractVersionError``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import orjson

from .contract import CONTRACT_FILES, CONTRACT_VERSION, parse_version


class ContractVersionError(ValueError):
    """The file was written by a newer major version than this fm-saxml reads."""


def file_version(data: Any) -> tuple[int, int]:
    """``(major, minor)`` of a contract file's contents; ``(0, 0)`` when it predates the contract."""
    if not isinstance(data, dict) or "schemaVersion" not in data:
        return (0, 0)
    try:
        version = parse_version(data["schemaVersion"])
    except ValueError:
        raise ContractVersionError(f"schemaVersion {data['schemaVersion']!r} is not MAJOR.MINOR") from None
    if len(version) != 2:  # external-references.json's own "1.0.0", before the contract
        return (0, 0)
    return version  # type: ignore[return-value]


def upgrade_0_to_1(file_name: str, data: Any) -> dict:
    """Pre-contract output (fm-saxml 0.6.x and earlier) -> 1.0: add the envelope, wrap the payloads."""
    head = {"schemaVersion": "1.0", "generator": None, "source": {}}
    if file_name == "entities.json":
        return {**head, **{k: v for k, v in data.items() if k not in head}}
    if file_name == "references.json":
        return {**head, "references": data}
    if file_name == "backlinks.json":
        return {**head, "backlinks": data}
    if file_name == "external-references.json":
        source = {k: v for k, v in (data.get("source") or {}).items() if k != "fileName"}  # an absolute path
        rest = {k: v for k, v in data.items() if k not in ("schemaVersion", "source")}
        return {**head, "source": source, **rest}
    raise ValueError(f"{file_name} is not a contract file ({', '.join(CONTRACT_FILES)})")


# major -> function taking that major's dict to the next major
UPGRADES: dict[int, Callable[[str, Any], dict]] = {
    0: upgrade_0_to_1,
}


def upgrade(file_name: str, data: Any, path: Optional[Path] = None) -> dict:
    """``data`` (one contract file, parsed) brought up to the current major version."""
    current = CONTRACT_VERSION[0]
    major = file_version(data)[0]
    if major > current:
        where = f"{path}: " if path else ""
        raise ContractVersionError(
            f"{where}docs written by schema {major}.x; this fm-saxml reads up to {current}.x — upgrade fm-saxml"
        )
    while major < current:
        data = UPGRADES[major](file_name, data)
        major += 1
    return data


def read_contract_file(path: Path):
    """Parse, upgrade and validate one contract file; returns its model from ``contract_models``."""
    from .contract_models import DOC_MODELS

    path = Path(path)
    if path.name not in DOC_MODELS:
        raise ValueError(f"{path.name} is not a contract file ({', '.join(CONTRACT_FILES)})")
    data = upgrade(path.name, orjson.loads(path.read_bytes()), path)
    return DOC_MODELS[path.name].model_validate(data)
