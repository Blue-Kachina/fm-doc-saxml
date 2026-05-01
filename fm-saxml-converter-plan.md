# FileMaker Save As XML Documentation Generator Plan

## 1. Project Goal

Create a documentation pipeline that turns a FileMaker Pro **Save a Copy as XML** export into a structured, linkable documentation set.

The first output target should be a folder of Markdown files, but the architecture should not be Markdown-specific. The core goal is to build a normalized JSON representation of the FileMaker system, then render that JSON into one or more output formats.

Initial pipeline:

```text
FileMaker SaveAsXML.xml
        ↓
XML Parser / Extractor
        ↓
Normalized Recursive JSON Model
        ↓
Documentation Renderers
        ↓
Markdown site / HTML site / Vue data / search index / AI agent corpus
```

The long-term value is not just “pretty documentation.” The real value is a clean, navigable knowledge graph of the FileMaker solution that can be used by humans, AI agents, code review tools, documentation generators, and eventually maybe diff/reporting tools.

---

## 2. Guiding Principles

### 2.1 Separate extraction from presentation

Do not generate Markdown directly from the XML.

Instead:

1. Parse FileMaker XML.
2. Normalize it into your own JSON structure.
3. Enrich that JSON with references, backlinks, display names, warnings, and derived relationships.
4. Render Markdown from the JSON.
5. Add future renderers later.

This prevents the Markdown generator from becoming tangled with FileMaker XML quirks.

### 2.2 Treat FileMaker XML as an input format, not your source of truth

Claris notes that the XML format may change between FileMaker Pro versions, so the parser should be version-aware and isolated from the rest of the app.

Your internal JSON model should be more stable than the FileMaker XML.

### 2.3 Preserve FileMaker identity, but add documentation identity

Many FileMaker elements have names, IDs, UUIDs, internal references, or paths.

For documentation, each entity should receive its own stable documentation identity:

```json
{
  "docId": "field:Acc_Transaction_Log::Type",
  "fmpId": "72",
  "uuid": "...",
  "name": "Type",
  "qualifiedName": "Acc_Transaction_Log::Type"
}
```

The `docId` should be what your renderer and link system use. The `fmpId` and `uuid` should be preserved as metadata.

### 2.4 Link aggressively

Whenever one entity refers to another, create a linkable relationship.

Examples:

- Field → Base table
- Table → Fields
- Table occurrence → Base table
- Relationship → Source/target table occurrences
- Script step → Referenced fields/layouts/scripts
- Layout → Table occurrence
- Layout object → Field
- Value list → Fields, custom values, related values
- Custom function → Other custom functions
- Calculation → Fields, custom functions, table occurrences
- Privilege set → Tables, layouts, scripts

### 2.5 Optimize for humans and AI agents

Markdown files should be easy to read manually, but also predictable for AI indexing.

Use consistent headings and consistent tables.

Good pattern:

```markdown
# Field: Acc_Transaction_Log::Type

## Summary

| Name | Value |
|------|-------|
| Base Table | [Acc_Transaction_Log](../Tables/Acc_Transaction_Log.md) |
| Field Name | Type |
| Data Type | Number |
| Field Type | Normal |
| FMP ID | 72 |

## Definition

| Name | Value |
|------|-------|
| Auto-enter | None |
| Validation | None |
| Storage | Indexed |

## References

### Used By Scripts

| Script | Step | Context |
|--------|------|---------|
| [Post Transaction](../Scripts/Post_Transaction.md) | Set Field | `Acc_Transaction_Log::Type` |

### Used By Layouts

| Layout | Object |
|--------|--------|
| [Transaction Detail](../Layouts/Transaction_Detail.md) | Field object |
```

---

## 3. Proposed Repository Structure

```text
fm-docgen/
├─ README.md
├─ pyproject.toml
├─ src/
│  └─ fm_docgen/
│     ├─ cli.py
│     ├─ config.py
│     ├─ parser/
│     │  ├─ __init__.py
│     │  ├─ saxml_reader.py
│     │  ├─ version_detector.py
│     │  └─ extractors/
│     │     ├─ tables.py
│     │     ├─ fields.py
│     │     ├─ table_occurrences.py
│     │     ├─ relationships.py
│     │     ├─ layouts.py
│     │     ├─ scripts.py
│     │     ├─ script_steps.py
│     │     ├─ custom_functions.py
│     │     ├─ value_lists.py
│     │     └─ privileges.py
│     ├─ model/
│     │  ├─ document_model.py
│     │  ├─ entities.py
│     │  ├─ references.py
│     │  └─ validation.py
│     ├─ normalize/
│     │  ├─ normalize.py
│     │  ├─ names.py
│     │  ├─ paths.py
│     │  ├─ ids.py
│     │  └─ references.py
│     ├─ analyze/
│     │  ├─ dependency_graph.py
│     │  ├─ backlinks.py
│     │  ├─ calculations.py
│     │  └─ warnings.py
│     ├─ render/
│     │  ├─ markdown/
│     │  │  ├─ renderer.py
│     │  │  ├─ templates/
│     │  │  │  ├─ table.md.j2
│     │  │  │  ├─ field.md.j2
│     │  │  │  ├─ script.md.j2
│     │  │  │  ├─ layout.md.j2
│     │  │  │  └─ index.md.j2
│     │  ├─ html/
│     │  │  └─ renderer.py
│     │  └─ json/
│     │     └─ writer.py
│     └─ utils/
│        ├─ markdown.py
│        ├─ slugify.py
│        └─ file_writer.py
├─ tests/
│  ├─ fixtures/
│  │  ├─ small_sample.xml
│  │  └─ expected_model.json
│  ├─ test_parser.py
│  ├─ test_normalize.py
│  ├─ test_references.py
│  └─ test_markdown_render.py
└─ examples/
   ├─ input/
   └─ output/
```

