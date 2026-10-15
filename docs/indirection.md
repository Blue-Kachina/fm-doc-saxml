# Names written in text (indirection)

FileMaker stores a direct reference by its internal ID: a field in a calculation, the script a Perform Script step runs, the layout of a Go to Layout step. When you rename the target, FileMaker updates these for you.

It does **not** update a name written in text:

```
GetField ( "Invoices::Total" )
Set Field By Name [ $targetField ; ... ]
Perform Script [ By name: $callbackScriptName ]
Go to Layout [ $type & " Advanced Search tabs" ]
Go to Object [ "btnSave" ]
ExecuteSQL ( "SELECT Total FROM Invoices WHERE id = ?" ; "" ; "" ; $id )
If [ Get ( LayoutName ) = "Invoice Detail" ]
```

fm-saxml finds every such place (a **site**), works out which entity each one can name, and says how sure it is. This is what to check before renaming anything to fit a naming standard.

## Where it shows up

| Output | What you get |
|---|---|
| `Reports/indirection.md` | Every site by class, a rename-risk ranking (most-named entities first), broken names, and the sites that get their name from data |
| `Reports/summary.md` | Counts by class |
| Field, table occurrence, layout, script, value list and layout object pages | **Referenced by Name**: places that would break if this were renamed, and places that capture its name safely |
| Script, field, layout, layout object and custom function pages | **Names Used in Text**: the sites in this script or calculation |
| Custom function pages | What the function does with names (wraps GetField, captures a field name, looks up a script by ID, ...) |
| `model.json` | `indirectionSites`, plus `via: "byName"` and `siteDocId` on the references they produce |
| `Reports/warnings.md` | `BYNAME_TARGET_MISSING` for a name that matches nothing, `BYNAME_OPAQUE` with the count of sites whose name comes from data |
| `fm-saxml rename-check` | The impact of renaming one entity, or a whole plan of renames |
| `fm-saxml diff` | **Names Still Using an Old Name**: text that still uses the old name after a rename |
| WebMCP (`--webmcp`) | `find_indirection`, `rename_impact`, and `includeByName` on `find_references` |

By-name references count as uses: a field only ever used through `GetField ( "T::f" )` is not reported as `UNUSED_FIELD_CANDIDATE`. They are kept out of the **Used By** tables on each page, which list direct references only, and appear in their own **Referenced by Name** section instead.

## Classes

| Class | | Breaks on rename? | Example |
|---|---|---|---|
| **A** | Safe capture | No | `GetFieldName ( Invoices::Total )`, `Get ( ScriptName )`, `SQLTable ( Invoices::id )`: the name comes from a real reference |
| **A′** | ID-based | No (yes on delete and recreate) | `getScriptName ( 387 )`, `SELECT FieldName FROM FileMaker_Fields WHERE FieldID = ?` |
| **B** | Hardcoded | **Yes** | `GetField ( "Invoices::Total" )`, `Go to Object [ "btnSave" ]` |
| **C** | Dynamic, traced | Yes, when the name started as text | `Set Field By Name [ $target ]` where a caller passes `"Invoices::Total"` |
| **D** | Opaque | Unknown | The name comes from a field, a record, an API response, or a parameter no caller in this file supplies |
| **E** | Broken | Already broken | A name that matches nothing in this file |

Each candidate also says where the name came from: `literal` (written as text: breaks), `pattern` (a name built at run time, like `$type & " tabs"`, matched against the catalog: breaks), `capture`, `self` or `id` (follow a rename).

Confidence is `parsed` when the name is written at the site itself and `inferred` when it was traced through variables or parameters, matched by a pattern, or is a field name without its table (`GetField ( "Total" )` uses whatever table the current layout is on).

## What is traced

