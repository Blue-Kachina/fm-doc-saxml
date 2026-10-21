"""The published JSON contract: the files other tools may read from a docs folder.

Every output root has a ``docs.json`` catalog (``ROOT_CATALOG``) saying whether it
holds one file's docs or a batch, and where each file's docs are. Four files then
describe each FileMaker file. They all share one version:

* ``entities.json``             every entity collection, ``{docId: entity}``, plus
                                ``fileOptions`` and ``graphNotes``
* ``references.json``           ``references``: the typed source -> target graph
* ``backlinks.json``            ``backlinks``: ``{targetDocId: [reference, ...]}``
* ``external-references.json``  ``dataSources``, ``externalTableOccurrences``, ``references``

Each is a JSON object that starts with the same envelope (``envelope``):
``schemaVersion``, ``generator`` and ``source``. ``source`` never holds a path on
this machine, and no file holds a timestamp, so building the same export twice
gives byte-identical files.

``model.json`` is not part of the contract: it is this tool's own save format and
keeps its own ``SCHEMA_VERSION`` (``model/document_model.py``).

Version policy: a minor version adds keys or collections (readers ignore what they
don't know); a major version renames, removes or reshapes something.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:
    from .model.document_model import DocumentModel

CONTRACT_VERSION: tuple[int, int] = (1, 0)
CONTRACT_FILES = ("entities.json", "references.json", "backlinks.json", "external-references.json")
# At the root of every output folder (one file's docs, or a batch): what it holds. Same version.
ROOT_CATALOG = "docs.json"
# Top-level keys every contract file starts with. In entities.json they sit next to the
# collections, so no collection may use one of these names.
ENVELOPE_KEYS = ("schemaVersion", "generator", "source")
GENERATOR_NAME = "fm-saxml-converter"


def parse_version(text: str) -> tuple[int, ...]:
    """``"1.0"`` -> ``(1, 0)``, ``"0.5.0"`` -> ``(0, 5, 0)``. Compare the tuples, never the strings.

    Raises ValueError for anything that isn't dot-separated whole numbers.
    """
    parts = str(text).strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a version number: {text!r}")
    return tuple(int(p) for p in parts)


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in version)


def envelope(model: "DocumentModel") -> dict:
    """The keys every contract file starts with: version, what wrote it, which file it describes."""
    src = model.source
    return {
        "schemaVersion": format_version(CONTRACT_VERSION),
        "generator": {"name": GENERATOR_NAME, "version": __version__},
        "source": {
            "fmpFileName": src.fmp_file_name,
            "fileUuid": src.file_uuid,
            "scope": src.scope,
            "fileMakerVersion": src.file_maker_version,
            "saxmlVersion": src.saxml_version,
        },
    }