---

## 4. Command-Line Interface

Start with a simple CLI.

```bash
fm-docgen parse ./FileMakerProSaveAsXML.xml --out ./build/model.json

fm-docgen render markdown ./build/model.json --out ./docs

fm-docgen build ./FileMakerProSaveAsXML.xml --out ./docs
```

Eventually:

```bash
fm-docgen build ./MySolution.xml \
  --model-out ./build/model.json \
  --markdown-out ./docs \
  --include-backlinks \
  --include-raw-xml-paths \
  --strict
```

Recommended initial commands:

| Command | Purpose |
|---|---|
| `parse` | Convert SaveAsXML into normalized JSON |
| `render markdown` | Convert normalized JSON into Markdown files |
| `build` | Parse and render in one command |
| `validate` | Check JSON model consistency |
| `inspect` | Print counts and warnings |
| `diff` | Future comparison between two JSON models |

---

## 5. Normalized JSON Model

The JSON model should be recursive enough to represent the FileMaker file, but also indexed enough to allow easy linking.

Use both:

1. A hierarchical structure for human readability.
2. Entity maps for fast lookup.

Example top-level shape:

```json
{
  "schemaVersion": "0.1.0",
  "source": {
    "type": "FileMakerSaveAsXML",
    "fileName": "FileMakerProSaveAsXML.xml",
    "fileMakerVersion": "unknown",
    "generatedAt": "2026-05-01T00:00:00Z"
  },
  "solution": {
    "name": "My FileMaker Solution",
    "files": []
  },
  "entities": {
    "tables": {},
    "fields": {},
    "tableOccurrences": {},
    "relationships": {},
    "layouts": {},
    "scripts": {},
    "scriptSteps": {},
    "customFunctions": {},
    "valueLists": {},
    "privilegeSets": {}
  },
  "references": [],
  "backlinks": {},
  "warnings": []
}
```

### 5.1 Why include entity maps?

Because Markdown rendering will constantly need to answer questions like:

- What field does this field reference point to?
- What table does this table occurrence belong to?
- Which scripts use this field?
- Which layouts are based on this table occurrence?

Maps make those lookups easy.

Example:

```json
"entities": {
  "fields": {
    "field:Acc_Transaction_Log::Type": {
      "docId": "field:Acc_Transaction_Log::Type",
      "entityType": "field",
      "name": "Type",
      "qualifiedName": "Acc_Transaction_Log::Type",
      "baseTableDocId": "table:Acc_Transaction_Log",
      "dataType": "Number",
      "fieldType": "Normal",
      "fmpId": "72",
      "uuid": null,
      "calculation": null,
      "autoEnter": null,
      "validation": null,
      "storage": {
        "indexed": true,
        "global": false,
        "repeating": false
      }
    }
  }
}
```

---

## 6. Core Entity Types

### 6.1 Solution

Represents the whole exported FileMaker file.

Suggested fields:

| Field | Meaning |
|---|---|
| `docId` | Stable documentation ID |
| `name` | FileMaker file / solution name |
| `sourceFile` | XML input file |
| `generatedAt` | Documentation generation timestamp |
| `counts` | Counts of tables, fields, layouts, scripts, etc. |

### 6.2 Table

Represents a base table.

```json
{
  "docId": "table:Acc_Transaction_Log",
  "entityType": "table",
  "name": "Acc_Transaction_Log",
  "fmpId": "12",
  "uuid": "...",
  "fields": [
    "field:Acc_Transaction_Log::ID",
    "field:Acc_Transaction_Log::Type"
  ],
  "tableOccurrences": [
    "to:Acc_Transaction_Log"
  ]
}
```

### 6.3 Field

Represents a field belonging to a base table.

Important field subtypes:

- Normal field
- Calculation field
- Summary field
- Global field
- Container field
- Repeating field

Suggested fields:

| Field | Meaning |
|---|---|
| `docId` | Stable documentation ID |
| `name` | Field name |
| `qualifiedName` | `Table::Field` |
| `baseTableDocId` | Parent table |
| `dataType` | Text, Number, Date, Time, Timestamp, Container |
| `fieldType` | Normal, Calculation, Summary |
| `calculation` | Calculation definition if present |
| `autoEnter` | Auto-enter calculation/data |
| `validation` | Validation rules |
| `storage` | Global/index/repetition settings |
| `references` | Outbound references from calculation or options |

### 6.4 Table Occurrence

