# WebMCP question set

Plain-English questions an agent should be able to answer from a `--webmcp` viewer, each
with the tool call(s) that answer it. When a question comes up that none of these covers,
add a pipeline step or a tool for the *kind* of question, not a one-off, and add it here.

Names below (`Invoices`, `Invoice Post`, ...) stand for the solution's own. In a
multi-file solution add `file` to scope a call to one file.

Reference kinds (`relationshipType`): `usesField`, `usesScript`, `triggersScript`,
`usesLayout`, `opensLayout`, `usesValueList`, `usesCustomFunction`, `usesTableOccurrence`,
`usesCustomMenu`, `basedOnTableOccurrence`, `basedOnBaseTable`, `joinsTo`, `looksUp`,
`sortsBy`, `summarizes`, `grantedTo`, `assignedPrivilegeSet`, `contains` (structural).

## Acceptance (each is one call)

| # | Question | Call |
|---|---|---|
| A1 | Show me all references to fields from table X | `find_references({targetType:"field", parentDocId:"table:X", direction:"incoming", groupBy:"target"})` |
| A2 | Show me all the hidden fields on layout X | `query_entities({type:"layoutObject", where:[{field:"layoutDocId",op:"eq",value:"layout:X"},{field:"isField",op:"eq",value:true},{any:[{field:"hasHideCondition",op:"eq",value:true},{field:"inPanel",op:"eq",value:true}]}]})`. On X's page: `list_objects_on_this_layout({fieldsOnly:true, hidden:"any"})` |
| A3 | Which accounts can run script X? | `who_can_access({docId:"script:X", action:"run"})` |
| A4 | Which accounts can access layout Y? | `who_can_access({docId:"layout:Y", action:"view"})` |
| A5 | Everything that eventually calls script X | `traverse({from:"script:X", direction:"incoming", relationshipTypes:["usesScript","triggersScript"]})` |
| A6 | Privilege sets that can run a script containing a Delete Record step | `query({steps:[{from:"scriptStep"},{where:[{field:"name",op:"eq",value:"Delete Record/Request"}]},{join:{on:"scriptDocId",as:"script"}},{joinAccess:{on:"script.docId",action:"run",as:"access"}},{groupBy:"access.name",agg:"list"}]})` |

## Impact and dead code

| # | Question | Call |
|---|---|---|
| 1 | What breaks if I rename `Invoices::Total`? | `find_references({docId:"field:Invoices::Total"})` |
| 2 | Which scripts does nothing call? | `find_unreferenced({type:"script"})` (read the caveat: calls by name, other files, schedules) |
| 3 | Unused value lists / custom functions / table occurrences | `find_unreferenced({type:"valueList"})`, `{type:"customFunction"}`, `{type:"tableOccurrence"}` |
| 4 | Fields no layout, script or calculation uses | `find_unreferenced({type:"field"})` |

## Scripts and steps

| # | Question | Call |
|---|---|---|
| 5 | Everything script X eventually runs | `traverse({from:"script:X", direction:"outgoing", relationshipTypes:["usesScript"]})` |
| 6 | Scripts that call each other in a loop | `traverse({from:"script:X", relationshipTypes:["usesScript"]})`: see `cycleBackToStart` |
| 7 | Every Set Field step that sets `Invoices::Total` | `find_script_steps({stepName:"Set Field", targetDocId:"field:Invoices::Total"})` |
| 8 | Where is Perform Script on Server used? | `find_script_steps({stepName:"Perform Script on Server"})` |
| 9 | Scripts that turn user abort on | `find_script_steps({stepName:"Allow User Abort", textContains:"On"})` |
| 10 | Disabled steps | `find_script_steps({enabled:false})` |
| 11 | Scripts with more than 200 steps | `query_entities({type:"script", where:[{field:"stepCount",op:"gt",value:200}]})` |
| 12 | Steps that commit without error capture before them in the script | `query({steps:[{from:"scriptStep"},{where:[{field:"name",op:"eq",value:"Set Error Capture"}]},{groupBy:"scriptDocId"}]})` vs. the same for `Commit Records/Requests`. A step-order operator would make this one call: add one if it comes up often |

## Schema and calculations

| # | Question | Call |
|---|---|---|
| 13 | Unstored calculations that use related fields | `query_entities({type:"field", where:[{field:"stored",op:"eq",value:false},{field:"calculation",op:"contains",value:"::"}]})` |
| 14 | Global fields | `query_entities({type:"field", where:[{field:"global",op:"eq",value:true}]})` |
| 15 | Auto-enter calculations that overwrite existing values | `query_entities({type:"field", where:[{field:"autoEnter.overwriteExisting",op:"eq",value:true}]})` |
| 16 | Where is `ExecuteSQL` used? | `search_entities({query:"ExecuteSQL", deep:true})` and `find_script_steps({textContains:"ExecuteSQL"})` |
| 17 | Where is layout "Invoice Detail" named in a calculation? | `search_entities({query:"\"Invoice Detail\"", deep:true})` (quotes included: a name typed as text) |

## Layouts and triggers

| # | Question | Call |
|---|---|---|
| 18 | Every OnRecordCommit trigger | `query_entities({type:"layoutObject", where:[{field:"triggerEvents",op:"contains",value:"OnRecordCommit"}]})` and the same with `type:"layout"` |
| 19 | Layouts with OnLayoutEnter | `query_entities({type:"layout", where:[{field:"triggerEvents",op:"contains",value:"OnLayoutEnter"}]})` |
| 20 | Layouts based on table occurrence X | `query_entities({type:"layout", where:[{field:"baseTableOccurrenceDocId",op:"eq",value:"to:X"}]})` |
| 21 | What can a user reach from layout X's buttons and triggers? | `traverse({from:"layout:X", direction:"outgoing", relationshipTypes:["triggersScript","usesScript","usesLayout"]})` |

## Security

| # | Question | Call |
|---|---|---|
| 22 | Who can delete records in table X? | `who_can_access({docId:"table:X", action:"delete"})` |
| 23 | Which accounts have Full Access? | `who_can_access({docId:"script:<any>", action:"modify"})` filtered on `reason:"fullAccess"`, or `query_entities({type:"account", where:[{field:"privilegeSetDocId",op:"eq",value:"privilegeSet:[Full Access]"}]})` |
| 24 | Who has fmrest / fmwebdirect? | `query_entities({type:"extPriv", where:[{field:"name",op:"in",value:["fmrest","fmwebdirect"]}], fields:["privilegeSetDocIds"]})` |
| 25 | Full-access scripts a restricted account can start | `query({steps:[{from:"script"},{where:[{field:"runWithFullAccess",op:"eq",value:true}]},{joinAccess:{action:"run",as:"access"}},{where:[{field:"access.name",op:"ne",value:"[Full Access]"}]}]})` |
| 26 | What can account `ui` run? | `what_can_access({account:"ui", type:"script"})` |

## Relationships and files

| # | Question | Call |
|---|---|---|
| 27 | Relationships that delete related records | `query_entities({type:"relationship", where:[{any:[{field:"options.left.delete",op:"eq",value:true},{field:"options.right.delete",op:"eq",value:true}]}]})` |
| 28 | Table occurrences of base table X | `query_entities({type:"tableOccurrence", where:[{field:"baseTableDocId",op:"eq",value:"table:X"}]})` |
| 29 | Path between table occurrences A and B | `traverse({from:"to:A", to:"to:B", direction:"both", relationshipTypes:["joinsTo"]})` |
| 30 | Everything that references file Y | `query({steps:[{from:"reference"},{where:[{field:"externalFile",op:"eq",value:"Y"}]}]})` |
