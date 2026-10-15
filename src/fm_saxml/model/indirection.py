"""Indirection: places that name a field, script, layout, ... in a string.

FileMaker stores a direct reference (a field in a calc, the script of a Perform Script
step) by internal ID and updates it on rename. A *name* inside a string is not updated:
``GetField ( "Invoice::Total" )``, ``Set Field By Name [ $target ]``, ``Perform Script
[ By name: $callback ]``, ``Go to Object [ "btnSave" ]``, an ``ExecuteSQL`` query.
Each such place is an :class:`IndirectionSite`; ``analyze/indirection.py`` builds them.

Classes (see handling_indirection.md):

* ``A``  safe capture: the name comes from a real reference (``GetFieldName ( T::f )``,
  ``Get ( ScriptName )``), so it follows a rename.
* ``A'`` ID-based: resolved by internal ID (``getScriptName ( 387 )``, FileMaker_Fields
  by FieldID). Survives a rename, not a delete-and-recreate.
* ``B``  hardcoded: the name is a string literal right there. Breaks on rename.
* ``C``  dynamic: built from variables, script parameters or patterns we could trace.
* ``D``  opaque: the name comes from data (field contents, records, an API mapping).
* ``E``  broken: names something that does not exist (or ``<Field Missing>``).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

IndirectionClass = Literal["A", "A'", "B", "C", "D", "E"]

# Where a candidate's name came from. "literal" names break on rename; the rest follow it.
CandidateOrigin = Literal["literal", "capture", "self", "id", "pattern"]

CLASS_LABELS: dict[str, str] = {
    "A": "Safe capture",
    "A'": "ID-based",
    "B": "Hardcoded name",
    "C": "Dynamic (traced)",
    "D": "Opaque (from data)",
    "E": "Broken",
}


class IndirectCandidate(BaseModel):
    """An entity a site may name, and why we think so."""

    target_doc_id: str = Field(alias="targetDocId")
    target_entity_type: str = Field(alias="targetEntityType")
    name: str                             # the name (or pattern) that matched
    origin: CandidateOrigin
    confidence: Literal["parsed", "inferred"] = "parsed"
    evidence: list[str] = []              # how the name reached the site, nearest first

    model_config = ConfigDict(populate_by_name=True)

    @property
    def breaks_on_rename(self) -> bool:
        return self.origin in ("literal", "pattern")


class IndirectionSite(BaseModel):
    """One place a name is consumed: a sink function's argument or a by-name step target."""

    doc_id: str = Field(alias="docId")                       # "<source docId>#ind<n>"
    source_doc_id: str = Field(alias="sourceDocId")          # script step, field, layout object, CF ...
    source_entity_type: str = Field(alias="sourceEntityType")
    script_doc_id: Optional[str] = Field(None, alias="scriptDocId")
    step: Optional[int] = None                               # 1-based step number
    role: Optional[str] = None                               # calc role, or the step name
    sink: str                                                # GetField, Set Field By Name, ...
    name_kind: str = Field(alias="nameKind")                 # field | script | layout | tableOccurrence | ...
    expression: str                                          # the argument as written (scrubbed text)
    klass: IndirectionClass = Field(alias="class")
    names: list[str] = []                                    # every name / pattern the expression can produce
    note: Optional[str] = None
    candidates: list[IndirectCandidate] = []

    model_config = ConfigDict(populate_by_name=True)