Represents an item on the relationship graph.

```json
{
  "docId": "to:Invoice__Customer",
  "entityType": "tableOccurrence",
  "name": "Invoice__Customer",
  "baseTableDocId": "table:Customer",
  "relationships": [
    "relationship:Invoice_to_Customer"
  ]
}
```

### 6.5 Relationship

Represents a relationship graph join between two table occurrences.

```json
{
  "docId": "relationship:Invoice__Customer",
  "entityType": "relationship",
  "name": "Invoice__Customer",
  "leftTableOccurrenceDocId": "to:Invoice",
  "rightTableOccurrenceDocId": "to:Invoice__Customer",
  "predicates": [
    {
      "leftFieldDocId": "field:Invoice::_kftCustomerID",
      "operator": "=",
      "rightFieldDocId": "field:Customer::__kpCustomerID"
    }
  ],
  "options": {
    "allowCreateRelatedRecords": false,
    "deleteRelatedRecords": false,
    "sortRelatedRecords": false
  }
}
```

### 6.6 Layout

Represents a layout.

```json
{
  "docId": "layout:Transaction_Detail",
  "entityType": "layout",
  "name": "Transaction Detail",
  "baseTableOccurrenceDocId": "to:Acc_Transaction_Log",
  "theme": "Default",
  "objects": [
    "layoutObject:Transaction_Detail:001"
  ],
  "referencedFields": [
    "field:Acc_Transaction_Log::Type"
  ],
  "scripts": []
}
```

### 6.7 Layout Object

This may be optional for the first version.

Eventually, layout objects can be extremely valuable because they explain where fields appear visually.

Suggested fields:

| Field | Meaning |
|---|---|
| `objectType` | Field, button, portal, tab panel, popover, web viewer, text, etc. |
| `fieldDocId` | Field shown by object, if any |
| `scriptDocId` | Script triggered by button/action, if any |
| `bounds` | Position and size |
| `name` | Object name |
| `conditionalFormatting` | Conditional formatting definitions |
| `hideCondition` | Hide object condition |

### 6.8 Script

Represents a FileMaker script.

```json
{
  "docId": "script:Post_Transaction",
  "entityType": "script",
  "name": "Post Transaction",
  "folderPath": "Accounting/Transactions",
  "steps": [
    "scriptStep:Post_Transaction:0001",
    "scriptStep:Post_Transaction:0002"
  ],
  "referencedFields": [],
  "referencedLayouts": [],
  "referencedScripts": [],
  "warnings": []
}
```

### 6.9 Script Step

Each script step should be extracted as its own structured entity or as embedded data under the script.

For future analysis, make it an entity.

```json
{
  "docId": "scriptStep:Post_Transaction:0007",
  "entityType": "scriptStep",
  "scriptDocId": "script:Post_Transaction",
  "index": 7,
  "name": "Set Field",
  "enabled": true,
  "rawText": "Set Field [ Acc_Transaction_Log::Type ; 1 ]",
  "references": [
    {
      "kind": "field",
      "targetDocId": "field:Acc_Transaction_Log::Type",
      "role": "target"
    }
  ]
}
```

### 6.10 Custom Function

```json
{
  "docId": "customFunction:MakeDateRangeArray",
  "entityType": "customFunction",
  "name": "MakeDateRangeArray",
  "parameters": ["_year", "_type", "_labelStart"],
  "calculation": "...",
  "references": []
}
```

### 6.11 Value List

```json
{
  "docId": "valueList:Status",
  "entityType": "valueList",
  "name": "Status",
  "type": "customValues",
  "values": ["Approved", "Pending", "Declined", "Info Only"],
  "sourceFieldDocId": null,
  "secondFieldDocId": null
}
```

### 6.12 Privilege Set

This can be deferred until later, but it will eventually matter.

```json
{
  "docId": "privilegeSet:Data Entry Only",
  "entityType": "privilegeSet",
  "name": "Data Entry Only",
  "records": {},
  "layouts": {},
  "scripts": {},
  "valueLists": {}
}
```

---

## 7. Reference Model

References should be first-class records.

Do not only store references inside entities. Store a flat reference list too.

```json
{
  "references": [
    {
      "sourceDocId": "scriptStep:Post_Transaction:0007",
      "sourceEntityType": "scriptStep",
      "targetDocId": "field:Acc_Transaction_Log::Type",
      "targetEntityType": "field",
      "relationshipType": "usesField",
      "role": "target",
      "confidence": "exact",
      "rawText": "Acc_Transaction_Log::Type"
    }
  ]
}
```

### 7.1 Suggested relationship types

| Type | Meaning |
|---|---|
| `contains` | Parent contains child |
| `usesField` | Script/layout/calculation uses field |
| `usesLayout` | Script step refers to layout |
| `usesScript` | Script calls another script |
| `usesCustomFunction` | Calculation calls custom function |
| `usesValueList` | Field/layout object uses value list |
| `basedOnTableOccurrence` | Layout is based on table occurrence |
| `basedOnBaseTable` | Table occurrence is based on base table |
| `joinsTo` | Relationship joins table occurrences |
| `readsFrom` | Calculation/script reads from entity |
| `writesTo` | Script writes to entity |
| `deletesFrom` | Script may delete records from context |
| `opensWindowOn` | Script opens layout/window |
| `navigatesTo` | Script changes layout or mode |

