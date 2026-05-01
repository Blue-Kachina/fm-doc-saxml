"""Main normalization pipeline — converts RawModel into DocumentModel."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    ScriptStepEntity,
    ScriptEntity,
    CustomFunctionEntity,
    ValueListEntity,
    PrivilegeSetEntity,
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
    script_doc_id,
    script_step_doc_id,
    custom_function_doc_id,
    value_list_doc_id,
    privilege_set_doc_id,
)
from .names import normalize_name, qualified_name


def normalize(raw: RawModel, source_file: str = "") -> DocumentModel:
    """Convert a RawModel into a fully normalized DocumentModel."""
    source = SourceInfo(
        fileName=source_file or raw.file_name,
        fileMakerVersion=raw.filemaker_version,
        generatedAt=datetime.now(timezone.utc),
    )
    solution = SolutionInfo(name=raw.solution_name or source_file or "Unknown Solution")
    entities = EntityMaps()
    model = DocumentModel(source=source, solution=solution, entities=entities)

    # Propagate parse-time warnings
    for w in raw.parse_warnings:
        model.add_warning("PARSE_WARNING", w)

    _normalize_tables(raw, model)
    _normalize_fields(raw, model)
    _normalize_table_occurrences(raw, model)
    _normalize_relationships(raw, model)
    _normalize_layouts(raw, model)
    _normalize_scripts(raw, model)
    _normalize_custom_functions(raw, model)
    _normalize_value_lists(raw, model)
    _normalize_privilege_sets(raw, model)

    return model


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
            sourceXml=SourceXmlInfo(path=t.get("source_xml_path", "")) if t.get("source_xml_path") else None,
        )
        model.entities.tables[doc_id] = entity


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
            "maxRepeat": storage_raw.get("maxRepeat", 1),
        })

        auto_enter = None
        ae_raw = f.get("auto_enter")
        if ae_raw:
            auto_enter = AutoEnterOptions(
                type=ae_raw.get("type", "none"),
                value=ae_raw.get("value"),
                calculation=ae_raw.get("calculation"),
                no_modify_auto_enter=ae_raw.get("no_modify_auto_enter", False),
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
            )

        entity = FieldEntity(
            docId=doc_id,
            name=name,
            qualifiedName=qualified_name(table_name, name),
            baseTableDocId=table_did,
            dataType=f.get("data_type", "Text"),
            fieldType=f.get("field_type", "Normal"),
            fmpId=str(f.get("id", "")),
            uuid=f.get("uuid"),
            calculation=f.get("calculation"),
            autoEnter=auto_enter,
            validation=validation,
            storage=storage,
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
        base_table_doc_id = table_id_map.get(base_table_id) or table_name_map.get(name, "")

        entity = TableOccurrenceEntity(
            docId=doc_id,
            name=name,
            baseTableDocId=base_table_doc_id,
            fmpId=str(to.get("id", "")),
            uuid=to.get("uuid"),
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
    field_name_map: dict[tuple[str, str], str] = {
        (f.base_table_doc_id.split(":", 1)[1], f.name): f.doc_id
        for f in model.entities.fields.values()
    }
    # Also map by table occurrence name (which may equal base table name)
    to_to_base_map = {to.name: to.base_table_doc_id for to in model.entities.table_occurrences.values()}

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
            left_field_doc = _resolve_pred_field(pred, "left", to_to_base_map, field_name_map, model)
            right_field_doc = _resolve_pred_field(pred, "right", to_to_base_map, field_name_map, model)
            predicates.append(RelationshipPredicate(
                leftFieldDocId=left_field_doc,
                operator=pred.get("operator", "="),
                rightFieldDocId=right_field_doc,
            ))

        options = RelationshipOptions(
            allowCreateRelated=rel.get("allow_create_related", False),
            deleteRelated=rel.get("delete_related", False),
            sortRelated=rel.get("sort_related", False),
        )

        entity = RelationshipEntity(
            docId=doc_id,
            name=name,
            fmpId=str(rel.get("id", "")),
            leftTableOccurrenceDocId=left_to_doc,
            rightTableOccurrenceDocId=right_to_doc,
            predicates=predicates,
            options=options,
            sourceXml=SourceXmlInfo(path=rel.get("source_xml_path", "")) if rel.get("source_xml_path") else None,
        )
        model.entities.relationships[doc_id] = entity

        # Register relationship on TOs
        for to_doc in [left_to_doc, right_to_doc]:
            to_entity = model.entities.table_occurrences.get(to_doc)
            if to_entity and doc_id not in to_entity.relationships:
                to_entity.relationships.append(doc_id)


def _resolve_pred_field(
    pred: dict,
    side: str,
    to_to_base_map: dict[str, str],
    field_name_map: dict[tuple[str, str], str],
    model: DocumentModel,
) -> str:
    field_name = pred.get(f"{side}_field_name", "")
    table_name = pred.get(f"{side}_table_name", "")
    # Try resolving via base table name
    base_table_name = to_to_base_map.get(table_name, "")
    if base_table_name:
        actual_table = base_table_name.split(":", 1)[1] if ":" in base_table_name else base_table_name
        doc_id = field_name_map.get((actual_table, field_name), "")
        if doc_id:
            return doc_id
    # Fallback: construct docId directly
    return field_doc_id(table_name, field_name) if table_name and field_name else ""


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

    field_name_map: dict[tuple[str, str], str] = {
        (f.base_table_doc_id.split(":", 1)[1], f.name): f.doc_id
        for f in model.entities.fields.values()
    }

    for layout in raw.layouts:
        name = normalize_name(layout.get("name", ""))
        if not name:
            continue
        doc_id = layout_doc_id(name)

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
            fd = field_name_map.get((t, fn)) or field_doc_id(t, fn)
            if fd not in ref_field_doc_ids:
                ref_field_doc_ids.append(fd)

        entity = LayoutEntity(
            docId=doc_id,
            name=name,
            fmpId=str(layout.get("id", "")),
            uuid=layout.get("uuid"),
            baseTableOccurrenceDocId=to_doc,
            theme=layout.get("theme"),
            referencedFields=ref_field_doc_ids,
            sourceXml=SourceXmlInfo(path=layout.get("source_xml_path", "")) if layout.get("source_xml_path") else None,
        )
        model.entities.layouts[doc_id] = entity


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def _normalize_scripts(raw: RawModel, model: DocumentModel) -> None:
    layout_name_map = {ly.name: ly.doc_id for ly in model.entities.layouts.values()}
    script_name_map_prelim: dict[str, str] = {}

    # First pass — create script entities without step cross-references
    script_entities: list[tuple[dict, ScriptEntity]] = []
    for s in raw.scripts:
        name = normalize_name(s.get("name", ""))
        if not name:
            continue
        doc_id = script_doc_id(name)
        entity = ScriptEntity(
            docId=doc_id,
            name=name,
            fmpId=str(s.get("id", "")),
            uuid=s.get("uuid"),
            folderPath=s.get("folder_path"),
            sourceXml=SourceXmlInfo(path=s.get("source_xml_path", "")) if s.get("source_xml_path") else None,
        )
        model.entities.scripts[doc_id] = entity
        script_name_map_prelim[name] = doc_id
        script_entities.append((s, entity))

    # Second pass — process steps (now all script docIds are known)
    field_name_map: dict[tuple[str, str], str] = {
        (f.base_table_doc_id.split(":", 1)[1], f.name): f.doc_id
        for f in model.entities.fields.values()
    }

    for s, script_entity in script_entities:
        step_doc_ids = []
        ref_fields: list[str] = []
        ref_layouts: list[str] = []
        ref_scripts: list[str] = []

        for raw_step in s.get("steps", []):
            step_doc = script_step_doc_id(script_entity.name, raw_step.get("index", 0))
            step_refs = []

            # Layout reference
            lr = raw_step.get("layout_ref")
            if lr and lr.get("name"):
                ld = layout_name_map.get(lr["name"]) or layout_doc_id(lr["name"])
                step_refs.append({"kind": "layout", "targetDocId": ld, "role": "target"})
                if ld not in ref_layouts:
                    ref_layouts.append(ld)
                    script_entity.referenced_layouts.append(ld)

            # Field references
            for fr in raw_step.get("field_refs", []):
                fn = fr.get("name", "")
                tn = fr.get("table", "")
                if fn:
                    fd = field_name_map.get((tn, fn)) or field_doc_id(tn, fn)
                    step_refs.append({"kind": "field", "targetDocId": fd, "role": "target", "rawText": f"{tn}::{fn}"})
                    if fd not in ref_fields:
                        ref_fields.append(fd)
                        script_entity.referenced_fields.append(fd)

            # Script reference
            sr = raw_step.get("script_ref")
            if sr and sr.get("name"):
                sn = sr["name"]
                sd = script_name_map_prelim.get(sn) or script_doc_id(sn)
                step_refs.append({"kind": "script", "targetDocId": sd, "role": "callee"})
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
                references=step_refs,
            )
            model.entities.script_steps[step_doc] = step_entity
            step_doc_ids.append(step_doc)

        script_entity.steps = step_doc_ids


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
            sourceXml=SourceXmlInfo(path=cf.get("source_xml_path", "")) if cf.get("source_xml_path") else None,
        )
        model.entities.custom_functions[doc_id] = entity


# ---------------------------------------------------------------------------
# Value Lists
# ---------------------------------------------------------------------------

def _normalize_value_lists(raw: RawModel, model: DocumentModel) -> None:
    field_name_map: dict[tuple[str, str], str] = {
        (f.base_table_doc_id.split(":", 1)[1], f.name): f.doc_id
        for f in model.entities.fields.values()
    }
    for vl in raw.value_lists:
        name = normalize_name(vl.get("name", ""))
        if not name:
            continue
        doc_id = value_list_doc_id(name)

        source_field_doc = None
        sf = vl.get("source_field")
        if sf:
            t = sf.get("table", "")
            fn = sf.get("name", "")
            source_field_doc = field_name_map.get((t, fn)) or (field_doc_id(t, fn) if t and fn else None)

        second_field_doc = None
        sf2 = vl.get("second_field")
        if sf2:
            t = sf2.get("table", "")
            fn = sf2.get("name", "")
            second_field_doc = field_name_map.get((t, fn)) or (field_doc_id(t, fn) if t and fn else None)

        entity = ValueListEntity(
            docId=doc_id,
            name=name,
            fmpId=str(vl.get("id", "")),
            uuid=vl.get("uuid"),
            listType=vl.get("list_type", "customValues"),
            values=vl.get("values", []),
            sourceFieldDocId=source_field_doc,
            secondFieldDocId=second_field_doc,
            sourceXml=SourceXmlInfo(path=vl.get("source_xml_path", "")) if vl.get("source_xml_path") else None,
        )
        model.entities.value_lists[doc_id] = entity


# ---------------------------------------------------------------------------
# Privilege Sets
# ---------------------------------------------------------------------------

def _normalize_privilege_sets(raw: RawModel, model: DocumentModel) -> None:
    for ps in raw.privilege_sets:
        name = normalize_name(ps.get("name", ""))
        if not name:
            continue
        doc_id = privilege_set_doc_id(name)
        entity = PrivilegeSetEntity(
            docId=doc_id,
            name=name,
            fmpId=str(ps.get("id", "")),
            description=ps.get("description"),
            sourceXml=SourceXmlInfo(path=ps.get("source_xml_path", "")) if ps.get("source_xml_path") else None,
        )
        model.entities.privilege_sets[doc_id] = entity
