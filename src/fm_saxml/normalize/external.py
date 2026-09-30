"""Describe references that point into other files of a multi-file solution.

An ``ExternalTarget`` keeps everything the export knows about the far end
(data source, table occurrence, ids/UUIDs), so a later run that also has the
sister file's export can resolve the reference exactly.
"""

from __future__ import annotations

from typing import Optional

from ..model.document_model import DocumentModel
from ..model.entities import TableOccurrenceEntity
from ..model.references import ExternalTarget


class ExternalTargets:
    """Builds ExternalTarget records from the model's external TOs and data source catalog."""

    def __init__(self, model: DocumentModel) -> None:
        self._sources = {ds.name.casefold(): ds for ds in model.external_data_sources}
        self._tos: dict[str, TableOccurrenceEntity] = {
            to.name.casefold(): to
            for to in model.entities.table_occurrences.values()
            if to.external_data_source
        }

    def to_entity(self, to_name: Optional[str]) -> Optional[TableOccurrenceEntity]:
        """The External TO called ``to_name``, or None if it is local / unknown."""
        return self._tos.get((to_name or "").strip().casefold())

    def data_source_of(self, to_name: Optional[str]) -> Optional[str]:
        to = self.to_entity(to_name)
        return to.external_data_source if to else None

    def _source_fields(self, name: str, ds_id: Optional[str] = None, ds_uuid: Optional[str] = None) -> dict:
        cat = self._sources.get(name.casefold())
        return {
            "dataSource": name,
            "dataSourceId": ds_id or (cat.fmp_id if cat else None),
            "dataSourceUuid": ds_uuid or (cat.uuid if cat else None),
        }

    def field(
        self, to_name: Optional[str], field_name: str,
        fmp_id: Optional[str] = None, uuid: Optional[str] = None,
    ) -> Optional[ExternalTarget]:
        """Target for ``TO::field`` when TO is an external table occurrence, else None."""
        to = self.to_entity(to_name)
        if to is None or not field_name:
            return None
        return ExternalTarget(
            **self._source_fields(to.external_data_source, to.external_data_source_id, to.external_data_source_uuid),
            targetType="field",
            name=field_name,
            fmpId=fmp_id or None,
            uuid=uuid or None,
            tableOccurrence=to.name,
            baseTable=to.external_base_table,
            baseTableId=to.external_base_table_id,
            baseTableUuid=to.external_base_table_uuid,
        )

    def script(
        self, data_source: Optional[str], name: str,
        fmp_id: Optional[str] = None, uuid: Optional[str] = None,
    ) -> Optional[ExternalTarget]:
        """Target for a Perform Script "from file" step, else None (local script)."""
        if not data_source:
            return None
        return ExternalTarget(
            **self._source_fields(data_source),
            targetType="script", name=name, fmpId=fmp_id or None, uuid=uuid or None,
        )

    def layout(
        self, via_to: Optional[str], name: str,
        fmp_id: Optional[str] = None, uuid: Optional[str] = None,
    ) -> Optional[ExternalTarget]:
        """Target for a layout reached via an external TO (Go to Related Record), else None."""
        to = self.to_entity(via_to)
        if to is None:
            return None
        return ExternalTarget(
            **self._source_fields(to.external_data_source, to.external_data_source_id, to.external_data_source_uuid),
            targetType="layout", name=name, fmpId=fmp_id or None, uuid=uuid or None,
            tableOccurrence=to.name,
            baseTable=to.external_base_table,
            baseTableId=to.external_base_table_id,
            baseTableUuid=to.external_base_table_uuid,
        )