### 7.2 Reference confidence

Some references will be exact because FileMaker XML stores IDs.

Others may need to be inferred from calculation text.

Use confidence:

| Confidence | Meaning |
|---|---|
| `exact` | ID or explicit XML reference found |
| `parsed` | Parsed from calculation/script text |
| `inferred` | Inferred from context |
| `unresolved` | Text looks like a reference but target could not be matched |

---

## 8. Markdown Output Structure

Suggested output:

```text
docs/
├─ index.md
├─ entities.json
├─ references.json
├─ Tables/
│  ├─ index.md
│  └─ Acc_Transaction_Log.md
├─ Fields/
│  ├─ index.md
│  └─ Acc_Transaction_Log/
│     ├─ index.md
│     ├─ ID.md
│     └─ Type.md
├─ TableOccurrences/
│  ├─ index.md
│  └─ Invoice__Customer.md
├─ Relationships/
│  ├─ index.md
│  └─ Invoice__Customer.md
├─ Layouts/
│  ├─ index.md
│  └─ Transaction_Detail.md
├─ Scripts/
│  ├─ index.md
│  └─ Accounting/
│     └─ Post_Transaction.md
├─ CustomFunctions/
│  ├─ index.md
│  └─ MakeDateRangeArray.md
├─ ValueLists/
│  ├─ index.md
│  └─ Status.md
├─ Privileges/
│  ├─ index.md
│  └─ Data_Entry_Only.md
└─ Reports/
   ├─ unresolved-references.md
   ├─ dependency-graph.md
   ├─ unused-fields.md
   └─ warnings.md
```

### 8.1 File naming

Use safe slugs but preserve display names inside the file.

Example:

```text
Display name: Acc Transaction Log
Slug: Acc_Transaction_Log
File path: Tables/Acc_Transaction_Log.md
```

For fields:

```text
Fields/Acc_Transaction_Log/Type.md
```

This avoids collisions between fields with the same name in different tables.

### 8.2 Markdown front matter

Each Markdown file should include machine-readable front matter.

```markdown
---
docId: field:Acc_Transaction_Log::Type
entityType: field
name: Type
qualifiedName: Acc_Transaction_Log::Type
source: FileMakerProSaveAsXML.xml
---

# Field: Acc_Transaction_Log::Type
```

This helps static site generators, AI indexers, and future tooling.

---

## 9. Markdown Page Templates

### 9.1 Table page

```markdown
---
docId: table:Acc_Transaction_Log
entityType: table
name: Acc_Transaction_Log
---

# Table: Acc_Transaction_Log

## Metadata

| Name | Value |
|---|---|
| FMP ID | 12 |
| UUID | ... |
| Field Count | 27 |

## Fields

| Field | Type | Field Type | Notes |
|---|---|---|---|
| [ID](../Fields/Acc_Transaction_Log/ID.md) | Text | Normal | Primary key |
| [Type](../Fields/Acc_Transaction_Log/Type.md) | Number | Normal |  |

## Table Occurrences

| Table Occurrence | Notes |
|---|---|
| [Acc_Transaction_Log](../TableOccurrences/Acc_Transaction_Log.md) |  |

## Referenced By

| Entity | Type | Relationship |
|---|---|---|
| [Transaction Detail](../Layouts/Transaction_Detail.md) | Layout | Based on table occurrence |
```

### 9.2 Field page

```markdown
---
docId: field:Acc_Transaction_Log::Type
entityType: field
name: Type
qualifiedName: Acc_Transaction_Log::Type
---

# Field: Acc_Transaction_Log::Type

## Metadata

| Name | Value |
|---|---|
| FMP ID | 72 |
| Base Table | [Acc_Transaction_Log](../../Tables/Acc_Transaction_Log.md) |
| Field Name | Type |
| Field Type | Normal |
| Data Type | Number |

## Options

| Name | Value |
|---|---|
| Global | No |
| Indexed | Yes |
| Repeating | No |

## Calculation

_None._

## Auto-enter

_None._

## Validation

_None._

## Used By Scripts

| Script | Step | Usage |
|---|---|---|
| [Post Transaction](../../Scripts/Accounting/Post_Transaction.md) | Set Field | Target |

## Used By Layouts

| Layout | Usage |
|---|---|
| [Transaction Detail](../../Layouts/Transaction_Detail.md) | Field object |
```

### 9.3 Script page

