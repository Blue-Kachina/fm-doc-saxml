"""Main normalization pipeline — converts RawModel into DocumentModel."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..parser.saxml_reader import RawModel
from ..model.document_model import DocumentModel, SourceInfo, SolutionInfo, EntityMaps, Warning
from ..model.entities import (
    TableEntity,
    FieldEntity,
    TableOccurrenceEntity,
    RelationshipEntity,
    RelationshipPredicate,
    RelationshipOptions,
    LayoutEntity,
    LayoutObjectEntity,
    LayoutObjectBounds,
    ScriptStepEntity,
    StepCalculation,
    EntityCalculation,
    ScriptTriggerInfo,
    ScriptEntity,
    PrivilegeItem,
    PrivilegeCategory,
    PortalOptions,
    LayoutPart,
    GraphRect,
    SortField,
    RelationshipSide,
    CustomFunctionEntity,
    ValueListEntity,
    PrivilegeSetEntity,
    AccountEntity,
    ModificationInfo,
    ExtendedPrivilegeEntity,
    CustomMenuEntity,
    CustomMenuItem,
    CustomMenuSetEntity,
    ThemeEntity,
    FileReferenceEntity,
    StorageOptions,
    AutoEnterOptions,
    ValidationOptions,
    SourceXmlInfo,
)
from .ids import (
    table_doc_id,
    field_doc_id,
    to_doc_id,
    relationship_doc_id,
    layout_doc_id,
    layout_object_doc_id,
    script_doc_id,
    script_step_doc_id,
    custom_function_doc_id,
    value_list_doc_id,
    privilege_set_doc_id,
    account_doc_id,
    extended_privilege_doc_id,
    custom_menu_doc_id,
    custom_menu_set_doc_id,
    theme_doc_id,
    file_reference_doc_id,
    file_scope,
)
from .names import normalize_name, qualified_name
from .variables import build_variables
from .field_resolver import build_field_resolver, resolve_field_or_fallback
from .external import ExternalTargets
from .calc_refs import CalcRefResolver, chunk_ref_models
from ..model.document_model import ExternalDataSource, FileOptions, GraphNote, XmlInventory
from ..model.step_text import step_text


def normalize(
    raw: RawModel,
    source_file: str = "",
    source_path: Optional[Path] = None,
) -> DocumentModel:
    """Convert a RawModel into a fully normalized DocumentModel.

    ``source_path``, if provided, is used to capture the modification timestamp
    of the source XML file (rendered as "XML Created At" in the summary).
    """
    source_modified_at = _extract_mtime(source_path)

    source = SourceInfo(
        fileName=source_file or raw.file_name,
        fileMakerVersion=raw.filemaker_version,
        generatedAt=datetime.now(timezone.utc),
        sourceModifiedAt=source_modified_at,
        fmpFileName=raw.fmp_file_name or None,
        fileUuid=raw.file_uuid or None,
        scope=file_scope(raw.file_uuid, raw.fmp_file_name, Path(source_file or raw.file_name).name),
    )
    solution = SolutionInfo(name=raw.solution_name or source_file or "Unknown Solution")
    entities = EntityMaps()
    model = DocumentModel(source=source, solution=solution, entities=entities)

    model.external_data_sources = [
        ExternalDataSource(
            name=ds.get("name", ""), fmpId=ds.get("id") or None, uuid=ds.get("uuid"),
            type=ds.get("type") or "FileMaker", paths=ds.get("paths", []),
        )
        for ds in raw.external_data_sources
    ]

    # Propagate parse-time warnings
    for w in raw.parse_warnings:
        model.add_warning("PARSE_WARNING", w)

    _index_script_ids(raw, model)  # before anything links to a script
    _normalize_tables(raw, model)
    _normalize_fields(raw, model)
    _normalize_table_occurrences(raw, model)
    _normalize_relationships(raw, model)
    _normalize_graph_notes(raw, model)
    _resolve_lookups(model)  # needs table occurrences
    _normalize_value_lists(raw, model)  # before layouts/scripts: their calcs reference value lists by name
    _normalize_layouts(raw, model)
    _normalize_layout_objects(raw, model)
    _normalize_scripts(raw, model)
    _normalize_custom_functions(raw, model)
    _normalize_privilege_sets(raw, model)
    _normalize_accounts(raw, model)
    _normalize_extended_privileges(raw, model)
    _normalize_custom_menus(raw, model)
    _normalize_custom_menu_sets(raw, model)
    _normalize_themes(raw, model)
    _normalize_file_references(raw, model)
    _normalize_file_options(raw, model)
    if raw.coverage is not None:
        model.coverage_inventory = XmlInventory.model_validate(raw.coverage)
    build_variables(model)  # needs scripts and every entity's calculations

    return model


def _resolve_lookups(model: DocumentModel) -> None:
    resolve_field = build_field_resolver(model)
    ext = ExternalTargets(model)
    for f in model.entities.fields.values():
        ae = f.auto_enter
        if ae is None or not ae.lookup_field:
            continue
        ae.lookup_external = ext.field(ae.lookup_table_occurrence, ae.lookup_field)
        ae.lookup_field_doc_id = (
            ae.lookup_external.scoped_doc_id if ae.lookup_external
            else resolve_field_or_fallback(resolve_field, ae.lookup_table_occurrence or "", ae.lookup_field)
        )


def _normalize_graph_notes(raw: RawModel, model: DocumentModel) -> None:
    tos = [to for to in model.entities.table_occurrences.values() if to.graph_bounds is not None]
    notes = [GraphRect(**n["bounds"]) if n.get("bounds") else None for n in raw.graph_notes]

    def same_column(a: GraphRect, b: GraphRect) -> bool:
        return a.left < b.right and b.left < a.right

    for note, bounds in zip(raw.graph_notes, notes):
        covered, below = [], []
        if bounds is not None:
            covered = sorted(to.doc_id for to in tos if bounds.overlaps(to.graph_bounds))
            stop = min((n.top for n in notes if n is not None and n is not bounds
                        and n.top >= bounds.bottom and same_column(n, bounds)), default=float("inf"))
            below = [to.doc_id for to in sorted(tos, key=lambda t: (t.graph_bounds.top, t.graph_bounds.left))
                     if to.doc_id not in covered and bounds.bottom <= to.graph_bounds.top < stop
                     and same_column(to.graph_bounds, bounds)]
        model.graph_notes.append(GraphNote(text=note.get("text") or "", bounds=bounds,
                                           tableOccurrenceDocIds=covered, belowDocIds=below))


def _normalize_file_options(raw: RawModel, model: DocumentModel) -> None:
    fo = raw.file_options
    if not fo:
        return
    layout = fo.get("default_layout")
    model.file_options = FileOptions(
        defaultLayout=model.local_layout_doc_id(layout["name"], layout.get("id")) if layout else None,
        minimumVersion=fo.get("minimum_version"),
        loginType=fo.get("login_type"),
        loginAccount=fo.get("login_account"),
        encrypted=fo.get("encrypted"),
        allowSavePassword=fo.get("allow_save_password"),
        requireMobilePassword=fo.get("require_mobile_password"),
        showSignInFields=fo.get("show_sign_in_fields"),
        hideFromClientSharing=fo.get("hide_from_client_sharing"),
        hideFromWebDirectSharing=fo.get("hide_from_webdirect_sharing"),
        useDefaultFields=fo.get("use_default_fields"),
        defaultMenuSet=fo.get("default_menu_set"),
        scriptTriggers=_script_triggers(fo.get("script_triggers"), ExternalTargets(model), model),
    )


def _index_script_ids(raw: RawModel, model: DocumentModel) -> None:
    """FileMaker id -> docId for every script and layout. A name used twice gets a docId with the id."""
    taken_layouts: set[str] = set()
    for lay in raw.layouts:
        name = normalize_name(lay.get("name", ""))
        if not name:
            continue
        doc_id = layout_doc_id(name)
        if doc_id in taken_layouts:
            doc_id = layout_doc_id(f"{name} (#{lay.get('id', '')})")
        taken_layouts.add(doc_id)
        if lay.get("id"):
            model._layout_doc_ids[str(lay["id"])] = doc_id
    taken: set[str] = set()
    for s in raw.scripts:
        name = normalize_name(s.get("name", ""))
        if not name:
            continue
        doc_id = script_doc_id(name)
        if doc_id in taken:
            doc_id = script_doc_id(f"{name} (#{s.get('id', '')})")
        taken.add(doc_id)
        if s.get("id"):
            model._script_doc_ids[str(s["id"])] = doc_id


def _extract_mtime(source_path: Optional[Path]) -> Optional[datetime]:
    """Return the mtime of ``source_path`` as a UTC datetime, or None."""
    if not source_path:
        return None
    try:
        path = Path(source_path)
        if not path.exists():
            return None
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def _normalize_tables(raw: RawModel, model: DocumentModel) -> None:
    for t in raw.tables:
        name = normalize_name(t.get("name", ""))
        if not name:
            model.add_warning("MISSING_NAME", "Table record missing name — skipped", detail=str(t))
            continue
        doc_id = table_doc_id(name)
        entity = TableEntity(
            docId=doc_id,
            name=name,
            fmpId=str(t.get("id", "")),
            uuid=t.get("uuid"),
            comment=t.get("comment"),
            modified=ModificationInfo.model_validate(t["modified"]) if t.get("modified") else None,
            sourceXml=SourceXmlInfo(path=t.get("source_xml_path", "")) if t.get("source_xml_path") else None,
        )
        model.entities.tables[doc_id] = entity


def _entity_calcs(
    raw_calcs: Optional[list[dict]],
    fallbacks: list[tuple[str, Optional[str]]] = (),
) -> list[EntityCalculation]:
    """Raw ``{"role", "text", "references"}`` calcs -> models.

    ``fallbacks`` are ``(role, text)`` pairs used when the extractor found none, e.g. v1
    exports (or hand-built raw dicts) that only carry a calc's text.
    """
    if not raw_calcs:
        raw_calcs = [{"role": role, "text": text} for role, text in fallbacks if text]
    return [
        EntityCalculation(role=c["role"], text=c["text"], chunkRefs=chunk_ref_models(c.get("references")))
        for c in raw_calcs
    ]


def _script_triggers(raw_triggers: Optional[list[dict]], ext: ExternalTargets,
                     model: DocumentModel) -> list[ScriptTriggerInfo]:
    triggers = []
    for t in raw_triggers or []:
        sref = t["script"]
        s_ext = ext.script(sref.get("data_source"), sref["name"], sref.get("id"), sref.get("uuid"))
        triggers.append(ScriptTriggerInfo(
            event=t.get("event") or "",
            scriptDocId=s_ext.scoped_doc_id if s_ext else model.local_script_doc_id(sref["name"], sref.get("id")),
            scriptExternal=s_ext,
        ))
    return triggers


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def _normalize_fields(raw: RawModel, model: DocumentModel) -> None:
    for f in raw.fields:
        table_name = normalize_name(f.get("table_name", ""))
        name = normalize_name(f.get("name", ""))
        if not name or not table_name:
            model.add_warning("MISSING_NAME", f"Field record missing name or table — skipped", detail=str(f))
            continue

        table_did = table_doc_id(table_name)
        doc_id = field_doc_id(table_name, name)

        storage_raw = f.get("storage", {})
        storage = StorageOptions(**{
            "global": storage_raw.get("global", False),
            "indexed": storage_raw.get("indexed", False),
            "index": storage_raw.get("index", "None"),
            "autoIndex": storage_raw.get("autoIndex", False),
            "maxRepeat": storage_raw.get("maxRepeat", 1),
            "stored": storage_raw.get("stored"),
            "externalStorage": (storage_raw.get("external_storage") or {}).get("type"),
            "externalStorageDirectory": (storage_raw.get("external_storage") or {}).get("base_directory"),
        })

        auto_enter = None
        ae_raw = f.get("auto_enter")
        if ae_raw:
            auto_enter = AutoEnterOptions(
                type=ae_raw.get("type", "none"),
                value=ae_raw.get("value"),
                calculation=ae_raw.get("calculation"),
                no_modify_auto_enter=ae_raw.get("no_modify_auto_enter", False),
                overwriteExisting=ae_raw.get("overwrite_existing"),
                serialIncrement=(ae_raw.get("serial") or {}).get("increment"),
                serialGenerate=(ae_raw.get("serial") or {}).get("generate"),
                lookupTableOccurrence=(ae_raw.get("lookup") or {}).get("table_name"),
                lookupField=(ae_raw.get("lookup") or {}).get("field_name"),
                lookupContext=(ae_raw.get("lookup") or {}).get("context"),
                lookupDontCopyIfEmpty=(ae_raw.get("lookup") or {}).get("dont_copy_if_empty"),
                lookupNoMatch=(ae_raw.get("lookup") or {}).get("no_match"),
                lookupNoMatchValue=(ae_raw.get("lookup") or {}).get("no_match_value"),
            )

        validation = None
        val_raw = f.get("validation")
        if val_raw:
            validation = ValidationOptions(
                required=val_raw.get("required", False),
                not_empty=val_raw.get("not_empty", False),
                unique=val_raw.get("unique", False),
                max_characters=val_raw.get("max_characters"),
                message=val_raw.get("message"),
                valueListDocId=(
                    value_list_doc_id(normalize_name(val_raw["value_list"]))
                    if val_raw.get("value_list") else None
                ),
                existing=val_raw.get("existing", False),
                strictType=val_raw.get("strict_type"),
                hasCalculation=val_raw.get("has_calculation", False),
                hasMessageCalculation=val_raw.get("has_message_calculation", False),
                alwaysValidate=val_raw.get("always_validate"),
                range=val_raw.get("range"),
                validateOn=val_raw.get("validate"),
                allowOverride=val_raw.get("allow_override"),
                other=val_raw.get("other") or {},
            )

        summary_field_did = None
        sf_raw = f.get("summary_field")
        if sf_raw and sf_raw.get("name"):
            # A summary field always aggregates a field on its own table.
            summary_field_did = field_doc_id(normalize_name(sf_raw.get("table") or table_name), normalize_name(sf_raw["name"]))

        entity = FieldEntity(
            docId=doc_id,
            name=name,
            qualifiedName=qualified_name(table_name, name),
            baseTableDocId=table_did,
            dataType=f.get("data_type", "Text"),
            fieldType=f.get("field_type", "Normal"),
            fmpId=str(f.get("id", "")),
            uuid=f.get("uuid"),
            comment=f.get("comment"),
            calculation=f.get("calculation"),
            autoEnter=auto_enter,
            validation=validation,
            storage=storage,
            summaryFieldDocId=summary_field_did,
            annotation=f.get("annotation"),
            summaryOperation=(f.get("summary") or {}).get("operation"),
            summaryRestartEachGroup=(f.get("summary") or {}).get("restart_each_group"),
            summaryRepetitions=(f.get("summary") or {}).get("summarize_repetition"),
            alwaysEvaluate=f.get("always_evaluate"),
            calculations=_entity_calcs(f.get("calculations"), [
                ("calculation", f.get("calculation")),
                ("autoEnter", (ae_raw or {}).get("calculation")),
            ]),
            modified=ModificationInfo.model_validate(f["modified"]) if f.get("modified") else None,
            sourceXml=SourceXmlInfo(path=f.get("source_xml_path", "")) if f.get("source_xml_path") else None,
        )

        model.entities.fields[doc_id] = entity

        # Register field on its parent table
        table = model.entities.tables.get(table_did)
        if table is not None and doc_id not in table.fields:
            table.fields.append(doc_id)
        elif table is None:
            model.add_warning(
                "ORPHAN_FIELD",
                f"Field '{qualified_name(table_name, name)}' references table '{table_name}' which was not found",
                entity_doc_id=doc_id,
            )


# ---------------------------------------------------------------------------
# Table Occurrences
# ---------------------------------------------------------------------------

def _normalize_table_occurrences(raw: RawModel, model: DocumentModel) -> None:
    # Build a lookup from table fmpId → table docId
    table_id_map = {t.fmp_id: t.doc_id for t in model.entities.tables.values()}
    table_name_map = {t.name: t.doc_id for t in model.entities.tables.values()}

    for to in raw.table_occurrences:
        name = normalize_name(to.get("name", ""))
        if not name:
            continue
        doc_id = to_doc_id(name)
        base_table_id = str(to.get("base_table_id", ""))
        external_source = to.get("external_data_source")
        if external_source:
            # Base table lives in another file; ids/names must not match local tables
            base_table_doc_id = ""
        else:
            base_table_doc_id = table_id_map.get(base_table_id) or table_name_map.get(name, "")

        entity = TableOccurrenceEntity(
            docId=doc_id,
            name=name,
            baseTableDocId=base_table_doc_id,
            externalDataSource=external_source,
            externalDataSourceId=to.get("external_data_source_id"),
            externalDataSourceUuid=to.get("external_data_source_uuid"),
            externalBaseTable=to.get("external_base_table"),
            externalBaseTableId=to.get("external_base_table_id"),
            externalBaseTableUuid=to.get("external_base_table_uuid"),
            fmpId=str(to.get("id", "")),
            uuid=to.get("uuid"),
            graphBounds=to.get("graph_bounds"),
            collapsed=to.get("collapsed"),
            modified=ModificationInfo.model_validate(to["modified"]) if to.get("modified") else None,
            sourceXml=SourceXmlInfo(path=to.get("source_xml_path", "")) if to.get("source_xml_path") else None,
        )
        model.entities.table_occurrences[doc_id] = entity

        # Back-register on the base table
        if base_table_doc_id and base_table_doc_id in model.entities.tables:
            table = model.entities.tables[base_table_doc_id]
            if doc_id not in table.table_occurrences:
                table.table_occurrences.append(doc_id)


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def _normalize_relationships(raw: RawModel, model: DocumentModel) -> None:
    to_id_map = {to.fmp_id: to.doc_id for to in model.entities.table_occurrences.values()}
    to_name_map = {to.name: to.doc_id for to in model.entities.table_occurrences.values()}
    resolve_field = build_field_resolver(model)
    ext = ExternalTargets(model)

    for rel in raw.relationships:
        name = normalize_name(rel.get("name", ""))
        if not name:
            # v2: relationships have no name attribute — synthesize from TO names
            left_n = rel.get("left_table_name", "")
            right_n = rel.get("right_table_name", "")
            if left_n and right_n:
                name = f"{left_n}__{right_n}"
            elif left_n or right_n:
                name = left_n or right_n
            else:
                name = f"rel_{rel.get('id', '')}"
        if not name:
            continue
        doc_id = relationship_doc_id(name)

        left_id = str(rel.get("left_table_id", ""))
        right_id = str(rel.get("right_table_id", ""))
        left_name = rel.get("left_table_name", "")
        right_name = rel.get("right_table_name", "")

        left_to_doc = to_id_map.get(left_id) or to_name_map.get(left_name, to_doc_id(left_name))
        right_to_doc = to_id_map.get(right_id) or to_name_map.get(right_name, to_doc_id(right_name))

        predicates = []
        for pred in rel.get("predicates", []):
            left_ext = ext.field(pred.get("left_table_name"), pred.get("left_field_name", ""),
                                 pred.get("left_field_id"), pred.get("left_field_uuid"))
            right_ext = ext.field(pred.get("right_table_name"), pred.get("right_field_name", ""),
                                  pred.get("right_field_id"), pred.get("right_field_uuid"))
            left_field_doc = left_ext.scoped_doc_id if left_ext else _resolve_pred_field(pred, "left", resolve_field)
            right_field_doc = right_ext.scoped_doc_id if right_ext else _resolve_pred_field(pred, "right", resolve_field)
            predicates.append(RelationshipPredicate(
                leftFieldDocId=left_field_doc,
                operator=pred.get("operator", "="),
                rightFieldDocId=right_field_doc,
                leftExternal=left_ext,
                rightExternal=right_ext,
            ))

        options = RelationshipOptions(
            allowCreateRelated=rel.get("allow_create_related", False),
            deleteRelated=rel.get("delete_related", False),
            sortRelated=rel.get("sort_related", False),
            left=_relationship_side(rel.get("left"), resolve_field, ext),
            right=_relationship_side(rel.get("right"), resolve_field, ext),
        )

        entity = RelationshipEntity(
            docId=doc_id,
            name=name,
            fmpId=str(rel.get("id", "")),
            leftTableOccurrenceDocId=left_to_doc,
            rightTableOccurrenceDocId=right_to_doc,
            predicates=predicates,
            options=options,
            modified=ModificationInfo.model_validate(rel["modified"]) if rel.get("modified") else None,
            sourceXml=SourceXmlInfo(path=rel.get("source_xml_path", "")) if rel.get("source_xml_path") else None,
        )
        model.entities.relationships[doc_id] = entity

        # Register relationship on TOs
        for to_doc in [left_to_doc, right_to_doc]:
            to_entity = model.entities.table_occurrences.get(to_doc)
            if to_entity and doc_id not in to_entity.relationships:
                to_entity.relationships.append(doc_id)


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_fields(raw_sort: Optional[list[dict]], resolve_field, ext: ExternalTargets) -> list[SortField]:
    out = []
    for sf in raw_sort or []:
        f_ext = ext.field(sf.get("table_name"), sf.get("field_name", ""), sf.get("field_id"), sf.get("field_uuid"))
        field_did = (f_ext.scoped_doc_id if f_ext
                     else resolve_field_or_fallback(resolve_field, sf.get("table_name", ""), sf.get("field_name", "")))
        out.append(SortField(
            fieldDocId=field_did,
            order=sf.get("order") or "Ascending",
            valueListDocId=value_list_doc_id(normalize_name(sf["value_list"])) if sf.get("value_list") else None,
            external=f_ext,
        ))
    return out


def _relationship_side(side: Optional[dict], resolve_field, ext: ExternalTargets) -> Optional[RelationshipSide]:
    if side is None:
        return None
    return RelationshipSide(
        allowCreate=side.get("allow_create", False),
        delete=side.get("delete", False),
        sort=_sort_fields(side.get("sort"), resolve_field, ext),
    )


def _resolve_pred_field(pred: dict, side: str, resolve_field) -> str:
    field_name = pred.get(f"{side}_field_name", "")
    table_name = pred.get(f"{side}_table_name", "")
    return resolve_field_or_fallback(resolve_field, table_name, field_name) or ""


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------

def _normalize_layouts(raw: RawModel, model: DocumentModel) -> None:
    to_id_map = {to.fmp_id: to.doc_id for to in model.entities.table_occurrences.values()}
    to_name_map = {to.name: to.doc_id for to in model.entities.table_occurrences.values()}
    # Also allow resolution by base table name matching
    base_to_map: dict[str, str] = {}
    for to in model.entities.table_occurrences.values():
        base_name = to.base_table_doc_id.split(":", 1)[1] if ":" in to.base_table_doc_id else ""
        if base_name and base_name not in base_to_map:
            base_to_map[base_name] = to.doc_id

    resolve_field = build_field_resolver(model)
    ext = ExternalTargets(model)

    for layout in raw.layouts:
        name = normalize_name(layout.get("name", ""))
        if not name:
            continue
        doc_id = model.local_layout_doc_id(name, layout.get("id"))
        if doc_id in model.entities.layouts:  # same name and no id to tell them apart
            doc_id = layout_doc_id(f"{name} (#{layout.get('id', '') or len(model.entities.layouts)})")

        to_id = str(layout.get("table_occurrence_id", ""))
        to_name = layout.get("table_occurrence_name", "")
        to_doc = (
            to_id_map.get(to_id)
            or to_name_map.get(to_name)
            or base_to_map.get(to_name)
            or (to_doc_id(to_name) if to_name else None)
        )

        # Collect field docIds from referenced fields list
        ref_field_doc_ids = []
        for ref in layout.get("referenced_fields", []):
            t = ref.get("table_name", "")
            fn = ref.get("field_name", "")
            if not fn:
                continue
            fd = resolve_field_or_fallback(resolve_field, t, fn) or field_doc_id(t, fn)
            if fd not in ref_field_doc_ids:
                ref_field_doc_ids.append(fd)

        entity = LayoutEntity(
            docId=doc_id,
            name=name,
            fmpId=str(layout.get("id", "")),
            uuid=layout.get("uuid"),
            baseTableOccurrenceDocId=to_doc,
            theme=layout.get("theme"),
            folderPath=layout.get("folder_path"),
            referencedFields=ref_field_doc_ids,
            menuSet=layout.get("menu_set"),
            parts=[
                LayoutPart(
                    type=p.get("type") or "",
                    name=p.get("name"),
                    height=p.get("height"),
                    breakFieldDocId=(
                        resolve_field_or_fallback(resolve_field, p["break_field"]["table_name"],
                                                  p["break_field"]["field_name"])
                        if p.get("break_field") else None
                    ),
                    objectCount=p.get("object_count", 0),
                )
                for p in layout.get("parts") or []
            ],
            scriptTriggers=_script_triggers(layout.get("script_triggers"), ext, model),
            calculations=_entity_calcs(layout.get("calculations")),
            modified=ModificationInfo.model_validate(layout["modified"]) if layout.get("modified") else None,
            sourceXml=SourceXmlInfo(path=layout.get("source_xml_path", "")) if layout.get("source_xml_path") else None,
        )
        model.entities.layouts[doc_id] = entity


# ---------------------------------------------------------------------------
# Layout Objects
# ---------------------------------------------------------------------------

def _normalize_layout_objects(raw: RawModel, model: DocumentModel) -> None:
    """Build LayoutObjectEntity instances from raw layout dicts.

    Also re-populates each layout's ``referenced_fields`` from the resolved
    layout-object field references (which gives us a more accurate count than
    the raw ``referenced_fields`` list).
    """
    resolve_field = build_field_resolver(model)
    to_id_map = {to.fmp_id: to.doc_id for to in model.entities.table_occurrences.values()}
    to_name_map = {to.name: to.doc_id for to in model.entities.table_occurrences.values()}
    # name -> docId, plus "#<FileMaker id>" -> docId (two layouts can share a name)
    layout_name_map = {ly.name: ly.doc_id for ly in model.entities.layouts.values()}
    layout_name_map.update({f"#{ly.fmp_id}": ly.doc_id for ly in model.entities.layouts.values() if ly.fmp_id})
    ext = ExternalTargets(model)

    for raw_layout in raw.layouts:
        layout_name = normalize_name(raw_layout.get("name", ""))
        if not layout_name:
            continue
        layout_did = model.local_layout_doc_id(layout_name, raw_layout.get("id"))
        layout_key = layout_did.split(":", 1)[1]  # the layout's name, or "name (#id)" for a duplicate
        layout_entity = model.entities.layouts.get(layout_did)
        if layout_entity is None:
            continue

        objects = raw_layout.get("layout_objects", []) or []
        object_doc_ids: list[str] = []
        # Track field doc IDs derived from real layout objects so we can
        # overwrite the layout's referenced_fields with a verified set.
        derived_field_dids: list[str] = []
        seen_fields: set[str] = set()

        for obj in objects:
            obj_id = str(obj.get("id", "") or "")
            fallback_idx = int(obj.get("fallback_index", 0) or 0)
            doc_id = layout_object_doc_id(layout_key, obj_id, fallback_idx)

            bounds_raw = obj.get("bounds") or {}
            bounds = (
                LayoutObjectBounds(**bounds_raw)
                if isinstance(bounds_raw, dict) and bounds_raw
                else None
            )

            field_did: str | None = None
            field_external = None
            to_did: str | None = None
            f = obj.get("field")
            if f:
                fn = f.get("field_name", "")
                tn = f.get("table_name", "")
                if fn:
                    field_external = ext.field(tn, fn, f.get("field_id"), f.get("field_uuid"))
                    field_did = (
                        field_external.scoped_doc_id if field_external
                        else resolve_field_or_fallback(resolve_field, tn, fn)
                    )
                fm_to_id = str(f.get("to_id", "") or "")
                if fm_to_id and fm_to_id in to_id_map:
                    to_did = to_id_map[fm_to_id]
                elif tn and tn in to_name_map:
                    to_did = to_name_map[tn]

            # A portal shows records of its own table occurrence, sorted by its sort fields
            portal = obj.get("portal")
            if portal:
                to_did = (to_id_map.get(str(portal.get("to_id") or ""))
                          or to_name_map.get(portal.get("to_name") or "") or to_did)

            # Single-step button: its layout / fields / value lists; portal sort fields
            obj_refs: list[dict] = []
            if obj.get("button_step"):
                obj_refs += _step_target_refs(obj["button_step"], "buttonAction", resolve_field, ext, layout_name_map)
            if portal:
                sort_step = {"field_refs": [{"name": sf["field_name"], "table": sf["table_name"],
                                             "id": sf["field_id"], "uuid": sf["field_uuid"]}
                                            for sf in portal.get("sort_fields", [])]}
                obj_refs += _step_target_refs(sort_step, "portalSort", resolve_field, ext, layout_name_map)

            # Button-triggered script. Scripts aren't normalized yet at this
            # point in the pipeline, so there's no name->doc_id map to check
            # against — script_doc_id() is a pure function of the normalized
            # name, so it produces the same doc_id the real script will get.
            button_script_did: str | None = None
            button_script_external = None
            bs = obj.get("button_script")
            if bs and bs.get("name"):
                button_script_external = ext.script(bs.get("data_source"), bs["name"], bs.get("id"), bs.get("uuid"))
                button_script_did = (
                    button_script_external.scoped_doc_id if button_script_external
                    else model.local_script_doc_id(bs["name"], bs.get("id"))
                )

            entity = LayoutObjectEntity(
                docId=doc_id,
                layoutDocId=layout_did,
                part=obj.get("part"),
                objectId=obj_id,
                objectType=obj.get("type", "") or "",
                kind=obj.get("kind"),
                name=obj.get("name", "") or "",
                uuid=obj.get("uuid"),
                bounds=bounds,
                fieldDocId=field_did,
                tableOccurrenceDocId=to_did,
                valueListDocId=(
                    value_list_doc_id(normalize_name(obj["value_list"]["name"]))
                    if obj.get("value_list") else None
                ),
                externalTarget=field_external,
                buttonScriptDocId=button_script_did,
                buttonScriptExternal=button_script_external,
                buttonStep=step_text(obj["button_step"]) if obj.get("button_step") else None,
                buttonKind=obj.get("button_kind"),
                parentObjectDocId=(
                    layout_object_doc_id(layout_key, str(obj["parent_id"])) if obj.get("parent_id") else None
                ),
                portal=PortalOptions(
                    initialRow=_int_or_none(portal.get("initial_row")),
                    rows=_int_or_none(portal.get("rows")),
                    sort=_sort_fields(portal.get("sort"), resolve_field, ext),
                ) if portal else None,
                scriptTriggers=_script_triggers(obj.get("script_triggers"), ext, model),
                calculations=_entity_calcs(obj.get("calculations")),
                references=obj_refs,
                rawText=obj.get("raw_text"),
                sourceXml=(
                    SourceXmlInfo(path=obj.get("source_xml_path", ""))
                    if obj.get("source_xml_path")
                    else None
                ),
            )
            model.entities.layout_objects[doc_id] = entity
            object_doc_ids.append(doc_id)

            if field_did and field_did not in seen_fields:
                seen_fields.add(field_did)
                derived_field_dids.append(field_did)

        layout_entity.layout_objects = object_doc_ids
        # Prefer the field set we just derived from real layout objects. If
        # none were found (e.g. nothing field-bound on this layout) leave the
        # existing referenced_fields list — which was populated from the same
        # source — alone.
        if derived_field_dids:
            layout_entity.referenced_fields = derived_field_dids


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def _ext(target) -> dict:
    """Step-reference marker: the target lives in another file; ``target`` is its ExternalTarget."""
    return {"external": target} if target else {}


def _normalize_scripts(raw: RawModel, model: DocumentModel) -> None:
    # name -> docId, plus "#<FileMaker id>" -> docId (two layouts can share a name)
    layout_name_map = {ly.name: ly.doc_id for ly in model.entities.layouts.values()}
    layout_name_map.update({f"#{ly.fmp_id}": ly.doc_id for ly in model.entities.layouts.values() if ly.fmp_id})
    script_name_map_prelim: dict[str, str] = {}

    # First pass — create script entities without step cross-references
    script_entities: list[tuple[dict, ScriptEntity]] = []
    for s in raw.scripts:
        name = normalize_name(s.get("name", ""))
        if not name:
            continue
        doc_id = model.local_script_doc_id(name, s.get("id"))
        if doc_id in model.entities.scripts:  # same name and no id to tell them apart
            doc_id = script_doc_id(f"{name} (#{s.get('id', '') or len(model.entities.scripts)})")
        entity = ScriptEntity(
            docId=doc_id,
            name=name,
            fmpId=str(s.get("id", "")),
            uuid=s.get("uuid"),
            folderPath=s.get("folder_path"),
            runWithFullAccess=(s.get("options") or {}).get("run_with_full_access"),
            showInMenu=(s.get("options") or {}).get("show_in_menu"),
            siriShortcut=(s.get("options") or {}).get("siri_shortcut"),
            modified=ModificationInfo.model_validate(s["modified"]) if s.get("modified") else None,
            sourceXml=SourceXmlInfo(path=s.get("source_xml_path", "")) if s.get("source_xml_path") else None,
        )
        model.entities.scripts[doc_id] = entity
        script_name_map_prelim[name] = doc_id
        script_entities.append((s, entity))

    # Second pass — process steps (now all script docIds are known)
    resolve_field = build_field_resolver(model)
    ext = ExternalTargets(model)
    calc_resolver = CalcRefResolver(model, resolve_field, ext)

    for s, script_entity in script_entities:
        step_doc_ids = []
        ref_fields: list[str] = []
        ref_layouts: list[str] = []
        ref_scripts: list[str] = []

        for raw_step in s.get("steps", []):
            step_doc = script_step_doc_id(script_entity.doc_id.split(":", 1)[1], raw_step.get("index", 0))
            calcs = raw_step.get("calculations")
            if calcs is None:  # raw step with only the joined calculation text
                calcs = [{"text": raw_step["calculation"]}] if raw_step.get("calculation") else []

            # The step's layout, fields and value lists
            step_refs = _step_target_refs(raw_step, "target", resolve_field, ext, layout_name_map)
            for r in step_refs:
                if r["kind"] == "layout" and r["targetDocId"] not in ref_layouts:
                    ref_layouts.append(r["targetDocId"])
                    script_entity.referenced_layouts.append(r["targetDocId"])
                elif r["kind"] == "field" and r["targetDocId"] not in ref_fields:
                    ref_fields.append(r["targetDocId"])
                    script_entity.referenced_fields.append(r["targetDocId"])

            # Fields / custom functions / value lists used inside the step's calculations
            for calc in calcs:
                for use in calc_resolver.uses(calc["text"], calc.get("references")):
                    kind, target = use.kind, use.target_doc_id
                    if any(r["kind"] == kind and r["targetDocId"] == target for r in step_refs):
                        continue
                    step_refs.append({"kind": kind, "targetDocId": target, "role": "calculation",
                                      "rawText": use.raw_text, "calculationPosition": calc.get("position"),
                                      **_ext(use.external)})
                    if kind == "field" and target not in ref_fields:
                        ref_fields.append(target)
                        script_entity.referenced_fields.append(target)

            # Script reference
            sr = raw_step.get("script_ref")
            if sr and sr.get("name"):
                sn = sr["name"]
                s_ext = ext.script(sr.get("data_source"), sn, sr.get("id"), sr.get("uuid"))  # "from file: X"
                if s_ext:
                    sd = s_ext.scoped_doc_id
                else:
                    sd = model.local_script_doc_id(sn, sr.get("id"))
                step_refs.append({"kind": "script", "targetDocId": sd, "role": "callee", **_ext(s_ext)})
                if sd not in ref_scripts:
                    ref_scripts.append(sd)
                    script_entity.referenced_scripts.append(sd)

            step_entity = ScriptStepEntity(
                docId=step_doc,
                scriptDocId=script_entity.doc_id,
                index=raw_step.get("index", 0),
                stepId=str(raw_step.get("step_type_id", "")),
                name=raw_step.get("name", ""),
                enabled=raw_step.get("enabled", True),
                rawText=raw_step.get("raw_text"),
                parameters={"variable": raw_step["variable"]} if raw_step.get("variable") else {},
                params=raw_step.get("params") or [],
                fmText=raw_step.get("fm_text"),
                calculations=[
                    StepCalculation(position=c.get("position"), parameter=c.get("parameter"),
                                    slot=c.get("slot"), text=c["text"])
                    for c in calcs
                ],
                references=step_refs,
            )
            model.entities.script_steps[step_doc] = step_entity
            step_doc_ids.append(step_doc)

        script_entity.steps = step_doc_ids


def _step_target_refs(
    step: dict,
    role: str,
    resolve_field,
    ext: ExternalTargets,
    layout_name_map: dict[str, str],
) -> list[dict]:
    """References a script step (or a single-step button's step) makes directly.

    Its target layout, fields and value lists — not what its calculations use.
    """
    refs: list[dict] = []

    lr = step.get("layout_ref")
    if lr and lr.get("name"):
        # Go to Related Record through an External TO -> layout is in the other file
        l_ext = ext.layout(lr.get("via_to"), lr["name"], lr.get("id"), lr.get("uuid"))
        ld = l_ext.scoped_doc_id if l_ext else (
            (layout_name_map.get(f"#{lr['id']}") if lr.get("id") else None)
            or layout_name_map.get(lr["name"]) or layout_doc_id(lr["name"])
        )
        refs.append({"kind": "layout", "targetDocId": ld, "role": role, **_ext(l_ext)})

    for fr in step.get("field_refs", []):
        fn = fr.get("name", "")
        tn = fr.get("table", "")
        if fn:
            f_ext = ext.field(tn, fn, fr.get("id"), fr.get("uuid"))
            fd = f_ext.scoped_doc_id if f_ext else (resolve_field(tn, fn) or field_doc_id(tn, fn))
            refs.append({"kind": "field", "targetDocId": fd, "role": role, "rawText": f"{tn}::{fn}", **_ext(f_ext)})

    # Value lists used by the step (e.g. Sort Records by value list)
    for vr in step.get("value_list_refs", []) or []:
        vd = value_list_doc_id(normalize_name(vr["name"]))
        if not any(r["kind"] == "valueList" and r["targetDocId"] == vd for r in refs):
            refs.append({"kind": "valueList", "targetDocId": vd, "role": "sort"})
    return refs


# ---------------------------------------------------------------------------
# Custom Functions
# ---------------------------------------------------------------------------

def _normalize_custom_functions(raw: RawModel, model: DocumentModel) -> None:
    for cf in raw.custom_functions:
        name = normalize_name(cf.get("name", ""))
        if not name:
            continue
        doc_id = custom_function_doc_id(name)
        entity = CustomFunctionEntity(
            docId=doc_id,
            name=name,
            fmpId=str(cf.get("id", "")),
            uuid=cf.get("uuid"),
            parameters=cf.get("parameters", []),
            calculation=cf.get("calculation"),
            calculations=_entity_calcs(cf.get("calculations"), [("calculation", cf.get("calculation"))]),
            modified=ModificationInfo.model_validate(cf["modified"]) if cf.get("modified") else None,
            sourceXml=SourceXmlInfo(path=cf.get("source_xml_path", "")) if cf.get("source_xml_path") else None,
        )
        model.entities.custom_functions[doc_id] = entity


# ---------------------------------------------------------------------------
# Value Lists
# ---------------------------------------------------------------------------

def _normalize_value_lists(raw: RawModel, model: DocumentModel) -> None:
    resolve_field = build_field_resolver(model)
    ext = ExternalTargets(model)
    to_name_map = {to.name: to.doc_id for to in model.entities.table_occurrences.values()}
    for vl in raw.value_lists:
        name = normalize_name(vl.get("name", ""))
        if not name:
            continue
        doc_id = value_list_doc_id(name)

        source_field_doc = None
        source_external = None
        second_external = None
        sf = vl.get("source_field")
        if sf:
            t = sf.get("table", "")
            fn = sf.get("name", "")
            source_external = ext.field(t, fn, sf.get("id"))
            source_field_doc = (
                source_external.scoped_doc_id if source_external
                else resolve_field_or_fallback(resolve_field, t, fn)
            )

        second_field_doc = None
        sf2 = vl.get("second_field")
        if sf2:
            t = sf2.get("table", "")
            fn = sf2.get("name", "")
            second_external = ext.field(t, fn, sf2.get("id"))
            second_field_doc = (
                second_external.scoped_doc_id if second_external
                else resolve_field_or_fallback(resolve_field, t, fn)
            )

        def to_did(table_occurrence: Optional[str]) -> Optional[str]:
            return to_name_map.get(normalize_name(table_occurrence)) if table_occurrence else None

        sort_by = None
        if sf and sf.get("sort"):
            sort_by = "first"
        elif sf2 and sf2.get("sort"):
            sort_by = "second"
        ext_vl = vl.get("external")
        missing = [label for label, part in (("source field", sf), ("second field", sf2))
                   if part is not None and not part.get("name")]
        if vl.get("list_type") == "field" and sf is None:
            missing.append("source field")  # a list "from field" whose field FileMaker can't find
        if ext_vl is not None and not ext_vl.get("name"):
            missing.append("external list")
        entity = ValueListEntity(
            docId=doc_id,
            name=name,
            fmpId=str(vl.get("id", "")),
            uuid=vl.get("uuid"),
            listType=vl.get("list_type", "customValues"),
            values=vl.get("values", []),
            sourceFieldDocId=source_field_doc,
            secondFieldDocId=second_field_doc,
            sourceFieldExternal=source_external,
            secondFieldExternal=second_external,
            sourceFieldToDocId=to_did(sf.get("table")) if sf else None,
            secondFieldToDocId=to_did(sf2.get("table")) if sf2 else None,
            showFirstField=sf.get("show") if sf and sf2 else None,
            sortBy=sort_by,
            relatedFromToDocId=to_did(vl.get("related_from")),
            externalDataSource=ext_vl.get("data_source") if ext_vl else None,
            missing=missing,
            externalValueList=(
                ext.value_list(ext_vl.get("data_source"), ext_vl.get("name", ""), ext_vl.get("id"), ext_vl.get("uuid"),
                               ext_vl.get("data_source_id"), ext_vl.get("data_source_uuid"))
                if ext_vl else None
            ),
            modified=ModificationInfo.model_validate(vl["modified"]) if vl.get("modified") else None,
            sourceXml=SourceXmlInfo(path=vl.get("source_xml_path", "")) if vl.get("source_xml_path") else None,
        )
        model.entities.value_lists[doc_id] = entity


# ---------------------------------------------------------------------------
# Privilege Sets
# ---------------------------------------------------------------------------

_PRIVILEGE_TARGETS = {
    "BaseTableReference": table_doc_id,
    "TableOccurrenceReference": to_doc_id,
    "LayoutReference": layout_doc_id,
    "ScriptReference": script_doc_id,
    "ValueListReference": value_list_doc_id,
}


def _privilege_summary(settings: dict[str, str], custom: bool) -> str:
    """FileMaker's wording for a blanket setting, e.g. "Create, edit, and delete in all tables"."""
    if custom:
        return "Custom privileges"
    allowed = [verb for verb in ("Create", "Edit", "Delete") if settings.get(verb, "").lower() == "true"]
    if allowed:
        return ", ".join(v.lower() for v in allowed).capitalize()
    view = settings.get("View")
    if view:
        return {"ReadOnly": "View only", "NoAccess": "No access", "ReadWrite": "Modifiable"}.get(view, view)
    if any(v.lower() == "false" for v in settings.values()):
        return "No access"
    return ""


def _privilege_category(raw_cat: Optional[dict]) -> Optional[PrivilegeCategory]:
    if not raw_cat:
        return None
    settings = raw_cat.get("settings") or {}
    custom = raw_cat.get("custom")
    items = None
    if custom is not None:
        items = []
        for it in custom:
            make_id = _PRIVILEGE_TARGETS.get(it.get("reference_kind") or "")
            name = normalize_name(it.get("name") or "")
            target = make_id(name) if make_id and name else None
            label = it.get("name") or (f"[Any new {it.get('kind', '').lower()}]" if it.get("type") == "New" else "")
            items.append(PrivilegeItem(
                kind=it.get("kind") or "",
                targetDocId=target,
                label=label,
                access=it.get("access") or {},
                calculations=[EntityCalculation(role=c["column"], text=c["calculation"])
                              for c in it.get("calculations") or []],
                attributes=it.get("attributes") or {},
            ))
    return PrivilegeCategory(summary=_privilege_summary(settings, custom is not None), settings=settings, custom=items)


def _normalize_privilege_sets(raw: RawModel, model: DocumentModel) -> None:
    for ps in raw.privilege_sets:
        name = normalize_name(ps.get("name", ""))
        if not name:
            continue
        doc_id = privilege_set_doc_id(name)
        access = ps.get("access") or {}
        entity = PrivilegeSetEntity(
            docId=doc_id,
            name=name,
            fmpId=str(ps.get("id", "")),
            description=ps.get("description"),
            builtIn=bool(access.get("default")),
            records=_privilege_category(access.get("records")),
            layouts=_privilege_category(access.get("layouts")),
            valueLists=_privilege_category(access.get("value_lists")),
            scripts=_privilege_category(access.get("scripts")),
            other=access.get("other") or {},
            modified=ModificationInfo.model_validate(ps["modified"]) if ps.get("modified") else None,
            sourceXml=SourceXmlInfo(path=ps.get("source_xml_path", "")) if ps.get("source_xml_path") else None,
        )
        model.entities.privilege_sets[doc_id] = entity


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _normalize_accounts(raw: RawModel, model: DocumentModel) -> None:
    ps_name_map = {ps.name: ps.doc_id for ps in model.entities.privilege_sets.values()}
    for acct in raw.accounts:
        name = normalize_name(acct.get("name", ""))
        if not name:
            continue
        doc_id = account_doc_id(name)
        ps_name = acct.get("privilege_set_name") or ""
        ps_doc_id = ps_name_map.get(ps_name) or (privilege_set_doc_id(ps_name) if ps_name else None)
        entity = AccountEntity(
            docId=doc_id,
            name=name,
            fmpId=str(acct.get("id", "")),
            accountType=acct.get("account_type", "FileMaker"),
            enabled=acct.get("enabled", True),
            description=acct.get("description"),
            privilegeSetDocId=ps_doc_id,
            privilegeSetName=ps_name or None,
            modified=ModificationInfo.model_validate(acct["modified"]) if acct.get("modified") else None,
            sourceXml=SourceXmlInfo(path=acct.get("source_xml_path", "")) if acct.get("source_xml_path") else None,
        )
        model.entities.accounts[doc_id] = entity


# ---------------------------------------------------------------------------
# Extended Privileges
# ---------------------------------------------------------------------------

def _normalize_extended_privileges(raw: RawModel, model: DocumentModel) -> None:
    ps_name_map = {ps.name: ps.doc_id for ps in model.entities.privilege_sets.values()}
    for ep in raw.extended_privileges:
        name = normalize_name(ep.get("name", ""))
        if not name:
            continue
        doc_id = extended_privilege_doc_id(name)
        ps_doc_ids = []
        for ref in ep.get("privilege_set_refs", []):
            ref_name = ref.get("name", "")
            ps_did = ps_name_map.get(ref_name) or (privilege_set_doc_id(ref_name) if ref_name else None)
            if ps_did and ps_did not in ps_doc_ids:
                ps_doc_ids.append(ps_did)
        entity = ExtendedPrivilegeEntity(
            docId=doc_id,
            name=name,
            fmpId=str(ep.get("id", "")),
            description=ep.get("description"),
            privilegeSetDocIds=ps_doc_ids,
            modified=ModificationInfo.model_validate(ep["modified"]) if ep.get("modified") else None,
            sourceXml=SourceXmlInfo(path=ep.get("source_xml_path", "")) if ep.get("source_xml_path") else None,
        )
        model.entities.extended_privileges[doc_id] = entity


# ---------------------------------------------------------------------------
# Custom Menus
# ---------------------------------------------------------------------------

def _normalize_custom_menus(raw: RawModel, model: DocumentModel) -> None:
    ext = ExternalTargets(model)
    script_name_map = {s.name: s.doc_id for s in model.entities.scripts.values()}
    for cm in raw.custom_menus:
        name = normalize_name(cm.get("name", ""))
        if not name:
            continue
        doc_id = custom_menu_doc_id(name)
        items = []
        for item in cm.get("items", []):
            sref = item.get("script_ref")
            s_ext = ext.script(sref.get("data_source"), sref["name"], sref.get("id"), sref.get("uuid")) if sref else None
            if s_ext:
                script_did = s_ext.scoped_doc_id
            else:
                script_did = model.local_script_doc_id(sref["name"], sref.get("id")) if sref else None
            items.append(CustomMenuItem(
                name=item.get("name", ""),
                actionType=item.get("action_type", ""),
                installCondition=item.get("install_condition"),
                scriptDocId=script_did,
                scriptExternal=s_ext,
                submenuDocId=custom_menu_doc_id(normalize_name(item["submenu_name"])) if item.get("submenu_name") else None,
            ))
        entity = CustomMenuEntity(
            docId=doc_id,
            name=name,
            fmpId=str(cm.get("id", "")),
            baseMenuName=cm.get("base_menu_name"),
            installCondition=cm.get("install_condition"),
            browseMode=cm.get("browse_mode", True),
            findMode=cm.get("find_mode", True),
            previewMode=cm.get("preview_mode", True),
            items=items,
            calculations=_entity_calcs(cm.get("calculations"), [("installCondition", cm.get("install_condition"))]),
            modified=ModificationInfo.model_validate(cm["modified"]) if cm.get("modified") else None,
            sourceXml=SourceXmlInfo(path=cm.get("source_xml_path", "")) if cm.get("source_xml_path") else None,
        )
        model.entities.custom_menus[doc_id] = entity


# ---------------------------------------------------------------------------
# Custom Menu Sets
# ---------------------------------------------------------------------------

def _normalize_custom_menu_sets(raw: RawModel, model: DocumentModel) -> None:
    for cms in raw.custom_menu_sets:
        name = normalize_name(cms.get("name", ""))
        if not name:
            continue
        doc_id = custom_menu_set_doc_id(name)
        menu_doc_ids = []
        for ref in cms.get("menu_refs", []):
            ref_name = ref.get("name", "")
            if ref_name:
                menu_doc_ids.append(custom_menu_doc_id(ref_name))
        entity = CustomMenuSetEntity(
            docId=doc_id,
            name=name,
            fmpId=str(cms.get("id", "")),
            menuDocIds=menu_doc_ids,
            modified=ModificationInfo.model_validate(cms["modified"]) if cms.get("modified") else None,
            sourceXml=SourceXmlInfo(path=cms.get("source_xml_path", "")) if cms.get("source_xml_path") else None,
        )
        model.entities.custom_menu_sets[doc_id] = entity


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

def _normalize_themes(raw: RawModel, model: DocumentModel) -> None:
    for th in raw.themes:
        name = normalize_name(th.get("name", ""))
        if not name:
            continue
        doc_id = theme_doc_id(name)
        entity = ThemeEntity(
            docId=doc_id,
            name=name,
            fmpId=str(th.get("id", "")),
            displayName=th.get("display_name", ""),
            group=th.get("group"),
            defaultTheme=th.get("default_theme", False),
            modified=ModificationInfo.model_validate(th["modified"]) if th.get("modified") else None,
            sourceXml=SourceXmlInfo(path=th.get("source_xml_path", "")) if th.get("source_xml_path") else None,
        )
        model.entities.themes[doc_id] = entity


# ---------------------------------------------------------------------------
# File References
# ---------------------------------------------------------------------------

def _normalize_file_references(raw: RawModel, model: DocumentModel) -> None:
    for fr in raw.file_references:
        display_name = fr.get("display_name", "") or fr.get("name", "")
        ref_type = fr.get("ref_type", "Local")
        if not display_name:
            continue
        doc_id = file_reference_doc_id(ref_type, display_name)
        if doc_id in model.entities.file_references:  # FileMaker allows two with one name
            doc_id = file_reference_doc_id(ref_type, f"{display_name} (#{fr.get('id', '') or len(model.entities.file_references)})")
        entity = FileReferenceEntity(
            docId=doc_id,
            name=display_name,
            fmpId=str(fr.get("id", "")),
            refType=ref_type,
            isSelf=fr.get("is_self", False),
            sourceXml=SourceXmlInfo(path=fr.get("source_xml_path", "")) if fr.get("source_xml_path") else None,
        )
        model.entities.file_references[doc_id] = entity
