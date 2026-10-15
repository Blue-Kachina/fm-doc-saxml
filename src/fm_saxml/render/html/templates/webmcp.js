/* fm-saxml viewer: WebMCP tools over the solution's model (written with --webmcp).
 *
 * A classic script (file:// pages can't fetch() or import local modules). It loads the
 * model in shards from _viewer/data/<file>/*.js on demand, answers questions about it,
 * and registers the answers as WebMCP tools when the browser supports WebMCP
 * (document.modelContext, formerly navigator.modelContext). The same tools are always
 * on window.FMDocs.tools, so any agent driving the browser, and the viewer's own search
 * box, can use them.
 *
 * Query tools show their results in the viewer (#/results?q=...) unless called with
 * display:false. No tool changes data, and none runs code an agent writes.
 */
(function () {
    'use strict';
    const FM = window.FMDocs;
    const DATA = 'data';
    const DEFAULT_LIMIT = 50;
    const MAX_LIMIT = 1000;

    // docId prefix -> entity type (normalize/ids.py)
    const PREFIX_TYPES = {
        table: 'table', field: 'field', to: 'tableOccurrence', relationship: 'relationship', layout: 'layout',
        layoutObject: 'layoutObject', script: 'script', scriptStep: 'scriptStep', customFunction: 'customFunction',
        valueList: 'valueList', privilegeSet: 'privilegeSet', account: 'account', extPriv: 'extPriv',
        customMenu: 'customMenu', customMenuSet: 'customMenuSet', theme: 'theme', fileRef: 'fileRef', variable: 'variable',
    };
    const TYPE_LABELS = {
        table: 'Tables', field: 'Fields', tableOccurrence: 'Table occurrences', relationship: 'Relationships',
        layout: 'Layouts', layoutObject: 'Layout objects', script: 'Scripts', scriptStep: 'Script steps',
        customFunction: 'Custom functions', valueList: 'Value lists', privilegeSet: 'Privilege sets',
        account: 'Accounts', extPriv: 'Extended privileges', customMenu: 'Custom menus',
        customMenuSet: 'Custom menu sets', theme: 'Themes', fileRef: 'File references', variable: 'Variables',
    };
    const TYPES = Object.keys(TYPE_LABELS);
    // A child entity and its parent's docId field: steps sit in a script, fields in a table, ...
    const PARENT_FIELD = { scriptStep: 'scriptDocId', field: 'baseTableDocId', layoutObject: 'layoutDocId' };
    const PARENT_TYPE = { scriptStep: 'script', field: 'table', layoutObject: 'layout' };
    // Edges that only say "B is part of A" (a table's fields, a script's steps), not a use of B.
    const STRUCTURAL = new Set(['contains']);

    // ---- Data registry (called by the data scripts) ---------------------------
    const store = { catalog: {}, shards: {}, byId: {}, refs: {}, access: {}, waiting: {} };
    FM.catalog = (file, data) => { store.catalog[file] = data; settle(`${file}|catalog`); };
    FM.shard = (file, type, records) => {
        for (const r of records) Object.defineProperty(r, '_file', { value: file, enumerable: false });
        store.shards[`${file}|${type}`] = records;
        const ids = store.byId[file] || (store.byId[file] = new Map());
        for (const r of records) ids.set(r.docId, r);
        settle(`${file}|${type}`);
    };
    FM.refs = (file, data) => {
        const rows = data.rows.map((row) => Object.fromEntries(data.cols.map((c, i) => [c, row[i]])));
        store.refs[file] = { rows, external: data.external || {}, byTarget: index(rows, 'target'), bySource: index(rows, 'source'),
            bySourceParent: index(rows.filter((r) => r.sourceParent), 'sourceParent') };
        settle(`${file}|refs`);
    };
    FM.access = (file, data) => { store.access[file] = data; settle(`${file}|access`); };

    function index(rows, key) {
        const m = new Map();
        for (const r of rows) { const k = r[key]; if (!m.has(k)) m.set(k, []); m.get(k).push(r); }
        return m;
    }
    function settle(key) { const w = store.waiting[key]; if (w) { delete store.waiting[key]; w.resolve(); } }

    const loads = {};
    function load(file, name) {
        const key = `${file}|${name}`;
        if (!loads[key]) {
            loads[key] = new Promise((resolve, reject) => {
                store.waiting[key] = { resolve };
                const s = document.createElement('script');
                s.src = `_viewer/${DATA}/${encodeURIComponent(file)}/${encodeURIComponent(name)}.js`;
                s.onload = () => { s.remove(); if (store.waiting[key]) { delete store.waiting[key]; resolve(); } };
                s.onerror = () => { s.remove(); delete loads[key]; reject(new Error(`Could not load ${s.src}`)); };
                document.head.appendChild(s);
            });
        }
        return loads[key];
    }

    const files = () => (FM.data && FM.data.webmcp && FM.data.webmcp.files) || [];
    function pickFiles(file) {
        const all = files();
        if (file === undefined || file === null || file === '') return all;
        const want = String(file).toLowerCase();
        const hit = all.filter((f) => f.key.toLowerCase() === want || f.label.toLowerCase() === want
            || f.dir.toLowerCase() === want);
        if (!hit.length) throw new ToolError(`Unknown file '${file}'.`, { validFiles: all.map((f) => f.label) });
        return hit;
    }
    async function catalogs(file) {
        const fs = pickFiles(file);
        await Promise.all(fs.map((f) => load(f.key, 'catalog')));
        return fs.map((f) => ({ file: f, catalog: store.catalog[f.key] }));
    }
    async function records(type, file) {
        checkType(type);
        const out = [];
        for (const { file: f, catalog } of await catalogs(file)) {
            if (!catalog.counts[type]) continue;
            await load(f.key, type);
            out.push(...store.shards[`${f.key}|${type}`]);
        }
        return out;
    }
    async function refs(file) {
        const fs = pickFiles(file);
        await Promise.all(fs.map((f) => load(f.key, 'refs')));
        return fs.map((f) => ({ file: f, refs: store.refs[f.key] }));
    }
    async function access(file) {
        const fs = pickFiles(file);
        await Promise.all(fs.map((f) => load(f.key, 'access')));
        return fs.map((f) => ({ file: f, access: store.access[f.key] }));
    }
    const typeOf = (docId) => PREFIX_TYPES[String(docId).split(':', 1)[0]] || null;
    async function entity(docId, file) {
        const type = typeOf(docId);
        if (!type) return [];
        const found = [];
        for (const f of pickFiles(file)) {
            const cat = (await catalogs(f.key))[0].catalog;
            if (!cat.counts[type]) continue;
            await load(f.key, type);
            const r = store.byId[f.key] && store.byId[f.key].get(docId);
            if (r) found.push(r);
        }
        return found;
    }
    function fileLabel(key) { const f = files().find((x) => x.key === key); return f ? f.label : key; }

    // ---- Errors & schemas -----------------------------------------------------
    class ToolError extends Error {
        constructor(message, details) { super(message); this.details = details || {}; }
    }
    function checkType(type) {
        if (!TYPE_LABELS[type]) throw new ToolError(`Unknown entity type '${type}'.`, { validTypes: TYPES });
    }
    const S = {
        str: (description, extra) => ({ type: 'string', description, ...extra }),
        int: (description) => ({ type: 'integer', description, minimum: 1 }),
        bool: (description) => ({ type: 'boolean', description }),
        file: { type: 'string', description: 'Only this file of a multi-file solution (its name). Default: every file.' },
        limit: { type: 'integer', minimum: 1, maximum: MAX_LIMIT, description: `Max items returned (default ${DEFAULT_LIMIT}).` },
        display: { type: 'boolean', description: 'Also show the results in the viewer, grouped by type (default true).' },
        title: { type: 'string', description: 'Heading for the results in the viewer, e.g. the question being answered.' },
        type: { type: 'string', enum: TYPES, description: 'Entity type.' },
        where: {
            type: 'array',
            description: 'Conditions, all of which must hold. Each is {field, op, value}, {any:[conditions]} or {not:condition}. '
                + 'field is a record key or dotted path (storage.indexed, autoEnter.type); call describe_schema for the keys. '
                + 'ops: eq, ne, contains (case-insensitive), startsWith, regex, in, exists, missing, gt, gte, lt, lte, isEmpty. '
                + 'On a list, eq/contains/regex hold if any element matches.',
            items: { type: 'object' },
        },
    };

    // ---- Matching -------------------------------------------------------------
    function getPath(obj, path) {
        let cur = obj;
        for (const part of String(path).split('.')) {
            if (cur === null || cur === undefined) return undefined;
            if (Array.isArray(cur) && !/^\d+$/.test(part)) {
                const vals = cur.map((c) => (c === null || c === undefined ? undefined : c[part])).flat();
                cur = vals.filter((v) => v !== undefined);
                continue;
            }
            cur = cur[part];
        }
        return cur;
    }
    const lower = (v) => String(v).toLowerCase();
    function compile(cond) {
        if (cond && Array.isArray(cond.any)) { const cs = cond.any.map(compile); return (r) => cs.some((c) => c(r)); }
        if (cond && Array.isArray(cond.all)) { const cs = cond.all.map(compile); return (r) => cs.every((c) => c(r)); }
        if (cond && cond.not) { const c = compile(cond.not); return (r) => !c(r); }
        if (!cond || typeof cond.field !== 'string') throw new ToolError('Each condition needs a "field" (or "any"/"all"/"not").', { condition: cond });
        const op = cond.op || 'eq';
        const v = cond.value;
        let test;
        switch (op) {
            case 'eq': test = (x) => x === v || (typeof x === 'string' && typeof v === 'string' && lower(x) === lower(v)); break;
            case 'ne': return (r) => { const x = getPath(r, cond.field); return Array.isArray(x) ? !x.some((y) => y === v) : x !== v; };
            case 'contains': test = (x) => x !== null && x !== undefined && typeof x !== 'object' && lower(x).includes(lower(v)); break;
            case 'startsWith': test = (x) => typeof x === 'string' && lower(x).startsWith(lower(v)); break;
            case 'regex': {
                let re;
                try { re = new RegExp(v, cond.flags === undefined ? 'i' : cond.flags); } catch (e) { throw new ToolError(`Bad regex: ${e.message}`); }
                test = (x) => typeof x === 'string' && re.test(x); break;
            }
            case 'in': { const set = (Array.isArray(v) ? v : [v]).map((x) => (typeof x === 'string' ? lower(x) : x)); test = (x) => set.includes(typeof x === 'string' ? lower(x) : x); break; }
            case 'gt': test = (x) => x > v; break;
            case 'gte': test = (x) => x >= v; break;
            case 'lt': test = (x) => x < v; break;
            case 'lte': test = (x) => x <= v; break;
            case 'exists': return (r) => { const x = getPath(r, cond.field); return x !== undefined && x !== null && x !== false && !(Array.isArray(x) && !x.length); };
            case 'missing': return (r) => { const x = getPath(r, cond.field); return x === undefined || x === null || x === false || (Array.isArray(x) && !x.length); };
            case 'isEmpty': return (r) => { const x = getPath(r, cond.field); return x === undefined || x === null || x === '' || (Array.isArray(x) && !x.length); };
            default: throw new ToolError(`Unknown op '${op}'.`, { validOps: ['eq', 'ne', 'contains', 'startsWith', 'regex', 'in', 'exists', 'missing', 'isEmpty', 'gt', 'gte', 'lt', 'lte'] });
        }
        return (r) => { const x = getPath(r, cond.field); return Array.isArray(x) ? x.some(test) : test(x); };
    }
    function compileWhere(where) {
        if (!where) return () => true;
        if (!Array.isArray(where)) where = [where];
        const cs = where.map(compile);
        return (r) => cs.every((c) => c(r));
    }
    function checkFields(type, where, sample) {
        // Unknown keys are an error (listing the real ones), not a silent empty result.
        if (!sample.length || !where) return;
        const keys = new Set();
        for (const r of sample.slice(0, 500)) for (const k of Object.keys(r)) keys.add(k);
        const walk = (c) => {
            if (!c) return;
            if (Array.isArray(c)) return c.forEach(walk);
            if (c.any) return walk(c.any);
            if (c.all) return walk(c.all);
            if (c.not) return walk(c.not);
            const head = String(c.field).split('.')[0];
            if (!keys.has(head) && !COMMON_KEYS.has(head)) {
                throw new ToolError(`'${type}' records have no field '${head}'.`, { validFields: [...keys].sort() });
            }
        };
        walk(where);
    }
    const COMMON_KEYS = new Set(['docId', 'entityType', 'name', 'path']);

    // ---- Result items ---------------------------------------------------------
    function detailOf(r) {
        switch (r.entityType) {
            case 'field': return [r.dataType, r.fieldType, r.global ? 'global' : null, r.stored === false ? 'unstored' : null].filter(Boolean).join(' · ');
            case 'scriptStep': return r.text;
            case 'layoutObject': return [r.objectType, r.fieldName, r.hasHideCondition ? 'hide when: ' + r.hideCondition : null,
                r.shownIn ? 'in ' + r.shownIn.map((c) => c.kind).join(' › ') : null].filter(Boolean).join(' · ');
            case 'script': return r.folderPath || '';
            case 'layout': return r.baseTableOccurrence ? 'on ' + r.baseTableOccurrence : '';
            case 'tableOccurrence': return r.baseTable ? 'of ' + r.baseTable : '';
            case 'account': return [r.accountType, r.privilegeSetName, r.enabled === false ? 'disabled' : null].filter(Boolean).join(' · ');
            case 'customFunction': return r.parameters ? `(${r.parameters.join('; ')})` : '';
            case 'valueList': return r.listType || '';
            default: return '';
        }
    }
    function itemOf(r, extra) {
        const type = r.entityType;
        const item = {
            file: fileLabel(r._file), docId: r.docId, type,
            name: type === 'scriptStep' ? `${r.stepNumber}. ${r.name}`
                : type === 'layoutObject' ? r.name || r.label || r.fieldName || `${r.objectType || 'Object'} #${r.objectId}`
                    : r.name || r.docId,
            path: r.path || null, detail: detailOf(r) || undefined,
        };
        if (type === 'scriptStep') item.step = r.stepNumber;
        const pf = PARENT_FIELD[type];
        if (pf && r[pf]) {
            item.parent = { docId: r[pf], type: PARENT_TYPE[type],
                name: type === 'scriptStep' ? r.scriptName : type === 'field' ? r.table : r.layoutName };
            if (type === 'scriptStep') item.parent.path = r.path;
        }
        return Object.assign(item, extra || {});
    }
    function limitOf(args) { return Math.min(Math.max(1, args.limit || DEFAULT_LIMIT), MAX_LIMIT); }
    function page(items, args, more) {
        const limit = limitOf(args);
        const out = { total: items.length, items: items.slice(0, limit) };
        if (items.length > limit) out.truncated = true;
        return Object.assign(out, more || {});
    }
    function project(r, fields) {
        if (!fields || !fields.length) return undefined;
        return Object.fromEntries(fields.map((f) => [f, getPath(r, f)]));
    }

    // ---- Tools ----------------------------------------------------------------
    const tools = {};
    const QUERY_TOOLS = new Set();
    function tool(name, description, properties, run, opts) {
        opts = opts || {};
        const schema = { type: 'object', properties, additionalProperties: false };
        if (opts.required) schema.required = opts.required;
        if (opts.query) {
            QUERY_TOOLS.add(name);
            properties.display = S.display;
            properties.title = S.title;
        }
        tools[name] = { name, description, inputSchema: schema, run, readOnly: !opts.changesView && !opts.query, query: !!opts.query,
            displayAs: opts.displayAs || null };
    }

    tool('describe_schema',
        'Lists the entity types in this FileMaker solution with their counts and, for one type, every queryable field '
        + 'with example values. Call it before query_entities or query to learn the field names.',
        { type: S.type, file: S.file },
        async (args) => {
            const cats = await catalogs(args.file);
            const counts = {};
            for (const { catalog } of cats) for (const [t, n] of Object.entries(catalog.counts)) counts[t] = (counts[t] || 0) + n;
            if (!args.type) {
                return { types: TYPES.filter((t) => counts[t]).map((t) => ({ type: t, label: TYPE_LABELS[t], count: counts[t] })),
                    note: 'Pass type to see its fields. References are queried with find_references / traverse, access with who_can_access.' };
            }
            const recs = await records(args.type, args.file);
            const fields = {};
            for (const r of recs.slice(0, 2000)) {
                for (const [k, v] of Object.entries(r)) {
                    const f = fields[k] || (fields[k] = { field: k, kind: Array.isArray(v) ? 'list' : v === null ? 'null' : typeof v, examples: [] });
                    const ex = typeof v === 'object' ? JSON.stringify(v).slice(0, 120) : v;
                    if (f.examples.length < 3 && !f.examples.includes(ex)) f.examples.push(ex);
                }
            }
            return { type: args.type, count: counts[args.type] || 0, fields: Object.values(fields) };
        });

    tool('get_solution_overview',
        'Overview of the documented FileMaker solution: its files, how many of each kind of entity each has, '
        + 'when the docs were generated and whether secrets were scrubbed.',
        {},
        async () => {
            const cats = await catalogs();
            return {
                title: FM.data.title, generatedAt: FM.data.generatedAt,
                files: cats.map(({ file, catalog }) => ({ file: file.label, folder: file.dir || '.', scrubbed: catalog.scrubbed,
                    references: catalog.references, counts: catalog.counts })),
            };
        });

    tool('get_current_page',
        'The page the user is looking at in the viewer: its path, and for an entity page the entity\'s full record '
        + '(every attribute, as queryable data).',
        {},
        async () => {
            const path = FM.ui ? FM.ui.currentPath() : null;
            if (!path) return { path: null };
            if (path.startsWith('results?')) return { path, results: currentResults };
            const page = FM.pages[path];
            const meta = (page && page.meta) || {};
            const out = { path, title: document.title, entityType: meta.entityType || null, docId: meta.docId || null };
            if (meta.docId) {
                const f = fileForPath(path);
                const found = await entity(meta.docId, f ? f.key : undefined);
                if (found.length) out.record = found[0];
            }
            return out;
        });

    tool('search_entities',
        'Finds entities by name (and, with deep:true, by comment, calculation or step text) across the whole solution. '
        + 'Matching is case-insensitive and on any part of the text.',
        { query: S.str('Text to look for.'), types: { type: 'array', items: S.type, description: 'Only these entity types.' },
            deep: S.bool('Also search comments, calculations and script step text (slower).'), file: S.file, limit: S.limit },
        async (args) => {
            const q = lower(args.query || '').trim();
            if (!q) throw new ToolError('query is empty.');
            const want = args.types && args.types.length ? new Set(args.types) : null;
            if (want) want.forEach(checkType);
            const hits = [];
            for (const { file, catalog } of await catalogs(args.file)) {
                for (const [docId, type, name, path] of catalog.index) {
                    if ((!want || want.has(type)) && lower(name).includes(q)) {
                        hits.push({ file: file.label, docId, type, name, path });
                    }
                }
            }
            if (args.deep) {
                const seen = new Set(hits.map((h) => h.file + '|' + h.docId));
                const types = want ? [...want] : TYPES;
                for (const type of types) {
                    for (const r of await records(type, args.file)) {
                        if (seen.has(fileLabel(r._file) + '|' + r.docId)) continue;
                        const text = [r.comment, r.calculation, r.text, r.hideCondition, r.tooltip,
                            ...(r.calculations || []).map((c) => c.text)].filter(Boolean).join('\n');
                        if (text && lower(text).includes(q)) hits.push(itemOf(r));
                    }
                }
            }
            return page(hits, args, { query: args.query });
        }, { query: true, required: ['query'] });

    tool('query_entities',
        'Filters the entities of one type by their attributes, e.g. unstored calculation fields, global fields, '
        + 'layouts based on a table occurrence, layout objects with a hide condition. Call describe_schema(type) for the fields.',
        { type: S.type, where: S.where, file: S.file, fields: { type: 'array', items: { type: 'string' }, description: 'Also return these fields of each match.' }, limit: S.limit },
        async (args) => {
            const recs = await records(args.type, args.file);
            checkFields(args.type, args.where, recs);
            const match = compileWhere(args.where);
            const hits = recs.filter(match).map((r) => itemOf(r, args.fields ? { fields: project(r, args.fields) } : null));
            return page(hits, args);
        }, { query: true, required: ['type'] });

    tool('find_script_steps',
        'Finds script steps: by step name (e.g. "Set Field", "Perform Script on Server"), by text in the step as FileMaker '
        + 'shows it, by regex, by the script or script folder they are in, or by what they act on (targetDocId, e.g. '
        + 'every Set Field step that sets field:Invoices::Total).',
        { stepName: S.str('Exact step name, case-insensitive, e.g. "Set Field".'), textContains: S.str('Text in the step line.'),
            regex: S.str('Regex over the step line (case-insensitive).'), scriptName: S.str('Only in scripts whose name contains this.'),
            scriptFolder: S.str('Only in scripts whose folder path contains this.'), targetDocId: S.str('Only steps that reference this docId.'),
            enabled: S.bool('Only enabled (true) or disabled (false) steps.'), file: S.file, limit: S.limit },
        async (args) => {
            const conds = [];
            if (args.stepName) conds.push({ field: 'name', op: 'eq', value: args.stepName });
            if (args.textContains) conds.push({ field: 'text', op: 'contains', value: args.textContains });
            if (args.regex) conds.push({ field: 'text', op: 'regex', value: args.regex });
            if (args.scriptName) conds.push({ field: 'scriptName', op: 'contains', value: args.scriptName });
            if (args.scriptFolder) conds.push({ field: 'scriptFolder', op: 'contains', value: args.scriptFolder });
            if (args.enabled !== undefined) conds.push({ field: 'enabled', op: 'eq', value: args.enabled });
            const match = compileWhere(conds);
            let recs = (await records('scriptStep', args.file)).filter(match);
            if (args.targetDocId) {
                const viaRefs = new Set();
                for (const { file, refs: rf } of await refs(args.file)) {
                    for (const e of rf.byTarget.get(args.targetDocId) || []) if (e.sourceType === 'scriptStep') viaRefs.add(file.key + '|' + e.source);
                }
                recs = recs.filter((r) => viaRefs.has(r._file + '|' + r.docId) || (r.targets || []).includes(args.targetDocId));
            }
            return page(recs.map((r) => itemOf(r)), args);
        }, { query: true });

    tool('get_entity',
        'Everything known about one entity (by docId, e.g. "script:Invoice Post", "field:Invoices::Total", "layout:Main"): '
        + 'all its attributes, plus how many references point at it.',
        { docId: S.str('The entity docId.'), file: S.file },
        async (args) => {
            const found = await entity(args.docId, args.file);
            if (!found.length) {
                const near = await nearest(args.docId, args.file);
                throw new ToolError(`No entity '${args.docId}'.`, near.length ? { didYouMean: near } : { hint: 'Use search_entities to find docIds.' });
            }
            const out = [];
            for (const r of found) {
                const rf = (await refs(r._file))[0].refs;
                out.push({ file: fileLabel(r._file), record: r,
                    incomingReferences: (rf.byTarget.get(r.docId) || []).length, outgoingReferences: (rf.bySource.get(r.docId) || []).length });
            }
            return out.length === 1 ? out[0] : { matches: out };
        }, { required: ['docId'] });

    async function nearest(docId, file) {
        const name = lower(String(docId).split(':').slice(1).join(':').split('::').pop());
        if (!name) return [];
        const out = [];
        for (const { catalog } of await catalogs(file)) {
            for (const [d, , n] of catalog.index) if (lower(n).includes(name)) { out.push(d); if (out.length >= 5) return out; }
        }
        return out;
    }

    function refItem(fileKey, e, direction, rf) {
        const other = direction === 'incoming' ? e.source : e.target;
        const otherType = direction === 'incoming' ? e.sourceType : e.targetType;
        const rec = store.byId[fileKey] && store.byId[fileKey].get(other);
        const ext = rf.external[other];
        const base = rec ? itemOf(rec) : { file: fileLabel(fileKey), docId: other, type: otherType,
            name: ext ? ext[0] : other, path: ext ? ext[1] : null };
        base.relationship = e.relationshipType + (e.role ? ` (${e.role})` : '');
        base.direction = direction;
        base.via = direction === 'incoming' ? e.target : e.source;
        if (e.externalFile) base.externalFile = e.externalFile;
        if (e.confidence !== 'exact') base.confidence = e.confidence;
        return base;
    }
    async function preload(fileKeys, types) {
        await Promise.all(fileKeys.map((k) => load(k, 'catalog')));
        const tasks = [];
        for (const k of fileKeys) {
            const cat = store.catalog[k];
            for (const t of types) if (t && cat && cat.counts[t]) tasks.push(load(k, t));
        }
        await Promise.all(tasks);
    }
    function nameOf(fileKey, docId, rf) {
        const rec = store.byId[fileKey] && store.byId[fileKey].get(docId);
        if (rec) return rec.qualifiedName || (rec.entityType === 'scriptStep' ? `${rec.scriptName} · step ${rec.stepNumber}` : rec.label || rec.name || docId);
        const ext = rf && rf.external[docId];
        return ext ? ext[0] : docId;
    }

    tool('find_references',
        'What uses an entity (incoming) or what it uses (outgoing): calculations, script steps, layouts, relationships, '
        + 'value lists, privileges, other files. Give one docId, several docIds, or targetType + parentDocId for every '
        + 'child of a parent (e.g. targetType "field" + parentDocId "table:Invoices" = references to any field of Invoices).',
        { docId: S.str('One entity docId.'), docIds: { type: 'array', items: { type: 'string' }, description: 'Several docIds.' },
            targetType: S.str('With parentDocId: the type of the children (field, layoutObject, scriptStep).'),
            parentDocId: S.str('With targetType: the parent (table:X, layout:X, script:X).'),
            direction: { type: 'string', enum: ['incoming', 'outgoing', 'both'], description: 'Default incoming.' },
            relationshipType: S.str('Only this kind of reference, e.g. usesField, usesScript, usesLayout, triggersScript.'),
            sourceType: S.str('Only references from this entity type (e.g. scriptStep, layoutObject, field).'),
            includeStructural: S.bool('Also include "contains" edges (a table containing its fields). Default false.'),
            groupBy: { type: 'string', enum: ['target', 'source'], description: 'In the viewer, group by what is referenced (default) or what references it.' },
            file: S.file, limit: S.limit },
        async (args) => {
            const direction = args.direction || 'incoming';
            const all = [];
            const rfs = await refs(args.file);
            let targets = null;
            if (args.docIds && args.docIds.length) targets = new Set(args.docIds);
            else if (args.docId) targets = new Set([args.docId]);
            else if (!(args.targetType && args.parentDocId)) throw new ToolError('Give docId, docIds, or targetType + parentDocId.');
            for (const { file, refs: rf } of rfs) {
                const keep = (e) => (args.includeStructural || !STRUCTURAL.has(e.relationshipType))
                    && (!args.relationshipType || lower(e.relationshipType) === lower(args.relationshipType));
                const edges = [];
                for (const dir of direction === 'both' ? ['incoming', 'outgoing'] : [direction]) {
                    const mine = dir === 'incoming' ? (e) => (targets ? targets.has(e.target) : e.targetType === args.targetType && e.targetParent === args.parentDocId)
                        : (e) => (targets ? targets.has(e.source) : e.sourceType === args.targetType && e.sourceParent === args.parentDocId);
                    for (const e of rf.rows) {
                        if (!mine(e) || !keep(e)) continue;
                        const otherType = dir === 'incoming' ? e.sourceType : e.targetType;
                        if (args.sourceType && otherType !== args.sourceType) continue;
                        edges.push([dir, e]);
                    }
                }
                await preload([file.key], [...new Set(edges.flatMap(([, e]) => [e.sourceType, e.targetType]))]);
                for (const [dir, e] of edges) {
                    const it = refItem(file.key, e, dir, rf);
                    it.viaName = nameOf(file.key, it.via, rf);
                    all.push(it);
                }
            }
            if (args.groupBy === 'target' || (!args.groupBy && !targets) || (targets && targets.size > 1 && !args.groupBy)) {
                for (const it of all) it.groupLabel = it.viaName;
            }
            return page(all, args, { direction });
        }, { query: true });

    tool('find_unreferenced',
        'Entities of a type that nothing references: candidates for dead code (scripts no button, trigger, menu or script '
        + 'calls; layouts nothing goes to; unused value lists, custom functions, fields, table occurrences). FileMaker can '
        + 'also reach things by name at run time (Perform Script by name, Go to Layout by calculation), from other files, '
        + 'or from server schedules, so check before deleting.',
        { type: S.type, where: S.where, file: S.file, limit: S.limit },
        async (args) => {
            const recs = (await records(args.type, args.file)).filter(compileWhere(args.where));
            const used = new Set();
            for (const { file, refs: rf } of await refs()) {
                for (const e of rf.rows) {
                    if (STRUCTURAL.has(e.relationshipType) || e.source === e.target) continue;
                    if (e.sourceParent && e.sourceParent === e.target) continue; // a script's own steps
                    used.add(file.key + '|' + e.target);
                }
            }
            const hits = recs.filter((r) => !used.has(r._file + '|' + r.docId)).map((r) => itemOf(r));
            return page(hits, args, { caveat: 'Run-time references by name, other files that were not in this build, and server schedules are not visible here.' });
        }, { query: true, required: ['type'] });

    tool('traverse',
        'Follows references more than one step: everything that eventually calls a script (incoming usesScript), everything '
        + 'a script eventually runs (outgoing), what a layout\'s buttons and triggers reach, or the path between two table '
        + 'occurrences (direction "both", relationshipTypes ["joinsTo"], to: the other one). Script steps and layout objects '
        + 'are folded into their script and layout.',
        { from: S.str('Start docId.'), direction: { type: 'string', enum: ['incoming', 'outgoing', 'both'], description: 'Default outgoing.' },
            relationshipTypes: { type: 'array', items: { type: 'string' }, description: 'Only follow these (e.g. usesScript, triggersScript, usesLayout, joinsTo). Default: all but contains.' },
            maxDepth: { type: 'integer', minimum: 1, maximum: 25, description: 'Default 10.' },
            to: S.str('Stop at this docId and return the path to it.'),
            stopAt: { type: 'array', items: S.type, description: 'Don\'t go past entities of these types.' },
            file: S.file, limit: S.limit },
        async (args) => {
            const direction = args.direction || 'outgoing';
            const types = args.relationshipTypes && args.relationshipTypes.length ? new Set(args.relationshipTypes.map(lower)) : null;
            const maxDepth = args.maxDepth || 10;
            const stopAt = new Set(args.stopAt || []);
            const rfs = await refs(args.file);
            const out = [];
            const seen = new Map();
            let frontier = rfs.map(({ file }) => ({ fileKey: file.key, docId: args.from, depth: 0, path: [args.from] }));
            let cycle = null;
            while (frontier.length) {
                const next = [];
                for (const node of frontier) {
                    if (node.depth >= maxDepth) continue;
                    const rf = rfs.find((x) => x.file.key === node.fileKey).refs;
                    // Edges from the node itself and, for a script/layout, from its steps/objects.
                    const edges = [];
                    if (direction !== 'incoming') {
                        for (const e of [...(rf.bySource.get(node.docId) || []), ...(rf.bySourceParent.get(node.docId) || [])]) edges.push([e, true]);
                    }
                    if (direction !== 'outgoing') for (const e of rf.byTarget.get(node.docId) || []) edges.push([e, false]);
                    for (const [e, fwd] of edges) {
                        if (STRUCTURAL.has(e.relationshipType)) continue;
                        if (types && !types.has(lower(e.relationshipType))) continue;
                        let other = fwd ? e.target : e.source;
                        let otherType = fwd ? e.targetType : e.sourceType;
                        const parent = fwd ? null : e.sourceParent;
                        if (parent && (otherType === 'scriptStep' || otherType === 'layoutObject')) { other = parent; otherType = otherType === 'scriptStep' ? 'script' : 'layout'; }
                        if (other === node.docId) continue;
                        if (other === args.from) { if (direction !== 'both') cycle = cycle || [...node.path, other]; continue; }
                        const key = node.fileKey + '|' + other;
                        if (seen.has(key)) continue;
                        const path = [...node.path, other];
                        seen.set(key, path);
                        out.push({ fileKey: node.fileKey, docId: other, type: otherType, depth: node.depth + 1, path,
                            relationship: e.relationshipType + (e.role ? ` (${e.role})` : '') });
                        if (args.to && other === args.to) { frontier = []; next.length = 0; break; }
                        if (!stopAt.has(otherType)) next.push({ fileKey: node.fileKey, docId: other, depth: node.depth + 1, path });
                    }
                }
                frontier = next;
            }
            const byFile = {};
            for (const n of out) (byFile[n.fileKey] || (byFile[n.fileKey] = new Set())).add(n.type);
            for (const [k, ts] of Object.entries(byFile)) await preload([k], [...ts]);
            const items = out.map((n) => {
                const rec = store.byId[n.fileKey] && store.byId[n.fileKey].get(n.docId);
                const rf = rfs.find((x) => x.file.key === n.fileKey).refs;
                const ext = rf.external[n.docId];
                const it = rec ? itemOf(rec) : { file: fileLabel(n.fileKey), docId: n.docId, type: n.type, name: ext ? ext[0] : n.docId, path: ext ? ext[1] : null };
                return Object.assign(it, { depth: n.depth, via: n.relationship, chain: n.path });
            });
            const result = page(args.to ? items.filter((i) => i.docId === args.to) : items, args, { from: args.from, direction });
            if (args.to) result.found = result.total > 0;
            if (cycle) result.cycleBackToStart = cycle;
            return result;
        }, { query: true, required: ['from'] });

    // ---- Access ---------------------------------------------------------------
    const ACTIONS = {
        script: { run: (l) => l === 'executable' || l === 'modifiable', modify: (l) => l === 'modifiable' },
        layout: { view: (l) => l === 'view' || l === 'modifiable', modify: (l) => l === 'modifiable' },
        valueList: { view: (l) => l === 'view' || l === 'modifiable', modify: (l) => l === 'modifiable' },
        table: { view: 1, edit: 1, create: 1, delete: 1 },
    };
    function accessRows(acc, type, docId) {
        const kind = type === 'layoutObject' ? null : type;
        const table = acc.objects[kind];
        return table ? table[docId] || null : null;
    }
    function judge(type, row, action) {
        if (type === 'table') {
            const level = row[1][action];
            return { allowed: level === 'yes' || level === 'limited', level, reason: row[2], limitedBy: row[3] && row[3][action] };
        }
        const level = row[1];
        const out = { allowed: ACTIONS[type][action](level), level, reason: type === 'layout' ? row[3] : row[2] };
        if (type === 'layout') out.records = row[2] || 'per record privileges';
        return out;
    }

    tool('who_can_access',
        'Which privilege sets, and so which accounts, can run a script, view or modify a layout or value list, or view, '
        + 'edit, create or delete records in a table. Each answer says why (full access, a setting for the whole category, '
        + 'the object\'s own row, or the "[Any new ...]" row). Disabled accounts and external (group) accounts are flagged.',
        { docId: S.str('script:X, layout:X, valueList:X or table:X.'),
            action: { type: 'string', enum: ['run', 'view', 'modify', 'edit', 'create', 'delete'], description: 'Default: run for scripts, view otherwise.' },
            includeDenied: S.bool('Also list the sets that are denied (default false).'), file: S.file, limit: S.limit },
        async (args) => {
            const type = typeOf(args.docId);
            if (!ACTIONS[type]) throw new ToolError(`Access is known for scripts, layouts, value lists and tables, not '${type || args.docId}'.`);
            const action = args.action || (type === 'script' ? 'run' : 'view');
            if (!ACTIONS[type][action]) throw new ToolError(`'${action}' doesn't apply to a ${type}.`, { validActions: Object.keys(ACTIONS[type]) });
            const items = [];
            let known = false;
            const caveats = new Set();
            for (const { file, access: acc } of await access(args.file)) {
                const rows = accessRows(acc, type, args.docId);
                if (!rows) continue;
                known = true;
                await preload([file.key], ['privilegeSet']);
                for (const row of rows) {
                    const v = judge(type, row, action);
                    if (!v.allowed && !args.includeDenied) continue;
                    const set = acc.sets[row[0]];
                    const setRec = store.byId[file.key] && store.byId[file.key].get(row[0]);
                    const base = setRec ? itemOf(setRec) : { file: file.label, docId: row[0], type: 'privilegeSet', name: set.name, path: null };
                    const accounts = set.accounts.map((a) => ({ name: a.name, docId: a.docId, enabled: a.enabled, external: a.external, accountType: a.accountType }));
                    if (accounts.some((a) => a.external)) caveats.add('External accounts are identity-provider groups: their members are not in the export.');
                    if (accounts.some((a) => !a.enabled)) caveats.add('Disabled accounts are listed but cannot sign in.');
                    items.push(Object.assign(base, { allowed: v.allowed, access: v.level, reason: v.reason, limitedBy: v.limitedBy, records: v.records,
                        detail: `${v.level} · ${v.reason}${v.limitedBy ? ' · limited by ' + v.limitedBy : ''}`,
                        accounts, extendedPrivileges: set.extendedPrivileges }));
                }
                if (type === 'script') {
                    await preload([file.key], ['script']);
                    const rec = store.byId[file.key].get(args.docId);
                    if (rec && rec.runWithFullAccess) caveats.add('This script runs with full access privileges: that changes what it can do once running, not who can start it.');
                }
            }
            if (!known) throw new ToolError(`No access data for '${args.docId}'.`, { hint: 'Check the docId with search_entities.' });
            const accounts = items.filter((i) => i.allowed).flatMap((i) => i.accounts.map((a) => ({ ...a, privilegeSet: i.name, file: i.file })));
            return page(items, args, { docId: args.docId, action, accounts, caveats: [...caveats] });
        }, { query: true, required: ['docId'] });

    tool('what_can_access',
        'The reverse of who_can_access: every script, layout, value list or table an account or privilege set can use, '
        + 'and why.',
        { account: S.str('Account name or docId.'), privilegeSet: S.str('Privilege set name or docId.'),
            type: { type: 'string', enum: ['script', 'layout', 'valueList', 'table'], description: 'Kind of object.' },
            action: { type: 'string', enum: ['run', 'view', 'modify', 'edit', 'create', 'delete'], description: 'Default: run for scripts, view otherwise.' },
            includeDenied: S.bool('Also list the objects it is denied (default false).'), file: S.file, limit: S.limit },
        async (args) => {
            const type = args.type;
            if (!ACTIONS[type]) throw new ToolError('type must be script, layout, valueList or table.');
            const action = args.action || (type === 'script' ? 'run' : 'view');
            if (!ACTIONS[type][action]) throw new ToolError(`'${action}' doesn't apply to a ${type}.`, { validActions: Object.keys(ACTIONS[type]) });
            if (!args.account && !args.privilegeSet) throw new ToolError('Give account or privilegeSet.');
            const items = [];
            const sets = [];
            for (const { file, access: acc } of await access(args.file)) {
                const wanted = new Set();
                for (const [psId, set] of Object.entries(acc.sets)) {
                    const bySet = args.privilegeSet && (lower(psId) === lower(args.privilegeSet) || lower(set.name) === lower(args.privilegeSet));
                    const byAcc = args.account && set.accounts.some((a) => lower(a.name) === lower(args.account) || lower(a.docId) === lower(args.account));
                    if (bySet || byAcc) { wanted.add(psId); sets.push({ file: file.label, privilegeSet: set.name }); }
                }
                if (!wanted.size) continue;
                await preload([file.key], [type]);
                for (const [docId, rows] of Object.entries(acc.objects[type] || {})) {
                    for (const row of rows) {
                        if (!wanted.has(row[0])) continue;
                        const v = judge(type, row, action);
                        if (!v.allowed && !args.includeDenied) continue;
                        const rec = store.byId[file.key].get(docId);
                        const base = rec ? itemOf(rec) : { file: file.label, docId, type, name: docId, path: null };
                        items.push(Object.assign(base, { allowed: v.allowed, access: v.level, reason: v.reason, limitedBy: v.limitedBy,
                            detail: `${v.level} · ${v.reason}`, privilegeSet: acc.sets[row[0]].name }));
                    }
                }
            }
            if (!sets.length) throw new ToolError(`No account or privilege set '${args.account || args.privilegeSet}'.`);
            return page(items, args, { sets, action });
        }, { query: true, required: ['type'] });

    // ---- The query pipeline -----------------------------------------------------
    tool('query',
        'A pipeline of steps for questions no other tool covers. Steps run in order over rows: '
        + '{from: type, file?} starts from every entity of a type (or "reference" for reference edges); '
        + '{where: [conditions]} filters (same conditions as query_entities; joined rows are reached as as.field); '
        + '{join: {on: field, as: name}} attaches the entity a docId field points at (scriptDocId, layoutDocId, privilegeSetDocId, fieldDocId...); '
        + '{joinRefs: {direction: incoming|outgoing, relationshipType?, as: name}} adds one row per reference; '
        + '{joinAccess: {action, as: name}} adds one row per privilege set with that access (rows must be scripts, layouts, value lists or tables, or join one first and pass on: field); '
        + '{select: [fields]}; {groupBy: field, agg: count|list}; {sort: field, desc?: bool}; {limit: n}. '
        + 'Example: privilege sets that can run a script containing Delete Record: '
        + '[{from:"scriptStep"},{where:[{field:"name",op:"eq",value:"Delete Record/Request"}]},{join:{on:"scriptDocId",as:"script"}},'
        + '{joinAccess:{on:"script.docId",action:"run",as:"access"}},{groupBy:"access.name",agg:"list"}]. '
        + 'The response gives the row count after every step, so an empty result shows which step emptied it.',
        { steps: { type: 'array', items: { type: 'object' }, description: 'The pipeline.' }, limit: S.limit },
        async (args) => runPipeline(args),
        { query: true, required: ['steps'] });

    async function runPipeline(args) {
        const steps = args.steps || [];
        if (!steps.length || !steps[0].from) throw new ToolError('The first step must be {from: type}.', { validTypes: [...TYPES, 'reference'] });
        let rows = [];
        const counts = [];
        let grouped = false;
        let selected = false;
        for (const [i, step] of steps.entries()) {
            const op = Object.keys(step).find((k) => ['from', 'where', 'join', 'joinRefs', 'joinAccess', 'select', 'groupBy', 'sort', 'limit'].includes(k));
            if (!op) throw new ToolError(`Step ${i + 1} has no known operation.`, { step, validOps: ['from', 'where', 'join', 'joinRefs', 'joinAccess', 'select', 'groupBy', 'sort', 'limit'] });
            if (op === 'from') {
                if (i) throw new ToolError('from must be the first step.');
                if (step.from === 'reference') {
                    for (const { file, refs: rf } of await refs(step.file)) for (const e of rf.rows) { const o = Object.assign(Object.create(null), { file: file.label }, e); Object.defineProperty(o, '_file', { value: file.key, enumerable: false, writable: true }); rows.push(o); }
                } else {
                    rows = (await records(step.from, step.file)).map((r) => wrap(r));
                }
            } else if (op === 'where') {
                if (rows.length && !grouped) checkFields(rows[0].entityType || 'row', step.where, rows.map((r) => r));
                rows = rows.filter(compileWhere(step.where));
            } else if (op === 'join') {
                const j = step.join;
                if (!j.on || !j.as) throw new ToolError('join needs on and as.');
                const out = [];
                for (const r of rows) {
                    const target = getPath(r, j.on);
                    const ids = Array.isArray(target) ? target : [target];
                    let any = false;
                    for (const id of ids) {
                        if (!id) continue;
                        const found = await entity(id, fileOfRow(r));
                        for (const t of found) { out.push(extend(r, { [j.as]: wrap(t) })); any = true; }
                    }
                    if (!any && j.keepUnmatched) out.push(r);
                }
                rows = out;
            } else if (op === 'joinRefs') {
                const j = step.joinRefs;
                const dir = j.direction || 'incoming';
                const out = [];
                for (const r of rows) {
                    const key = r._file;
                    const rf = (await refs(key))[0].refs;
                    const id = j.on ? getPath(r, j.on) : r.docId;
                    const edges = (dir === 'incoming' ? rf.byTarget.get(id) : rf.bySource.get(id)) || [];
                    for (const e of edges) {
                        if (STRUCTURAL.has(e.relationshipType) && !j.includeStructural) continue;
                        if (j.relationshipType && lower(e.relationshipType) !== lower(j.relationshipType)) continue;
                        const otherId = dir === 'incoming' ? e.source : e.target;
                        const otherType = dir === 'incoming' ? e.sourceType : e.targetType;
                        await preload([key], [otherType]);
                        const rec = store.byId[key] && store.byId[key].get(otherId);
                        out.push(extend(r, { [j.as || 'ref']: Object.assign({ relationshipType: e.relationshipType, role: e.role, docId: otherId, entityType: otherType }, rec ? wrap(rec) : {}) }));
                    }
                }
                rows = out;
            } else if (op === 'joinAccess') {
                const j = step.joinAccess;
                const out = [];
                for (const r of rows) {
                    const id = j.on ? getPath(r, j.on) : r.docId;
                    const type = typeOf(id);
                    if (!ACTIONS[type]) throw new ToolError(`joinAccess needs scripts, layouts, value lists or tables; got '${id}'. Use on: to point at one.`);
                    const action = j.action || (type === 'script' ? 'run' : 'view');
                    const acc = (await access(r._file))[0].access;
                    for (const row of accessRows(acc, type, id) || []) {
                        const v = judge(type, row, action);
                        if (!v.allowed && !j.includeDenied) continue;
                        const set = acc.sets[row[0]];
                        out.push(extend(r, { [j.as || 'access']: {
                            docId: row[0], name: set.name, allowed: v.allowed, access: v.level, reason: v.reason, limitedBy: v.limitedBy,
                            accounts: set.accounts.map((a) => a.name) } }));
                    }
                }
                rows = out;
            } else if (op === 'select') {
                rows = rows.map((r) => Object.assign(Object.fromEntries(step.select.map((f) => [f, getPath(r, f)])), hidden(r)));
                selected = true;
            } else if (op === 'groupBy') {
                const groups = new Map();
                for (const r of rows) {
                    const k = JSON.stringify(getPath(r, step.groupBy) ?? null);
                    if (!groups.has(k)) groups.set(k, []);
                    groups.get(k).push(r);
                }
                rows = [...groups.entries()].map(([k, rs]) => {
                    const g = { [step.groupBy]: JSON.parse(k), count: rs.length };
                    if (step.agg === 'list') g.items = rs.map(summarize);
                    return g;
                });
                grouped = true;
            } else if (op === 'sort') {
                const f = step.sort;
                const d = step.desc ? -1 : 1;
                rows = [...rows].sort((a, b) => { const x = getPath(a, f), y = getPath(b, f); return (x > y ? 1 : x < y ? -1 : 0) * d; });
            } else if (op === 'limit') {
                rows = rows.slice(0, step.limit);
            }
            counts.push({ step: i + 1, op, rows: rows.length });
        }
        const items = grouped || selected ? rows.map((r) => plain(r)) : rows.map(summarize);
        const result = page(items, args, { rowsAfterEachStep: counts });
        result.shape = grouped ? 'groups' : selected ? 'rows' : 'items';
        return result;
    }
    function wrap(r) {
        const o = Object.assign(Object.create(null), r);
        Object.defineProperty(o, '_file', { value: r._file, enumerable: false, writable: true });
        Object.defineProperty(o, '_rec', { value: r, enumerable: false });
        return o;
    }
    function extend(r, extra) {
        const o = Object.assign(Object.create(null), r, extra);
        Object.defineProperty(o, '_file', { value: r._file, enumerable: false, writable: true });
        if (r._rec) Object.defineProperty(o, '_rec', { value: r._rec, enumerable: false });
        return o;
    }
    function hidden(r) { const o = {}; Object.defineProperty(o, '_file', { value: r._file, enumerable: false }); return o; }
    function fileOfRow(r) { return r._file; }
    function plain(r) { return JSON.parse(JSON.stringify(r)); }
    function summarize(r) {
        const base = r._rec ? itemOf(r._rec) : plain(r);
        for (const [k, v] of Object.entries(r)) {
            if (v && typeof v === 'object' && !Array.isArray(v) && k !== '_rec' && (v.docId || v.name)) {
                base[k] = v._rec ? { docId: v.docId, type: v.entityType, name: v.name, path: v.path } : plain(v);
            }
        }
        return base;
    }

    tool('show_results',
        'Shows a hand-picked list of entities in the viewer, e.g. "the scripts I think cause this bug". '
        + 'Give docIds (and file in a multi-file solution).',
        { title: S.title, items: { type: 'array', items: { type: 'object' }, description: '[{docId, file?, note?}] or docId strings.' } },
        async (args) => {
            const items = [];
            for (const it of args.items || []) {
                const ref = typeof it === 'string' ? { docId: it } : it;
                const found = await entity(ref.docId, ref.file);
                if (!found.length) { items.push({ docId: ref.docId, type: typeOf(ref.docId) || 'unknown', name: ref.docId, detail: 'not found' }); continue; }
                for (const r of found) items.push(itemOf(r, ref.note ? { detail: ref.note } : null));
            }
            return { total: items.length, items };
        }, { changesView: true, required: ['items'] });

    tool('navigate_to',
        'Opens an entity\'s page in the viewer (by docId), or any page by path. For a script step, opens its script '
        + 'and highlights the step.',
        { docId: S.str('Entity docId.'), path: S.str('Page path, e.g. Reports/summary.md.'), file: S.file,
            anchor: S.str('Heading on the page to scroll to.') },
        async (args) => {
            let path = args.path;
            let step = null;
            if (!path && args.docId) {
                const found = await entity(args.docId, args.file);
                if (!found.length) throw new ToolError(`No entity '${args.docId}'.`);
                path = found[0].path;
                if (found[0].entityType === 'scriptStep') step = found[0].stepNumber;
            }
            if (!path) throw new ToolError('Give docId or path.');
            if (!FM.ui) throw new ToolError('The viewer is not ready.');
            FM.ui.navigate(path, { anchor: args.anchor, step });
            return { opened: path, step };
        }, { changesView: true });

    // ---- Page tools: registered for the page being shown ------------------------
    // Each is a query_entities call scoped to the page's entity, so its results view
    // (a plain query_entities route) still works after the page tools are gone.
    const PAGE_TOOLS = {
        script: () => ({
            list_steps_in_this_script: ['Lists the steps of the script on screen, optionally only those whose text contains a string.',
                { textContains: S.str('Text in the step line.'), stepName: S.str('Exact step name.'), limit: S.limit },
                (args, ctx) => ({ type: 'scriptStep', title: `Steps of ${ctx.name}`, where: [
                    { field: 'scriptDocId', op: 'eq', value: ctx.docId },
                    args.textContains ? { field: 'text', op: 'contains', value: args.textContains } : null,
                    args.stepName ? { field: 'name', op: 'eq', value: args.stepName } : null] })],
        }),
        table: () => ({
            list_fields_in_this_table: ['Lists the fields of the table on screen, optionally filtered (see query_entities for conditions).',
                { where: S.where, limit: S.limit },
                (args, ctx) => ({ type: 'field', title: `Fields of ${ctx.name}`,
                    where: [{ field: 'baseTableDocId', op: 'eq', value: ctx.docId }, ...[].concat(args.where || [])] })],
        }),
        layout: () => ({
            list_objects_on_this_layout: ['Lists the objects on the layout on screen. hidden: "hideCondition" = objects with a "Hide object when" '
                + 'calculation; "panel" = objects that only show when a tab panel, slide panel or popover is opened; "any" = either. '
                + 'Objects placed outside the visible area are not detected.',
                { objectType: S.str('e.g. "Edit Box", "Button", "Portal".'), fieldsOnly: S.bool('Only objects showing a field.'),
                    hidden: { type: 'string', enum: ['hideCondition', 'panel', 'any'] }, limit: S.limit },
                (args, ctx) => ({ type: 'layoutObject', title: `${args.hidden ? 'Hidden objects' : 'Objects'} on ${ctx.name}`, where: [
                    { field: 'layoutDocId', op: 'eq', value: ctx.docId },
                    args.objectType ? { field: 'objectType', op: 'eq', value: args.objectType } : null,
                    args.fieldsOnly ? { field: 'isField', op: 'eq', value: true } : null,
                    args.hidden === 'hideCondition' ? { field: 'hasHideCondition', op: 'eq', value: true } : null,
                    args.hidden === 'panel' ? { field: 'inPanel', op: 'eq', value: true } : null,
                    args.hidden === 'any' ? { any: [{ field: 'hasHideCondition', op: 'eq', value: true }, { field: 'inPanel', op: 'eq', value: true }] } : null,
                ] })],
        }),
    };
    let pageToolNames = [];
    function fileForPath(path) {
        const fs = files();
        return fs.filter((f) => !f.dir || path.startsWith(f.dir + '/')).sort((a, b) => b.dir.length - a.dir.length)[0] || null;
    }
    function onRoute(info) {
        for (const name of pageToolNames) { delete tools[name]; unregister(name); }
        pageToolNames = [];
        const meta = (info && info.meta) || {};
        const make = PAGE_TOOLS[meta.entityType];
        if (!make || !meta.docId) return;
        const f = fileForPath(info.path);
        const ctx = { docId: meta.docId, fileKey: f ? f.key : (files()[0] || {}).key, name: meta.name };
        for (const [name, [description, properties, toQuery]] of Object.entries(make())) {
            const asQuery = (args) => {
                const q = toQuery(args, ctx);
                const out = { type: q.type, where: q.where.filter(Boolean), file: ctx.fileKey, title: args.title || q.title };
                if (args.limit) out.limit = args.limit;
                return out;
            };
            tool(name, `${description} (On this page: ${meta.name || meta.docId}.)`, properties,
                (args) => call('query_entities', asQuery(args)), { query: true, displayAs: (args) => ['query_entities', asQuery(args)] });
            pageToolNames.push(name);
            register(tools[name]);
        }
    }

    // ---- Calling, results view --------------------------------------------------
    let currentResults = null;
    async function call(name, args) {
        const t = tools[name];
        if (!t) throw new ToolError(`No tool '${name}'.`, { tools: Object.keys(tools) });
        return t.run(args || {});
    }
    function show(name, args) {
        const { display, ...rest } = args || {};
        void display;
        if (!FM.ui) return;
        const q = encodeURIComponent(JSON.stringify({ tool: name, args: rest }));
        FM.ui.go('#/results?q=' + q);
    }
    async function execute(name, args) {
        args = args || {};
        try {
            const result = await call(name, args);
            const t = tools[name];
            if ((t.query && args.display !== false) || name === 'show_results') {
                if (t.displayAs) show(...t.displayAs(args)); else show(name, args);
            }
            return { content: [{ type: 'text', text: JSON.stringify(result) }] };
        } catch (err) {
            const body = err instanceof ToolError ? { error: err.message, ...err.details } : { error: String(err && err.message || err) };
            return { content: [{ type: 'text', text: JSON.stringify(body) }], isError: true };
        }
    }

    // ---- WebMCP registration ----------------------------------------------------
    // The browser (or an agent's browser) may add modelContext after the page loads, so
    // registration is retried a few times and every tool registered as soon as it appears.
    const findModelContext = () => (typeof document !== 'undefined' && document.modelContext)
        || (typeof navigator !== 'undefined' && navigator.modelContext) || null;
    let modelContext = findModelContext();
    const exposed = {};
    const registeredNatively = new Set();
    let badge = null; // the header status button (see updateBadge)
    function asWebMcp(t) {
        const readOnly = t.readOnly;
        return {
            name: t.name,
            description: t.description + (t.query ? ' Results also show in the viewer unless display is false.' : ''),
            inputSchema: t.inputSchema,
            annotations: { readOnlyHint: readOnly },
            execute: (args) => execute(t.name, args),
        };
    }
    function registerNatively(name) {
        if (!modelContext || typeof modelContext.registerTool !== 'function' || registeredNatively.has(name)) return;
        try { modelContext.registerTool(exposed[name]); registeredNatively.add(name); } catch (err) { console.warn(`WebMCP: could not register ${name}:`, err); }
    }
    function register(t) {
        exposed[t.name] = asWebMcp(t);
        registerNatively(t.name);
        updateBadge();
    }
    function unregister(name) {
        delete exposed[name];
        if (registeredNatively.delete(name) && modelContext && typeof modelContext.unregisterTool === 'function') {
            try { modelContext.unregisterTool(name); } catch (err) { void err; }
        }
        updateBadge();
    }
    function retryNative() {
        if (!modelContext) modelContext = findModelContext();
        if (modelContext) for (const name of Object.keys(exposed)) registerNatively(name);
        updateBadge();
    }
    for (const t of Object.values(tools)) register(t);
    for (const ms of [0, 500, 2000, 5000]) setTimeout(retryNative, ms);
    if (typeof window !== 'undefined') window.addEventListener('load', retryNative);

    // ---- Status badge (header): is WebMCP on, and if not, why ----------------------
    function docsFolder() {
        // file:///D:/Docs/My_docs/index.html -> D:\Docs\My_docs (the folder to pass to fm-saxml serve)
        let path = decodeURIComponent(location.pathname).replace(/\/[^/]*$/, '');
        if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1).replace(/\//g, '\\');
        return path || '.';
    }
    function status() {
        const total = Object.keys(exposed).length;
        if (modelContext && registeredNatively.size) {
            return { state: 'on', label: `WebMCP · ${registeredNatively.size} tools`,
                help: `Agents in this browser can use ${registeredNatively.size} tools to query this solution. `
                    + 'The same tools are on window.FMDocs.tools.' };
        }
        if (location.protocol === 'file:') {
            const cmd = `fm-saxml serve "${docsFolder()}"`;
            return { state: 'off', label: 'WebMCP off: opened from disk', command: cmd,
                help: 'Browsers only give WebMCP to pages served from a web address, not to pages opened from disk. '
                    + `Serve this folder on this computer (only it can connect) and open the address it prints:\n\n${cmd}\n\n`
                    + `Until then the ${total} tools are on window.FMDocs.tools, and can be run by URL: see #/agents.` };
        }
        return { state: 'off', label: 'WebMCP not in this browser',
            help: `This browser doesn't offer WebMCP to pages (document.modelContext is missing). In Chrome or Edge, turn on `
                + 'WebMCP under chrome://flags (edge://flags); in ChatGPT\'s browser, check Settings > Browser > Permissions '
                + `and that the model in use has site tools. Agents without WebMCP can still use the ${total} tools through `
                + 'window.FMDocs.tools or by URL: see "For AI agents" (#/agents).' };
    }
    function updateBadge() {
        if (typeof document === 'undefined' || !document.body) return;
        if (!badge) {
            const header = document.querySelector('header.top');
            if (!header) return;
            badge = document.createElement('button');
            badge.type = 'button';
            badge.id = 'webmcp-status';
            const search = header.querySelector('#search');
            header.insertBefore(badge, search || null);
            const guide = document.createElement('a');
            guide.id = 'webmcp-agents';
            guide.href = '#/agents';
            guide.textContent = 'For AI agents';
            guide.title = 'How AI agents can use this documentation\'s query tools, with or without WebMCP';
            header.insertBefore(guide, search || null);
            badge.addEventListener('click', () => {
                const st = status();
                if (st.command && navigator.clipboard) navigator.clipboard.writeText(st.command).catch(() => {});
                alert(st.help + (st.command ? '\n\n(The command has been copied.)' : ''));
            });
        }
        const st = status();
        badge.textContent = st.label;
        badge.title = st.help;
        badge.dataset.state = st.state;
    }
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', updateBadge);
        else updateBadge();
    }

    // ---- Results view (rendered by index.html at #/results?q=...) ---------------
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const RECENT_KEY = 'fm-saxml.recentQueries';
    function recent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; } }
    function remember(entry) {
        try {
            const list = recent().filter((e) => e.q !== entry.q);
            list.unshift(entry);
            localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 20)));
        } catch { /* storage unavailable: no history */ }
    }
    function titleFor(name, args) {
        if (args.title) return args.title;
        const a = Object.entries(args).filter(([k]) => k !== 'title').map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
        return `${name.replace(/_/g, ' ')}${a.length ? ' — ' + a.join(', ') : ''}`;
    }

    // #/results?q=<url-encoded {"tool": name, "args": {...}}>[&format=json] and #/agents.
    async function renderResultsRoute(container, hash) {
        if (/^#\/agents(\?|$)/.test(hash)) return renderAgentsPage(container);
        const m = /[?&]q=([^&]*)/.exec(hash);
        let spec = null;
        try { spec = m ? JSON.parse(decodeURIComponent(m[1])) : null; } catch { spec = null; }
        if (/[?&]format=json(&|$)/.test(hash)) return renderJson(container, spec);
        container.innerHTML = '';
        const wrapEl = document.createElement('div');
        wrapEl.className = 'fm-results';
        container.appendChild(wrapEl);
        wrapEl.innerHTML = advancedForm(spec) + '<div class="fm-results-body"></div>';
        wireAdvanced(wrapEl);
        const body = wrapEl.querySelector('.fm-results-body');
        if (!spec || !spec.tool) { body.innerHTML = recentList(); currentResults = null; return; }
        const title = titleFor(spec.tool, spec.args || {});
        document.title = `${title} · ${FM.data.title}`;
        body.innerHTML = `<h2>${esc(title)}</h2><p class="fm-muted">Running…</p>`;
        let result;
        try {
            result = await call(spec.tool, spec.args || {});
        } catch (err) {
            const details = err instanceof ToolError ? err.details : {};
            body.innerHTML = `<h2>${esc(title)}</h2><p class="fm-error">${esc(err.message)}</p>`
                + (Object.keys(details).length ? `<pre>${esc(JSON.stringify(details, null, 2))}</pre>` : '');
            currentResults = { error: err.message };
            return;
        }
        currentResults = { tool: spec.tool, args: spec.args, total: result.total };
        remember({ q: hash.slice(hash.indexOf('q=') + 2), title, total: result.total, at: new Date().toISOString() });
        body.innerHTML = `<h2>${esc(title)}</h2>` + renderResult(spec.tool, result, spec.args);
    }

    // The result as plain JSON text, for agents that read pages but can't call WebMCP or run scripts.
    async function renderJson(container, spec) {
        let body;
        if (!spec || !spec.tool) {
            body = { error: 'Give q={"tool": name, "args": {...}} (URL-encoded). The tools are listed at #/agents.' };
        } else {
            try { body = await call(spec.tool, spec.args || {}); } catch (err) {
                body = err instanceof ToolError ? { error: err.message, ...err.details } : { error: String(err && err.message || err) };
            }
        }
        currentResults = spec && spec.tool ? { tool: spec.tool, args: spec.args, total: body.total } : null;
        document.title = `${spec && spec.tool ? spec.tool : 'result'} (JSON) · ${FM.data.title}`;
        container.innerHTML = `<div class="fm-results"><p class="fm-muted">Result of <code>${esc(spec && spec.tool || '?')}</code> as JSON. `
            + 'Tool list: <a href="#/agents">#/agents</a>.</p>'
            + `<pre id="fm-result-json">${esc(JSON.stringify(body, null, 1))}</pre></div>`;
    }

    // ---- #/agents: how an agent without WebMCP reaches the same tools ----------
    function resultsUrl(tool, args, json) {
        return `${location.href.split('#')[0]}#/results?q=${encodeURIComponent(JSON.stringify({ tool, args }))}${json ? '&format=json' : ''}`;
    }
    async function examples() {
        const first = {};
        try {
            for (const { catalog } of await catalogs()) {
                for (const [docId, type] of catalog.index) if (!first[type]) first[type] = docId;
            }
        } catch { /* examples fall back to placeholders */ }
        const t = first.table || 'table:Invoices', sc = first.script || 'script:Invoice Post', l = first.layout || 'layout:Main';
        return {
            describe_schema: { type: 'field' },
            get_solution_overview: {},
            search_entities: { query: (first.table || 'table:Invoice').split(':')[1].slice(0, 4) },
            query_entities: { type: 'field', where: [{ field: 'global', op: 'eq', value: true }] },
            find_script_steps: { stepName: 'Set Field', limit: 20 },
            get_entity: { docId: sc },
            find_references: { targetType: 'field', parentDocId: t },
            find_unreferenced: { type: 'script' },
            traverse: { from: sc, direction: 'incoming', relationshipTypes: ['usesScript', 'triggersScript'] },
            who_can_access: { docId: sc, action: 'run' },
            what_can_access: { privilegeSet: '[Full Access]', type: 'layout' },
            query: { steps: [{ from: 'field' }, { where: [{ field: 'fieldType', op: 'eq', value: 'Calculated' }] }, { groupBy: 'table', agg: 'count' }] },
            show_results: { title: 'Picked by hand', items: [sc, l] },
        };
    }
    async function renderAgentsPage(container) {
        document.title = `Tools for AI agents · ${FM.data.title}`;
        const ex = await examples();
        const st = status();
        const list = Object.values(tools).filter((t) => !pageToolNames.includes(t.name));
        let html = `<div class="fm-results fm-agents"><h2>Tools for AI agents</h2>
            <p>This documentation answers questions about the FileMaker solution through ${list.length} tools (none of them change anything)
            (WebMCP status here: <strong>${esc(st.label)}</strong>). There are three ways to call them:</p>
            <ol>
            <li><strong>WebMCP</strong>, when the browser offers it (<code>document.modelContext</code>): the tools are registered under the names below.</li>
            <li><strong>JavaScript in this page</strong>: <code>await FMDocs.tools.&lt;name&gt;.execute({...args})</code> returns
              <code>{content: [{type: "text", text: "&lt;JSON&gt;"}]}</code>. Or <code>await FMDocs.webmcp.call("&lt;name&gt;", {...})</code> for the plain object.</li>
            <li><strong>A URL</strong>, for agents that can only open pages and read them: open
              <code>index.html#/results?q=&lt;URL-encoded {"tool": "&lt;name&gt;", "args": {...}}&gt;&amp;format=json</code>.
              The page shows the result as JSON text in <code>&lt;pre id="fm-result-json"&gt;</code>. Leave out <code>&amp;format=json</code>
              for the same result laid out for people, grouped by type.</li>
            </ol>
            <p>Start with <code>describe_schema</code> to see the entity types and their fields. Every entity has a <code>docId</code>
            such as <code>script:Name</code>, <code>field:Table::Field</code> or <code>layout:Name</code>; results carry the docIds
            to pass to the next call. Results are capped by <code>limit</code> (default ${DEFAULT_LIMIT}, max ${MAX_LIMIT}) and say
            <code>truncated</code> when there are more. In a multi-file solution, <code>file</code> narrows a call to one file.
            Script, table and layout pages add tools scoped to that page (WebMCP and JavaScript only).</p>`;
        for (const t of list) {
            const args = ex[t.name];
            html += `<section class="fm-tool"><h3 id="tool-${esc(t.name)}"><code>${esc(t.name)}</code></h3><p>${esc(t.description)}</p>`;
            html += `<details><summary>Arguments (JSON Schema)</summary><pre>${esc(JSON.stringify(t.inputSchema, null, 1))}</pre></details>`;
            if (args && t.name !== 'show_results') {
                const url = resultsUrl(t.name, args, true);
                html += `<p class="fm-muted">Example: <code>${esc(JSON.stringify(args))}</code> · <a href="${esc(url)}">open as JSON</a> · `
                    + `<a href="${esc(resultsUrl(t.name, args, false))}">open as results</a></p><pre class="fm-url">${esc(url)}</pre>`;
            }
            html += '</section>';
        }
        container.innerHTML = html + '</div>';
        currentResults = null;
    }

    function renderResult(name, result, args) {
        let more = '';
        if (result.truncated) {
            const all = '#/results?q=' + encodeURIComponent(JSON.stringify({ tool: name, args: { ...(args || {}), limit: MAX_LIMIT } }));
            more = ` (showing ${result.items.length}; <a href="${esc(all)}">show up to ${MAX_LIMIT}</a>)`;
        }
        let html = `<p class="fm-muted">${result.total} result${result.total === 1 ? '' : 's'}${more}</p>`;
        for (const key of ['caveat', 'caveats']) {
            const c = result[key];
            if (c && (!Array.isArray(c) || c.length)) html += `<p class="fm-note">${esc([].concat(c).join(' '))}</p>`;
        }
        if (result.cycleBackToStart) html += `<p class="fm-note">Cycle back to the start: ${esc(result.cycleBackToStart.join(' → '))}</p>`;
        if (result.accounts && result.accounts.length) {
            html += '<p><strong>Accounts:</strong> ' + result.accounts.map((a) => `${esc(a.name)}`
                + (a.external ? ' <span class="fm-tag">group</span>' : '') + (!a.enabled ? ' <span class="fm-tag">disabled</span>' : '')).join(', ') + '</p>';
        }
        if (result.shape === 'groups' || result.shape === 'rows') return html + renderTable(result.items);
        if (result.rowsAfterEachStep) html += `<p class="fm-muted">Rows after each step: ${result.rowsAfterEachStep.map((s) => `${s.op} ${s.rows}`).join(' → ')}</p>`;
        return html + renderGroups(result.items || []);
    }

    function renderTable(rows) {
        if (!rows.length) return '';
        const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
        const cell = (v) => {
            if (Array.isArray(v)) return v.map((x) => (x && typeof x === 'object' ? linkFor(x) : esc(x))).join(', ');
            if (v && typeof v === 'object') return v.docId ? linkFor(v) : esc(JSON.stringify(v));
            return esc(v);
        };
        return `<table class="fm-table"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>`
            + rows.map((r) => `<tr>${cols.map((c) => `<td>${cell(r[c])}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
    }

    function linkFor(it) {
        const label = esc(it.name || it.docId);
        if (!it.path || !FM.ui) return label;
        return `<a href="${esc(FM.ui.hrefFor(it.path))}" data-fm-path="${esc(it.path)}"${it.step ? ` data-fm-step="${it.step}"` : ''}>${label}</a>`;
    }

    function renderGroups(items) {
        const multiFile = new Set(items.map((i) => i.file)).size > 1;
        const byFile = new Map();
        for (const it of items) { const k = multiFile ? it.file : ''; if (!byFile.has(k)) byFile.set(k, []); byFile.get(k).push(it); }
        let html = '';
        for (const [file, list] of byFile) {
            if (file) html += `<h3 class="fm-file">${esc(file)}</h3>`;
            const byType = new Map();
            for (const it of list) {
                const k = it.groupLabel ? `via ${it.groupLabel}` : (TYPE_LABELS[it.type] || it.type);
                if (!byType.has(k)) byType.set(k, []);
                byType.get(k).push(it);
            }
            const groups = [...byType.entries()].sort((a, b) => b[1].length - a[1].length);
            for (const [label, group] of groups) {
                html += `<details class="fm-group" open><summary>${esc(label)} <span class="fm-count">${group.length}</span></summary>`;
                const withParent = group.filter((i) => i.parent);
                if (withParent.length === group.length && new Set(group.map((i) => i.parent.docId)).size < group.length) {
                    const byParent = new Map();
                    for (const it of group) { if (!byParent.has(it.parent.docId)) byParent.set(it.parent.docId, []); byParent.get(it.parent.docId).push(it); }
                    for (const [, kids] of byParent) {
                        const p = kids[0].parent;
                        const plink = p.path ? linkFor({ name: p.name, path: p.path }) : esc(p.name || p.docId);
                        html += `<details class="fm-sub" open><summary>${plink} <span class="fm-count">${kids.length}</span></summary><ul>${kids.map((k) => row(k, true)).join('')}</ul></details>`;
                    }
                } else {
                    html += `<ul>${group.map((k) => row(k, false)).join('')}</ul>`;
                }
                html += '</details>';
            }
        }
        return html || '<p class="fm-muted">Nothing found.</p>';
    }

    function row(it, nested) {
        let extra = '';
        if (it.relationship) extra += ` <span class="fm-tag">${esc(it.relationship)}</span>`;
        if (it.depth) extra += ` <span class="fm-tag">depth ${it.depth}</span>`;
        if (it.externalFile) extra += ` <span class="fm-tag">${esc(it.externalFile)}</span>`;
        if (it.accounts) {
            extra += '<div class="fm-accounts">' + (it.accounts.length ? it.accounts.map((a) => esc(a.name)
                + (a.external ? ' <span class="fm-tag">group</span>' : '') + (!a.enabled ? ' <span class="fm-tag">disabled</span>' : '')).join(', ') : '<span class="fm-muted">no accounts</span>') + '</div>';
        }
        const parent = it.parent && !nested ? ` <span class="fm-muted">in ${esc(it.parent.name || it.parent.docId)}</span>` : '';
        return `<li>${linkFor(it)}${parent}${it.detail ? ` <span class="fm-detail">${esc(it.detail)}</span>` : ''}${extra}</li>`;
    }

    function recentList() {
        const list = recent();
        if (!list.length) return '<p class="fm-muted">Type in the search box, use Advanced search above, or ask an agent that speaks WebMCP. Results show here.</p>';
        return '<h2>Recent queries</h2><ul>' + list.map((e) => `<li><a href="#/results?q=${esc(e.q)}">${esc(e.title)}</a> <span class="fm-muted">${e.total ?? ''}</span></li>`).join('') + '</ul>';
    }

    // ---- Advanced search form ----------------------------------------------------
    function advancedForm(spec) {
        const a = (spec && spec.tool === 'query_entities' && spec.args) || {};
        const types = TYPES.map((t) => `<option value="${t}"${a.type === t ? ' selected' : ''}>${esc(TYPE_LABELS[t])}</option>`).join('');
        const fileOpts = files().length > 1 ? `<label>File <select name="file"><option value="">All files</option>${files().map((f) => `<option${a.file === f.label ? ' selected' : ''}>${esc(f.label)}</option>`).join('')}</select></label>` : '';
        const nameCond = (a.where || []).find((c) => c.field === 'name' && c.op === 'contains');
        return `<details class="fm-advanced"${spec ? '' : ' open'}><summary>Advanced search</summary><form>
            <label>Type <select name="type">${types}</select></label>${fileOpts}
            <label>Name contains <input name="name" value="${esc(nameCond ? nameCond.value : '')}"></label>
            <label data-only="layoutObject"><input type="checkbox" name="hide"> Has a hide condition</label>
            <label data-only="layoutObject"><input type="checkbox" name="panel"> Only shown in a panel or popover</label>
            <label data-only="layout layoutObject"><input type="checkbox" name="triggers"> Has script triggers</label>
            <label><input type="checkbox" name="unreferenced"> Nothing references it</label>
            <button type="submit">Search</button></form></details>`;
    }
    function wireAdvanced(root) {
        const form = root.querySelector('.fm-advanced form');
        if (!form) return;
        const sync = () => {
            const type = form.elements.type.value;
            for (const el of form.querySelectorAll('[data-only]')) {
                const on = el.dataset.only.split(' ').includes(type);
                el.style.display = on ? '' : 'none';
                if (!on) el.querySelector('input').checked = false;
            }
        };
        form.elements.type.addEventListener('change', sync);
        sync();
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const fd = new FormData(form);
            const where = [];
            if (fd.get('name')) where.push({ field: 'name', op: 'contains', value: fd.get('name') });
            if (fd.get('hide')) where.push({ field: 'hasHideCondition', op: 'eq', value: true });
            if (fd.get('panel')) where.push({ field: 'inPanel', op: 'eq', value: true });
            if (fd.get('triggers')) where.push({ field: 'triggerEvents', op: 'exists' });
            const args = { type: fd.get('type'), where };
            if (fd.get('file')) args.file = fd.get('file');
            show(fd.get('unreferenced') ? 'find_unreferenced' : 'query_entities', args);
        });
    }

    // ---- Search box: entity names from every file, grouped by type ----------------
    async function search(query, side) {
        const q = query.trim();
        if (!q) return false;
        let result;
        try { result = await call('search_entities', { query: q, limit: 400 }); } catch (err) { side.innerHTML = `<p class="fm-error">${esc(err.message)}</p>`; return true; }
        const byType = new Map();
        for (const it of result.items) { if (!byType.has(it.type)) byType.set(it.type, []); byType.get(it.type).push(it); }
        const all = '#/results?q=' + encodeURIComponent(JSON.stringify({ tool: 'search_entities', args: { query: q, deep: true } }));
        let html = `<ul class="results"><li><small>${result.total} match${result.total === 1 ? '' : 'es'} by name · <a href="${all}">Search text too, in the results view →</a></small></li></ul>`;
        for (const [type, list] of [...byType.entries()].sort((a, b) => b[1].length - a[1].length)) {
            html += `<details open><summary>${esc(TYPE_LABELS[type] || type)}<span class="count">${list.length}</span></summary><ul class="results">`;
            for (const it of list.slice(0, 50)) {
                html += `<li>${it.path ? `<a href="${esc(FM.ui.hrefFor(it.path))}" data-path="${esc(it.path)}">${esc(it.name)}</a>` : esc(it.name)}`
                    + (files().length > 1 ? `<small>${esc(it.file)}</small>` : '') + '</li>';
            }
            if (list.length > 50) html += `<li><small>… ${list.length - 50} more in the results view</small></li>`;
            html += '</ul></details>';
        }
        side.innerHTML = html;
        return true;
    }

    // ---- Step highlight on a script page -----------------------------------------
    // Steps render as one numbered code block ("12  Set Field [ ... ]"). Crepe shows it as a
    // plain <pre> until it scrolls into view and only then mounts CodeMirror, which itself
    // only draws the lines near the viewport: scroll to the step's line in whichever is
    // there, and mark the line once CodeMirror has drawn it.
    async function highlightStep(content, scroller, n) {
        const re = new RegExp(`^\\s*${n}(\\s|$)`);
        const isSteps = (text) => /^\s*1(\s|$)/.test(text || '');
        const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 40)));
        const scrollTo = (el, offset) => {
            const top = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop + offset;
            scroller.scrollTop = Math.max(0, top - scroller.clientHeight / 2);
        };
        for (let attempt = 0; attempt < 20; attempt++) {
            const cm = [...content.querySelectorAll('.cm-content')].find((c) => isSteps((c.querySelector('.cm-line') || {}).textContent));
            if (cm) {
                const lines = [...cm.querySelectorAll('.cm-line')];
                const hit = lines.find((l) => re.test(l.textContent));
                if (hit) {
                    hit.scrollIntoView({ block: 'center' });
                    hit.classList.add('fm-step-hit');
                    setTimeout(() => hit.classList.remove('fm-step-hit'), 4000);
                    return true;
                }
                const nums = lines.map((l) => parseInt(l.textContent, 10)).filter((x) => !Number.isNaN(x));
                const h = (lines[0] && lines[0].getBoundingClientRect().height) || 18;
                if (nums.length) {
                    const lo = Math.min(...nums), hi = Math.max(...nums);
                    scroller.scrollTop += (n > hi ? n - hi + 5 : n < lo ? -(lo - n + 5) : 0) * h;
                } else {
                    scrollTo(cm, 0);
                }
            } else {
                const code = [...content.querySelectorAll('pre code')].find((c) => isSteps(c.textContent));
                if (!code) return false;
                const idx = code.textContent.split('\n').findIndex((l) => re.test(l));
                if (idx < 0) return false;
                const lh = parseFloat(getComputedStyle(code).lineHeight) || 18;
                scrollTo(code, idx * lh);
            }
            await frame();
        }
        return false;
    }

    // ---- Public API -----------------------------------------------------------------
    FM.tools = new Proxy({}, {
        get: (_, name) => (tools[name] ? { ...asWebMcp(tools[name]), execute: (args) => execute(name, args) } : undefined),
        ownKeys: () => Object.keys(tools),
        getOwnPropertyDescriptor: (_, name) => (tools[name] ? { enumerable: true, configurable: true } : undefined),
        has: (_, name) => name in tools,
    });
    FM.webmcp = {
        call, execute, onRoute, search, renderResultsRoute, highlightStep,
        get native() { return registeredNatively.size > 0; },
        get registered() { return Object.keys(exposed); },
        status,
    };
})();