```markdown
---
docId: script:Post_Transaction
entityType: script
name: Post Transaction
---

# Script: Post Transaction

## Metadata

| Name | Value |
|---|---|
| Folder | Accounting/Transactions |
| Step Count | 42 |

## Referenced Entities

### Fields

| Field | Usage Count |
|---|---:|
| [Acc_Transaction_Log::Type](../../Fields/Acc_Transaction_Log/Type.md) | 3 |

### Layouts

| Layout | Usage Count |
|---|---:|
| [Transaction Detail](../../Layouts/Transaction_Detail.md) | 1 |

### Scripts

| Script | Usage Count |
|---|---:|
| [Validate Transaction](Validate_Transaction.md) | 1 |

## Steps

| # | Enabled | Step | References |
|---:|---|---|---|
| 1 | Yes | Go to Layout [ Transaction Detail ] | [Transaction Detail](../../Layouts/Transaction_Detail.md) |
| 2 | Yes | Set Field [ Acc_Transaction_Log::Type ; 1 ] | [Acc_Transaction_Log::Type](../../Fields/Acc_Transaction_Log/Type.md) |
```

### 9.4 Relationship page

```markdown
---
docId: relationship:Invoice__Customer
entityType: relationship
name: Invoice__Customer
---

# Relationship: Invoice__Customer

## Metadata

| Name | Value |
|---|---|
| Left TO | [Invoice](../TableOccurrences/Invoice.md) |
| Right TO | [Invoice__Customer](../TableOccurrences/Invoice__Customer.md) |

## Predicates

| Left Field | Operator | Right Field |
|---|---|---|
| [Invoice::_kftCustomerID](../Fields/Invoice/_kftCustomerID.md) | = | [Customer::__kpCustomerID](../Fields/Customer/__kpCustomerID.md) |

## Options

| Name | Value |
|---|---|
| Allow create related records | No |
| Delete related records | No |
| Sort related records | No |
```

---

## 10. JSON-to-Markdown Renderer

Use templates rather than building strings manually.

Recommended template engine:

```bash
pip install jinja2
```

Renderer responsibilities:

1. Load `model.json`.
2. Build a link resolver.
3. Render index files.
4. Render one Markdown file per entity.
5. Render reports.
6. Copy JSON files into output folder if desired.

Pseudo-code:

```python
def render_markdown(model, output_dir):
    links = LinkResolver(model, output_dir)

    render_root_index(model, output_dir, links)
    render_tables(model, output_dir, links)
    render_fields(model, output_dir, links)
    render_table_occurrences(model, output_dir, links)
    render_relationships(model, output_dir, links)
    render_layouts(model, output_dir, links)
    render_scripts(model, output_dir, links)
    render_custom_functions(model, output_dir, links)
    render_value_lists(model, output_dir, links)
    render_reports(model, output_dir, links)

    write_json(output_dir / "entities.json", model["entities"])
    write_json(output_dir / "references.json", model["references"])
```

---

## 11. Link Resolver

A central link resolver is critical.

Every entity should have:

```json
{
  "docId": "field:Acc_Transaction_Log::Type",
  "markdownPath": "Fields/Acc_Transaction_Log/Type.md",
  "title": "Acc_Transaction_Log::Type"
}
```

The renderer should never guess links ad hoc.

Pseudo-code:

```python
class LinkResolver:
    def __init__(self, model, current_file=None):
        self.model = model
        self.path_by_doc_id = build_path_index(model)

    def href(self, source_doc_id, target_doc_id):
        source_path = self.path_by_doc_id[source_doc_id]
        target_path = self.path_by_doc_id[target_doc_id]
        return relative_path(from_file=source_path, to_file=target_path)

    def markdown_link(self, source_doc_id, target_doc_id, label=None):
        href = self.href(source_doc_id, target_doc_id)
        title = label or self.model["entityIndex"][target_doc_id]["title"]
        return f"[{escape_markdown(title)}]({href})"
```

---

## 12. Parsing Strategy

### 12.1 Use a streaming parser where possible

FileMaker XML can be large. Avoid loading the whole DOM if the file can be huge.

Options:

| Parser | Notes |
|---|---|
| `lxml.etree.iterparse` | Good for large XML files |
| `xml.etree.ElementTree.iterparse` | Built-in, less feature-rich |
| Full DOM parse | Easier at first, risky for huge files |

For the first prototype, a DOM parse may be fine. Design the parser so it can be swapped later.

### 12.2 Build extractors by entity type

Do not write one giant parser.

Use separate extractor modules:

```text
extract_tables()
extract_fields()
extract_table_occurrences()
extract_relationships()
extract_layouts()
extract_scripts()
extract_custom_functions()
extract_value_lists()
extract_privilege_sets()
```

Each extractor should return raw-ish records. Then a normalizer turns those records into the official model.

### 12.3 Preserve raw XML location

For debugging, include optional source trace data:

```json
{
  "sourceXml": {
    "path": "/FMSaveAsXML/Database/TableCatalog/BaseTable[12]/Field[3]",
    "line": 12345
  }
}
```

This is extremely useful when parser output looks wrong.

---

## 13. Normalization Phase

The normalization phase should:

1. Assign `docId`.
2. Normalize names.
3. Resolve parent-child relationships.
4. Create entity maps.
5. Create file paths.
6. Add display titles.
7. Add unresolved reference placeholders.
8. Validate required fields.

Example normalization flow:

```text
Raw XML records
    ↓
Normalize base tables
    ↓
Normalize fields
    ↓
Normalize table occurrences
    ↓
Normalize relationships
    ↓
Normalize layouts
    ↓
Normalize scripts and script steps
    ↓
Resolve references
    ↓
Create backlinks
    ↓
Validate model
```