- **Sinks**: `GetField`, `Evaluate`, `ExecuteSQL`, `GetLayoutObjectAttribute`, `ValueListItems`, `FieldType`, `FieldStyle`, `FieldRepetitions`, `FieldBounds`, `FieldComment`, `FieldNames`, `FieldIDs`, `LayoutObjectNames`; comparisons with `Get ( LayoutName )`, `Get ( LayoutTableName )`, `Get ( ScriptName )`, `Get ( ActiveFieldName )`, `Get ( ActiveFieldTableName )` and `Get ( ActiveLayoutObjectName )`; Set Field By Name; Perform Script and Perform Script on Server **By name**; Go to Layout by name; Go to Object, Refresh Object and Refresh Portal by object name. Disabled steps are included, with a note.
- **Variables**: every value a `$local` is given in its script, and a `$$global` anywhere in the file. A `$local` that is never set in its script is assumed to be unpacked from the script parameter under the same key (as `#Assign`-style custom functions do).
- **Script parameters**: `JSONGetElement ( Get ( ScriptParameter ) ; "key" )` (and `JSONGetElement_Safe`, or a variable holding the parameter) is traced to the `"key"` of every caller's parameter: Perform Script steps, buttons, and script triggers on layouts and objects. The callback convention, `[ "callbackScriptName" ; Get ( ScriptName ) ]`, resolves to the calling scripts.
- **Custom functions**: a function whose parameter reaches a sink (`ReadField ( name ) = GetField ( name )`) makes each call a site. A function that passes a parameter to `GetFieldName` (`SQLField`, `SQLTable`) captures the name safely. Functions named like `getScriptName` / `getLayoutName` / `getTableName` / `getFieldNameFromID` that use `ScriptIDs`, `LayoutIDs`, `TableIDs` or the `FileMaker_Fields` table resolve a literal ID to the entity.
- **Text building**: `&`, `If`, `Case`, `Choose`, `Let`, `List`, `GetValue` and the other value functions, `Substitute` (including SQL templates such as `Substitute ( "SELECT ~f FROM ~t" ; [ "~f" ; SQLField ( T::f ) ] ; ... )`), `JSONSetElement`, `Quote` and `Trim`.
- **SQL**: the table after `FROM`, `JOIN`, `UPDATE` or `INTO` is matched against table occurrence names, and the query's column names against that table's fields. `FileMaker_Tables` and `FileMaker_Fields` are system tables (A′).

A pattern that matches more than 25 entities is reported as too broad rather than listed.

## rename-check

```bash
fm-saxml rename-check Export.xml "Invoices::Total" "Post Invoice" btnSave
fm-saxml rename-check Export.xml --plan renames.csv --out rename-check.md --strict
```

Names can be `Table::Field` (a table occurrence works too), or the name of a script, layout, table occurrence, value list or layout object. `--kind field|script|layout|to|valuelist|object` narrows a name that several kinds share. The input can also be a `model.json` from `fm-saxml parse`.

A plan is a CSV, one rename per line: `old,new[,kind]` (a header row `old,new,kind` is optional). For each rename it also checks the **new** name. It flags an existing entity of the same kind that already has that name, and any place that already uses the new name in text: after the rename, that place would start pointing at this entity.

For each entity it prints how many places would break, how many capture the name safely, how many direct references FileMaker updates by itself, and how many places take a name of the same kind from data (check those by hand). `--out` writes the full list with the trace for each. `--strict` exits with status 1 when anything would break, for CI.

## Limits

- Names used from outside the file are invisible: the Data API, OData, ODBC/JDBC, PHP, plug-ins, web viewers, `fmp://` URLs from other apps, server schedules that run scripts by name.
- Names stored in records (configuration tables, integration mappings) can't be resolved. These sites are class D.
- Variables are traced without regard to step order or branches: every value counts.
- Window names, and layouts chosen by number (`Go to Layout [ by number ]`), aren't tracked. Layout numbers break when layouts are reordered, not renamed.
- In a multi-file build each file is analyzed on its own. A name that refers into another file of the solution isn't linked to it.