---

## 14. Reference Extraction

Reference extraction is the hardest and most valuable part.

### 14.1 Exact XML references

Prefer FileMaker’s own internal IDs when available.

Examples:

- Layout based on table occurrence
- Layout field object bound to a field
- Relationship predicate field references
- Script step explicit field/layout/script references

### 14.2 Calculation parsing

Calculations will contain references in text form.

Examples:

```text
Acc_Transaction_Log::Type
MakeDateRangeArray ( _year ; _type ; _labelStart )
Get ( CurrentDate )
```

Initial approach:

1. Tokenize calculation text.
2. Detect `TableOccurrence::Field` patterns.
3. Detect custom function names followed by `(`.
4. Detect value list references only where XML explicitly exposes them.
5. Mark ambiguous matches as unresolved.

Do not attempt to fully parse FileMaker calculation grammar in version 1. Start with practical extraction.

### 14.3 Script step parsing

Where XML exposes script step targets directly, use those.

For script step text, parse common patterns:

| Script Step | References |
|---|---|
| Go to Layout | Layout |
| Perform Script | Script |
| Set Field | Field target, fields in calculation |
| Set Variable | Fields/functions in calculation |
| Go to Related Record | Layout, table occurrence |
| New Window | Layout |
| Sort Records | Fields |
| Enter Find Mode / Perform Find | Fields |
| Insert Calculated Result | Fields/functions |
| Delete Record | Current context / layout table occurrence |
| Replace Field Contents | Field |

---

## 15. Backlinks

After collecting all references, generate backlinks automatically.

Example:

```json
"backlinks": {
  "field:Acc_Transaction_Log::Type": [
    {
      "sourceDocId": "scriptStep:Post_Transaction:0007",
      "relationshipType": "usesField",
      "role": "target"
    },
    {
      "sourceDocId": "layoutObject:Transaction_Detail:001",
      "relationshipType": "usesField",
      "role": "display"
    }
  ]
}
```

Backlinks make pages useful.

A field page should not only describe the field. It should answer:

- Where is this field displayed?
- Which scripts write to it?
- Which scripts read from it?
- Which calculations reference it?
- Which relationships use it?
- Which value lists or validations depend on it?

---

## 16. Reports to Generate

Beyond one page per entity, generate analysis reports.

### 16.1 Initial reports

| Report | Purpose |
|---|---|
| `unresolved-references.md` | Things the parser could not link |
| `dependency-graph.md` | High-level relationship/dependency summary |
| `unused-fields.md` | Fields with no detected inbound references |
| `scripts-by-field-usage.md` | Which scripts touch which fields |
| `fields-by-script-usage.md` | Which fields each script touches |
| `layouts-by-table.md` | Layouts grouped by table occurrence/base table |
| `table-occurrence-map.md` | Relationship graph summary |
| `warnings.md` | Parser warnings, missing IDs, ambiguous references |
| `summary.md` | Entity counts and documentation stats |

### 16.2 Later reports

| Report | Purpose |
|---|---|
| `dangerous-scripts.md` | Scripts that delete records, replace contents, import/export, run server-side steps |
| `security-surface.md` | Privilege sets, script access, layout access |
| `global-fields.md` | Global fields and where they are used |
| `external-data-sources.md` | File references, ODBC, external files |
| `web-viewers.md` | Web viewer content and calculations |
| `server-compatibility.md` | Script steps that may fail on server |
| `dead-code-candidates.md` | Possibly unused scripts, fields, layouts |
| `change-impact.md` | Impact analysis for changing a field/table/script |

---

## 17. Future HTML / Vue Output

The normalized JSON should be suitable for a Vue frontend.

Possible HTML architecture:

```text
model.json
entities.json
references.json
search-index.json
        ↓
Vue app
        ↓
Interactive documentation browser
```

Vue features:

- Global search
- Entity detail pages
- Graph navigation
- Relationship graph visualization
- Filter scripts by field usage
- Filter fields by table
- Show inbound/outbound references
- Show unresolved references
- Show warnings
- Jump from script step to target entity
- Toggle raw XML details
- Toggle “AI summary” sections

Potential generated assets:

```text
site/
├─ index.html
├─ assets/
├─ data/
│  ├─ model.json
│  ├─ entities.json
│  ├─ references.json
│  ├─ backlinks.json
│  └─ search-index.json
```

---

## 18. Data Model Versioning

Create your own schema version.

```json
{
  "schemaVersion": "0.1.0"
}
```

This lets you evolve the JSON safely.

Versioning rules:

| Change | Version impact |
|---|---|
| Add optional field | Minor |
| Rename field | Major |
| Change meaning of field | Major |
| Add entity type | Minor |
| Change `docId` format | Major |
| Change reference model | Major |

Consider writing a JSON Schema later:

```text
schemas/fm-docgen-model.schema.json
```

This would make validation and AI tooling easier.

---

## 19. Recommended Development Phases

## Phase 1: Proof of Concept

Goal: prove the pipeline.

Inputs:

- One SaveAsXML file
- A small subset of elements

Implement:

- Parse tables
- Parse fields
- Parse scripts at a basic level
- Generate model JSON
- Generate Markdown files for tables, fields, scripts
- Generate index pages
- Generate links from fields to tables
- Generate links from tables to fields

Deliverable:

```text
docs/
├─ index.md
├─ Tables/
├─ Fields/
└─ Scripts/
```

Success criteria:

- A human can navigate from table → field → table.
- A script page lists its steps.
- The JSON model is understandable and stable.

---

## Phase 2: Reference Graph

Goal: make the docs meaningfully connected.

Implement:

- Table occurrences
- Relationships
- Layouts
- Layout-to-field references
- Script-to-field references for common script steps
- Script-to-layout references
- Script-to-script references
- Backlinks
- Unresolved references report

Success criteria:

- A field page shows where it is used.
- A script page links to fields/layouts/scripts.
- A layout page links to its table occurrence and displayed fields.
- Relationship pages link to table occurrences and join fields.

---

## Phase 3: Markdown Quality

Goal: make the Markdown output excellent.

Implement:

- Jinja templates
- Front matter
- Consistent tables
- Escaped Markdown content
- Folder indexes
- Root index
- Reports folder
- Configurable output options
- Stable filenames

Success criteria:

- Documentation is useful in a Markdown viewer.
- Documentation is useful in GitHub/GitLab/Azure DevOps.
- Documentation is useful to AI indexing tools.

---

## Phase 4: Analysis Tools

Goal: turn documentation into insight.

Implement:

- Dependency graph
- Unused/dead-code candidates
- Server compatibility warnings
- Dangerous operation report
- Global field usage report
- Field write/read analysis
- Change impact report

Success criteria:

- User can ask, “What breaks if I change this field?”
- User can ask, “Where is this table used?”
- User can ask, “Which scripts write to this field?”
- User can ask, “Which scripts are risky to run on server?”

---

## Phase 5: HTML / Vue Renderer

Goal: add a richer UI without changing the parser.

Implement:

- JSON data export optimized for frontend use
- Vue browser
- Search index
- Entity pages
- Graph views
- Filters
- Cross-reference navigation

Success criteria:

- Same model JSON can produce both Markdown and HTML.
- Vue app does not need to understand FileMaker XML.
- Renderer consumes the normalized model only.

---

## Phase 6: Diff / Version Comparison

Goal: compare two FileMaker XML exports via normalized JSON.

Implement:

```bash
fm-docgen diff old.xml new.xml --out ./diff-report
```

Compare:

- Added/removed/renamed tables
- Added/removed/changed fields
- Changed calculations
- Changed scripts
- Changed layouts
- Changed relationships
- Changed custom functions
- Changed value lists
- Changed privilege sets

Success criteria:

- Output is more meaningful than raw XML diff.
- Diff report links to affected documentation pages.
- Potential change impact is visible.

---

## 20. Suggested Python Libraries

| Library | Use |
|---|---|
| `lxml` | XML parsing |
| `pydantic` | Typed models and validation |
| `jinja2` | Markdown/HTML templates |
| `python-slugify` | Safe filenames |
| `rich` | Pretty CLI output |
| `typer` | CLI framework |
| `pytest` | Tests |
| `networkx` | Optional dependency graph analysis |
| `orjson` | Fast JSON output |

Example dependencies:

```toml
[project]
dependencies = [
  "lxml",
  "pydantic",
  "jinja2",
  "python-slugify",
  "typer",
  "rich",
  "orjson"
]
```

---

## 21. Important Design Decisions

### 21.1 Should Markdown be the canonical output?

No.

Markdown should be one renderer.

Canonical output should be the normalized JSON model.

### 21.2 Should links be created during parsing?

No.

Parsing should extract facts.

Normalization and analysis should create references.

Rendering should turn references into links.

### 21.3 Should every script step become a standalone entity?

Probably yes, at least internally.

It makes backlinks and precise references much easier.

Markdown does not need one file per script step, but the JSON model can still treat them as entities.

### 21.4 Should calculations be fully parsed?

Not in version 1.

Start with practical reference detection:

- `TableOccurrence::Field`
- Custom function calls
- Known FileMaker functions ignored or classified
- Unresolved references reported

A full FileMaker calculation parser can come later.

### 21.5 Should raw XML be preserved?

Not fully in the model, unless needed.

But preserve enough source trace to debug extraction.

Optional:

```json
"raw": {
  "xmlSnippet": "..."
}
```

This may make JSON huge, so make it configurable.

---

## 22. Configuration File

Support a project config file:

```yaml
project:
  name: "Accounting System"

input:
  file: "./FileMakerProSaveAsXML.xml"

output:
  model: "./build/model.json"
  markdown: "./docs"

markdown:
  include_front_matter: true
  include_raw_xml_paths: false
  include_backlinks: true
  table_format: "github"

naming:
  slug_style: "safe"
  preserve_case: true

analysis:
  parse_calculations: true
  parse_script_step_text: true
  include_unresolved_references: true
```

CLI:

```bash
fm-docgen build --config fm-docgen.yaml
```

---

## 23. Testing Strategy

### 23.1 Fixture-based tests

Use tiny XML fixtures that contain known elements.

Test:

- Tables extract correctly
- Fields extract correctly
- Relationships extract correctly
- Scripts extract correctly
- References resolve correctly
- Markdown output contains expected links

### 23.2 Snapshot tests

For Markdown rendering, snapshot tests are useful.

Example:

```text
tests/snapshots/field_Acc_Transaction_Log_Type.md
```

If rendering changes, the snapshot diff shows exactly what changed.

### 23.3 Real-world regression tests

Keep anonymized or synthetic FileMaker XML exports for regression.

Use a larger sample to catch performance and parsing issues.

---

## 24. Handling Sensitive Information

FileMaker XML may include sensitive implementation details.

The tool should support redaction.

Possible redactions:

| Item | Redaction option |
|---|---|
| Account names | Replace with placeholders |
| Server paths | Hide or hash |
| External data source credentials | Always redact |
| URLs | Optional redact |
| Comments | Optional include/exclude |
| Custom function code | Optional include/exclude |
| Script step details | Optional include/exclude |

Config idea:

```yaml
security:
  redact_account_names: true
  redact_external_credentials: true
  redact_urls: false
  include_comments: true
```

---

## 25. AI-Friendly Enhancements

To make the output especially useful for AI agents:

### 25.1 Predictable headings

Use consistent headings across entity types.

Example:

```markdown
# Field: Table::Field

## Metadata
## Definition
## References
## Backlinks
## Warnings
```

### 25.2 Summary sections

Add short generated summaries.

```markdown
## AI Summary

This field belongs to the `Acc_Transaction_Log` table. It is a Number field and is used by 3 scripts, 2 layouts, and 1 relationship.
```

### 25.3 Machine-readable front matter

Keep it consistent.

### 25.4 Include JSON alongside Markdown

Place these in the output:

```text
entities.json
references.json
backlinks.json
search-index.json
```

### 25.5 Chunkable files

Avoid giant Markdown files where possible.

One entity per file is ideal for indexing.

---

## 26. Minimum Viable Product

The MVP should avoid trying to solve everything.

Build this first:

1. Parse FileMaker XML.
2. Extract base tables.
3. Extract fields.
4. Extract scripts and script steps as raw text.
5. Create normalized JSON.
6. Generate Markdown files:
   - `index.md`
   - one file per table
   - one file per field
   - one file per script
7. Link:
   - table → fields
   - field → table
8. Include raw script steps in script pages.
9. Create an unresolved/unsupported report.

MVP output:

```text
docs/
├─ index.md
├─ Tables/
│  ├─ index.md
│  └─ ExampleTable.md
├─ Fields/
│  └─ ExampleTable/
│     ├─ index.md
│     └─ ExampleField.md
├─ Scripts/
│  ├─ index.md
│  └─ ExampleScript.md
└─ Reports/
   └─ warnings.md
```

Once this works, expand references and backlinks.

---

## 27. Recommended First Implementation Sprint

### Step 1: Create CLI skeleton

```bash
fm-docgen build input.xml --out docs --model-out build/model.json
```

### Step 2: Parse enough XML to count entities

Output:

```text
Tables: 42
Fields: 812
Scripts: 235
Layouts: 110
```

### Step 3: Build the first JSON model

Include tables, fields, and scripts only.

### Step 4: Build Markdown renderer

Use Jinja templates.

### Step 5: Add link resolver

Generate table-field links.

### Step 6: Add reports

Start with:

- `summary.md`
- `warnings.md`
- `unresolved-references.md`

### Step 7: Test on a real FileMaker XML export

Document what is missing.

---

## 28. Example Internal Flow

```python
def build(input_xml: Path, output_dir: Path, model_out: Path):
    source_info = detect_source_info(input_xml)

    raw = parse_savexml(input_xml)

    model = normalize(raw, source_info=source_info)

    model = analyze_references(model)
    model = generate_backlinks(model)
    model = validate_model(model)

    write_model_json(model, model_out)

    render_markdown(model, output_dir)
```

---

## 29. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| FileMaker XML changes between versions | Version-detect and isolate parser logic |
| XML files are huge | Use streaming parser or staged extraction |
| References are ambiguous | Store confidence and unresolved references |
| Markdown links break | Centralize link resolver |
| File names collide | Use doc IDs and collision-safe slug registry |
| Calculations are hard to parse | Start with simple reference extraction |
| Output is too noisy | Add config flags and summary/detail levels |
| Sensitive details leak | Add redaction config |
| AI indexing is inconsistent | Use predictable headings and front matter |

---

## 30. Long-Term Vision

This can become more than a documentation generator.

Possible future capabilities:

- FileMaker solution browser
- AI-ready documentation corpus
- Dependency graph
- Change impact analyzer
- Dead code detector
- Server compatibility checker
- Security/privilege report
- Version comparison tool
- Git-friendly FileMaker schema snapshots
- Vue-based interactive documentation site
- “Ask questions about this FileMaker system” knowledge base

The important architectural decision is to make the normalized JSON model the center of the system.

Markdown is just the first renderer.
