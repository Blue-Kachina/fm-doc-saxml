/* fm-saxml viewer: layout preview (written with --html unless --no-layout-preview).
 *
 * A classic script (file:// pages can't fetch() or import local modules). Each layout's
 * geometry is a data script, _viewer/data/<file>/layouts/<n>.js, loaded when the layout is
 * shown (render/html/layout_preview.py writes them). The preview draws the layout as
 * FileMaker's Layout mode does: parts as bands, every object at its position, in paint
 * order (an object's index is its z-order), with the theme's colours, borders and fonts
 * when the data has a style table ("Styled"; analyze/layout_css.py resolves them) or as a
 * wireframe coloured by kind ("Wireframe"). It is for finding things:
 * search, deep links (#/layout?doc=…&select=…), the objects under a point, tab / slide
 * panels and popovers, and objects outside the layout, too small to see, duplicated or
 * covered by an opaque object.
 *
 * Shown inline on layout pages (a folded block above the Markdown on narrow screens), on
 * the full-page route #/layout?doc=<layout docId>&file=<key>, and as "Show on layout"
 * links on layout object pages, field pages and the results view.
 */
(function () {
    'use strict';
    const FM = window.FMDocs;
    const DIR = 'layouts';

    // ---- Data registry (called by the data scripts) ---------------------------
    const store = { index: {}, layouts: {}, library: {} };
    FM.layoutPreviewIndex = (key, data) => { store.index[key] = data; };
    FM.layoutPreview = (key, docId, data) => { store.layouts[`${key}|${docId}`] = data; };
    // Icons and graphics (_viewer/data/<file>/library/<libKey>.js), written once per file.
    FM.layoutLibrary = (key, libKey, data) => { store.library[`${key}|${libKey}`] = data; };

    const loads = {};
    function load(key, name, dir) {
        dir = dir || DIR;
        const id = `${key}|${dir}|${name}`;
        if (!loads[id]) {
            loads[id] = new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.src = `_viewer/data/${encodeURIComponent(key)}/${dir}/${encodeURIComponent(name)}.js`;
                s.onload = () => { s.remove(); resolve(); };
                s.onerror = () => { s.remove(); delete loads[id]; reject(new Error(`Could not load ${s.src}`)); };
                document.head.appendChild(s);
            });
        }
        return loads[id];
    }

    const files = () => (FM.data && FM.data.layoutPreview && FM.data.layoutPreview.files) || [];
    // The file a page belongs to: the one whose folder is the longest prefix of its path.
    function fileForPath(path) {
        let best = null;
        for (const f of files()) {
            if ((!f.dir || path === f.dir || path.startsWith(f.dir + '/')) && (!best || f.dir.length > best.dir.length)) best = f;
        }
        return best;
    }
    function fileByKey(key) {
        const all = files();
        return all.find((f) => f.key === key) || (key ? null : all[0] || null);
    }
    async function indexOf(key) {
        await load(key, 'index');
        return store.index[key];
    }
    async function layoutEntry(key, docId) {
        const idx = await indexOf(key);
        const row = idx && idx.layouts.find((r) => r[0] === docId);
        return row ? { docId: row[0], n: row[1], name: row[2], count: row[3], path: row[4], problems: row[5] } : null;
    }
    async function layoutData(key, docId) {
        const entry = await layoutEntry(key, docId);
        if (!entry) return null;
        await load(key, String(entry.n));
        return store.layouts[`${key}|${docId}`] || null;
    }

    // ---- URLs -----------------------------------------------------------------
    // #/layout?doc=<layout docId>&file=<key>[&select=<object docId>][&highlight=<docId>,<docId>][&q=<text>]
    function urlFor(opts) {
        const p = new URLSearchParams();
        p.set('doc', opts.layout);
        if (opts.file) p.set('file', opts.file);
        if (opts.select) p.set('select', opts.select);
        if (opts.highlight && opts.highlight.length) p.set('highlight', [].concat(opts.highlight).join(','));
        if (opts.q) p.set('q', opts.q);
        return '#/layout?' + p.toString();
    }
    function parseRoute(hash) {
        const q = new URLSearchParams(String(hash).replace(/^#\/layout\??/, ''));
        const list = (v) => (v ? v.split(',').map((s) => s.trim()).filter(Boolean) : []);
        return { layout: q.get('doc') || '', file: q.get('file') || '', select: q.get('select') || '',
            highlight: list(q.get('highlight')), q: q.get('q') || '' };
    }
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const pageHref = (path) => (FM.ui ? FM.ui.hrefFor(path) : '#/' + path.split('/').map(encodeURIComponent).join('/'));

    // ---- Object kinds ---------------------------------------------------------
    const FIELD_TYPES = new Set(['Edit Box', 'Drop-down List', 'Pop-up Menu', 'Checkbox Set', 'Radio Button Set',
        'Drop-down Calendar', 'Container', 'Field']);
    const KINDS = {
        field: 'Field', text: 'Text', button: 'Button', portal: 'Portal', panel: 'Tab / slide control',
        popover: 'Popover', shape: 'Shape', web: 'Web viewer', other: 'Other',
    };
    function kindOf(o) {
        if (o.f || FIELD_TYPES.has(o.t)) return 'field';
        switch (o.t) {
            case 'Text': return 'text';
            case 'Button': case 'Popover Button': case 'Button Bar': case 'Grouped Button': return 'button';
            case 'Portal': return 'portal';
            case 'Tab Control': case 'Slide Control': case 'Panel': return 'panel';
            case 'PopoverPanel': return 'popover';
            case 'Rectangle': case 'Rounded Rectangle': case 'Oval': case 'Line': return 'shape';
            case 'Web Viewer': return 'web';
            default: return 'other';
        }
    }
    // Extra classes by type: an oval's or rounded rectangle's outline; a panel is drawn by its control.
    const SHAPES = { Oval: 'oval', 'Rounded Rectangle': 'rrect', Panel: 'pane' };
    const PROBLEMS = { out: 'Outside the layout', tiny: 'Tiny (≤ 2 pt)', dup: 'Exact duplicates', cov: 'Covered' };
    const PROBLEM_COUNTS = { out: 'outside', tiny: 'tiny', dup: 'duplicate', cov: 'covered' };
    const POP_SIDES = ['right', 'below', 'left', 'above'];
    const ANCHOR_NAMES = { t: 'top', l: 'left', r: 'right', b: 'bottom' };

    // Objects that hold others: FileMaker never draws their names, so neither does the preview
    // (Wireframe shows the name as a small caption in the corner, out of the contents' way).
    const CONTAINERS = new Set(['PopoverPanel', 'Portal', 'Panel', 'Tab Control', 'Slide Control', 'Button Bar',
        'Group', 'Grouped Button']);
    function shown(o) {
        if (o.f) return o.f.includes('::') ? o.f.slice(o.f.lastIndexOf('::') + 2) : o.f;
        if (CONTAINERS.has(o.t)) return '';
        return o.l || o.n || '';
    }
    function title(o) {
        return o.n || o.l || (o.f ? o.f : '') || `${o.t} #${o.id}`;
    }
    // What "Find on this layout" (and the WebMCP tools' text search) looks in.
    const fold = (s) => String(s || '').toLowerCase();
    function matchesText(o, text) {
        const t = fold(text).trim();
        return !!t && [o.l, o.f, o.n, o.s, o.tt, o.t, o.st, o.pt, o.tab && o.tab.l].some((v) => v && fold(v).includes(t));
    }

    // ---- Facts about one layout's data (shared by the drawing and the WebMCP tools) ----
    // Children, ancestors (nearest first), each control's panels and default panel, and
    // which objects are in a popover. Computed once per data object.
    const factsCache = new WeakMap();
    function facts(data) {
        let f = factsCache.get(data);
        if (f) return f;
        const objs = data.objects;
        const kids = objs.map(() => []);
        objs.forEach((o, i) => { if (o.pa !== undefined && kids[o.pa]) kids[o.pa].push(i); });
        // Ancestors, nearest first (guarding against a cycle in bad data).
        const ancestors = objs.map((o) => {
            const out = [];
            let p = o.pa;
            while (p !== undefined && p !== null && !out.includes(p) && objs[p]) { out.push(p); p = objs[p].pa; }
            return out;
        });
        const panelsOf = (c) => kids[c].filter((k) => objs[k].t === 'Panel');
        const controls = [];
        const defaultPanel = new Map(); // control index -> the panel in front when the layout opens
        objs.forEach((o, i) => {
            if (o.t !== 'Tab Control' && o.t !== 'Slide Control') return;
            const panels = panelsOf(i);
            controls.push(i);
            const def = o.t === 'Tab Control' && o.tab && Number.isInteger(o.tab.def) && o.tab.def < panels.length ? o.tab.def : 0;
            if (panels.length) defaultPanel.set(i, panels[def]);
        });
        const inPopover = objs.map((o, i) => o.t === 'PopoverPanel' || ancestors[i].some((a) => objs[a].t === 'PopoverPanel'));
        f = { kids, ancestors, panelsOf, controls, defaultPanel, inPopover };
        factsCache.set(data, f);
        return f;
    }
    // Shown when the layout opens: its tab / slide panels are the default ones, and it isn't in a popover.
    function visibleAtOpen(data, i) {
        const F = facts(data);
        for (const a of [i, ...F.ancestors[i]]) {
            const x = data.objects[a];
            if (x.t === 'Panel' && F.defaultPanel.has(x.pa) && F.defaultPanel.get(x.pa) !== a) return false;
            if (x.t === 'PopoverPanel') return false;
        }
        return true;
    }
    // The tab / slide panels and popovers an object only shows in, nearest first (as the
    // WebMCP layoutObject record's shownIn), with the tab's label.
    // A popover's name for people: its title, its button's label or name, else the panel's own name.
    // A label that is only a merge (<<…>>) says little, so the panel's name is added to it.
    function popLabel(panel, btn) {
        const own = panel.pt || (btn && (btn.l || btn.n)) || '';
        if (own && panel.n && own !== panel.n && /^<<[^>]*>>$/.test(own.trim())) return `${own} (${panel.n})`;
        return own || panel.n || `Popover #${panel.id}`;
    }
    function shownIn(data, i) {
        const F = facts(data);
        const objs = data.objects;
        const out = [];
        for (const a of F.ancestors[i]) {
            const x = objs[a];
            if (x.t === 'Panel') {
                const ctl = objs[x.pa] || {};
                const k = F.panelsOf(x.pa).indexOf(a);
                const slide = ctl.t === 'Slide Control';
                out.push({ docId: data.objPrefix + x.id, kind: slide ? 'slidePanel' : 'tabPanel', name: x.n || null,
                    label: slide ? `Slide ${k + 1}` : (x.tab && x.tab.l) || `Tab ${k + 1}` });
            } else if (x.t === 'PopoverPanel') {
                const btn = x.pa !== undefined ? objs[x.pa] : null;
                out.push({ docId: data.objPrefix + x.id, kind: 'popover', name: x.n || null,
                    label: popLabel(x, btn) });
            }
        }
        return out;
    }
    function partOf(data, o) {
        const parts = data.parts || [];
        const named = o.p && parts.find((p) => p.type === o.p || p.name === o.p);
        if (named) return named;
        if (!o.b) return null;
        const cy = (o.b[0] + o.b[2]) / 2;
        return parts.find((p) => cy >= p.top && cy < p.top + p.height) || null;
    }
    // Where an object is, in words: "Body, top right, inside the 'Devis' tab".
    function position(data, i) {
        const F = facts(data);
        const objs = data.objects;
        const o = objs[i];
        const part = partOf(data, o);
        const out = [o.p || (part && (part.name || part.type)) || ''];
        if (o.b) {
            const [t, l, b, r] = o.b;
            const W = data.width || 0, H = data.height || 0;
            const past = [];
            if (!F.inPopover[i]) {
                if (l < 0) past.push(`${+(-l).toFixed(2)} pt left of its left edge`);
                if (t < 0) past.push(`${+(-t).toFixed(2)} pt above its top`);
                if (W && r > W) past.push(`${+(r - W).toFixed(2)} pt past its right edge`);
                if (H && b > H) past.push(`${+(b - H).toFixed(2)} pt below its last part`);
            }
            if (past.length) out.push(`outside the layout (${past.join(', ')})`);
            else {
                const cx = (l + r) / 2, cy = (t + b) / 2;
                const width = W || cx * 2 || 1;
                const h = cx < width / 3 ? 'left' : cx > width * 2 / 3 ? 'right' : 'center';
                const top = part ? part.top : 0, height = part ? part.height : H || cy * 2 || 1;
                const rel = height > 0 ? (cy - top) / height : 0.5;
                const v = rel < 1 / 3 ? 'top' : rel > 2 / 3 ? 'bottom' : 'middle';
                out.push(v === 'middle' && h === 'center' ? 'center' : `${v} ${h}`);
            }
        }
        const inside = [];
        for (const a of [...F.ancestors[i]].reverse()) {
            const x = objs[a];
            if (x.t === 'Panel') {
                const ctl = objs[x.pa] || {};
                const k = F.panelsOf(x.pa).indexOf(a);
                inside.push(ctl.t === 'Slide Control' ? `slide ${k + 1} of a slide control` : `the '${(x.tab && x.tab.l) || `Tab ${k + 1}`}' tab`);
            } else if (x.t === 'PopoverPanel') {
                const btn = x.pa !== undefined ? objs[x.pa] : null;
                const label = x.pt || (btn && (btn.l || btn.n));
                inside.push(label ? `the '${label}' popover` : 'a popover');
            } else if (x.t === 'Portal') inside.push(`row 1 of the ${x.n ? `'${x.n}' ` : ''}portal`);
            else if (x.t === 'Button Bar') inside.push('a button bar');
            else if (x.t === 'Group' || x.t === 'Grouped Button') inside.push('a group');
        }
        let text = out.filter(Boolean).join(', ');
        if (inside.length) text += `${text ? ', ' : ''}inside ${inside.join(', inside ')}`;
        if (o.hc) text += ' (has a hide condition)';
        return text;
    }
    // ---- Images (icons and graphics) ----------------------------------------------
    // o.ic = [libKey, placement, size in pt]; o.im = libKey; data.lib[libKey] = {k: kind, g: 1 for a
    // glyph that takes the style's icon colour, x: why it wasn't written}.
    const ICON_PLACES = { 1: 'icon only', 2: 'above the label', 3: 'below the label', 4: 'left of the label', 5: 'right of the label' };
    const SKIPPED = {
        images: 'not included (pictures and SVG graphics need --layout-images)',
        size: 'not included (over the size limit)', type: 'not included (a kind the viewer can\'t show)',
        missing: 'not in the export', invalid: 'not included (not a usable SVG)',
    };
    function imageInfo(data, libKey) {
        const e = (data.lib && data.lib[libKey]) || {};
        const out = { libraryKey: libKey, kind: e.k || 'unknown', included: !!e.k && !e.x };
        if (e.g) out.glyph = true;
        if (e.x) out.note = SKIPPED[e.x] || e.x;
        return out;
    }
    const LIB_KEY = /^[\w-]{1,64}$/;
    const MIMES = new Set(['image/png', 'image/jpeg', 'image/gif']);
    async function libraryImage(key, libKey) {
        if (!LIB_KEY.test(libKey)) return null;
        await load(key, libKey, 'library');
        return store.library[`${key}|${libKey}`] || null;
    }
    // A data: URL for an image entry, or '' when it doesn't look like one of ours.
    function imageSrc(img) {
        if (!img) return '';
        if (img.k === 'svg' && typeof img.svg === 'string') return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(img.svg);
        if (MIMES.has(img.m) && typeof img.d === 'string' && /^[A-Za-z0-9+/]*={0,2}$/.test(img.d)) return `data:${img.m};base64,${img.d}`;
        return '';
    }

    const absoluteUrl = (hash) => location.href.split('#')[0] + hash;
    // One object as the WebMCP tools return it. Bounds are absolute (points from the layout's top left).
    function describe(key, data, i) {
        const o = data.objects[i];
        const docId = data.objPrefix + o.id;
        const out = { docId, objectId: o.id, objectType: o.t, name: title(o), layout: data.name, layoutDocId: data.docId };
        if (o.f) out.field = o.f;
        if (o.l && o.l !== out.name) out.label = o.l;
        if (o.s) out.script = o.s;
        if (o.st) out.action = o.st;
        if (o.p) out.part = o.p;
        if (o.b) {
            const [t, l, b, r] = o.b;
            out.bounds = { top: t, left: l, bottom: b, right: r, width: +(r - l).toFixed(2), height: +(b - t).toFixed(2) };
        }
        const si = shownIn(data, i);
        if (si.length) out.shownIn = si;
        out.visibleAtOpen = visibleAtOpen(data, i);
        if (o.hc) out.hideCondition = o.hc;
        if (o.x) out.problems = o.x.map((p) => PROBLEM_COUNTS[p] || p);
        if (o.cv !== undefined && data.objects[o.cv]) out.coveredBy = data.objPrefix + data.objects[o.cv].id;
        if (o.sy !== undefined && data.styles && data.styles[o.sy]) out.style = Object.assign({}, data.styles[o.sy]);
        if (o.ic) out.icon = Object.assign({ placement: ICON_PLACES[o.ic[1]] || String(o.ic[1]), size: o.ic[2] }, imageInfo(data, o.ic[0]));
        if (o.im) out.image = imageInfo(data, o.im);
        out.z = i + 1;
        out.position = position(data, i);
        if (o.pg) out.path = (o.pg.includes('/') ? '' : data.objDir) + o.pg;
        out.previewUrl = absoluteUrl(urlFor({ layout: data.docId, file: key, select: docId }));
        return out;
    }
    // Hit test on the data: object indexes at a point {x, y} or overlapping a rect {top, left,
    // bottom, right} (entirely inside it with within), front to back, popover contents first.
    // Panels are left out (they cover their whole control). visibleAtOpen keeps only what shows
    // when the layout opens.
    function hitTest(data, where, opts) {
        opts = opts || {};
        const F = facts(data);
        const objs = data.objects;
        const out = [];
        const r = where.rect;
        for (let i = objs.length - 1; i >= 0; i--) {
            const o = objs[i];
            if (!o.b || o.t === 'Panel') continue;
            if (opts.visibleAtOpen && !visibleAtOpen(data, i)) continue;
            const [t, l, b, rt] = o.b;
            const hit = r ? (where.within ? t >= r.top && l >= r.left && b <= r.bottom && rt <= r.right
                : !(rt < r.left || l > r.right || b < r.top || t > r.bottom))
                : where.x >= l && where.x <= rt && where.y >= t && where.y <= b;
            if (hit) out.push(i);
        }
        return out.sort((a, b) => (F.inPopover[b] - F.inPopover[a]) || (b - a));
    }

    // ---- Styles ---------------------------------------------------------------
    const CSS = `
:root {
    --lp-out: #e9ecf1; --lp-layout: #ffffff; --lp-band: #fafbfc; --lp-band-line: #c3c9d2; --lp-ink: #1f2933;
    --lp-field: #3b6ea8; --lp-text: #66717f; --lp-button: #2e8b57; --lp-portal: #b26b00; --lp-panel: #7d5ba6;
    --lp-popover: #b0457a; --lp-shape: #98a2ad; --lp-web: #1f8a8a; --lp-other: #7b8592;
    --lp-hit: #e8590c; --lp-sel: #d6336c; --lp-hc: #c0392b;
}
@media (prefers-color-scheme: dark) {
    :root {
        --lp-out: #12151a; --lp-layout: #1b1f26; --lp-band: #1f242c; --lp-band-line: #3a424e; --lp-ink: #dde3ea;
        --lp-field: #88b4e7; --lp-text: #9aa4b1; --lp-button: #6cc497; --lp-portal: #e0a556; --lp-panel: #b79be0;
        --lp-popover: #e38bb6; --lp-shape: #6f7986; --lp-web: #5cc2c2; --lp-other: #8b95a3;
        --lp-hit: #ff8a4c; --lp-sel: #ff6b9a; --lp-hc: #e57373;
    }
}
.fm-lp-extra { padding: 8px 40px 0; }
.fm-lp-extra:empty { display: none; }
@media (max-width: 800px) { .fm-lp-extra { padding: 8px 16px 0; } }
.fm-lp-links { color: var(--muted); font-size: 13px; padding: 2px 0; }
.fm-lp-links a { color: var(--accent); text-decoration: none; }
.fm-lp-links a:hover { text-decoration: underline; }
details.fm-lp-block { border: 1px solid var(--border); border-radius: 8px; background: var(--panel); }
details.fm-lp-block > summary { cursor: pointer; padding: 6px 10px; font-weight: 600; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
details.fm-lp-block > summary .fm-lp-meta { font-weight: 400; color: var(--muted); font-size: 12px; }
details.fm-lp-block > summary a { margin-left: auto; font-weight: 400; font-size: 12px; color: var(--accent); text-decoration: none; }
details.fm-lp-block > .fm-lp { border-top: 1px solid var(--border); }
.fm-lp-route { padding: 12px 40px 24px; }
@media (max-width: 800px) { .fm-lp-route { padding: 10px 16px 20px; } }
.fm-lp-route h1 { font-size: 1.3em; margin: 4px 0 2px; }
.fm-lp-route .fm-lp-sub { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.fm-lp-route .fm-lp-sub a { color: var(--accent); text-decoration: none; }
.fm-lp-route .fm-lp { border: 1px solid var(--border); border-radius: 8px; background: var(--panel); }
.fm-lp { position: relative; font-size: 13px; }
.fm-lp button, .fm-lp select, .fm-lp input[type=search] {
    font: inherit; font-size: 12px; color: var(--text); background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 3px 8px;
}
.fm-lp button { cursor: pointer; }
.fm-lp button[aria-pressed=true] { background: var(--active-bg); color: var(--accent); border-color: var(--accent); }
.fm-lp-bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 8px 10px; }
.fm-lp-bar input[type=search] { width: min(260px, 100%); min-width: 120px; }
.fm-lp-bar .fm-lp-count { color: var(--muted); font-size: 12px; min-width: 5em; }
.fm-lp-bar .fm-lp-zoom { margin-left: auto; display: inline-flex; gap: 4px; }
.fm-lp-badges { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 0 10px 8px; font-size: 12px; color: var(--muted); }
.fm-lp-badges button { border-radius: 999px; }
.fm-lp-badges button .n { font-weight: 700; color: var(--lp-hc); margin-left: 4px; }
.fm-lp-body { display: flex; align-items: flex-start; border-top: 1px solid var(--border); }
/* stable gutter: Fit scales to clientWidth, so a scrollbar that comes and goes would make Fit oscillate */
.fm-lp-scroll { flex: 1 1 auto; min-width: 0; overflow: auto; scrollbar-gutter: stable; max-height: 70vh; background: var(--lp-out); position: relative; }
/* no min-height: the box is as tall as the drawn layout (a short one at Fit is a thin strip), up to the screen */
.fm-lp-full .fm-lp-scroll { max-height: calc(100vh - 230px); align-self: flex-start; }
.fm-lp-canvas { position: relative; }
.fm-lp-stage { position: absolute; left: 0; top: 0; transform-origin: 0 0; font: 11px/1.2 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--lp-ink); }
.fm-lp-layoutbox { position: absolute; background: var(--lp-layout); box-shadow: 0 0 0 1px var(--lp-band-line); }
.fm-lp-part { position: absolute; border-bottom: 1px dashed var(--lp-band-line); pointer-events: none; }
.fm-lp-part:nth-of-type(even) { background: var(--lp-band); }
.fm-lp-part > span { position: absolute; left: 2px; bottom: 1px; font-size: 10px; color: var(--muted); opacity: .8; white-space: nowrap; }
.fm-lp-o {
    --c: var(--lp-other);
    position: absolute; box-sizing: border-box; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    border: 1px solid color-mix(in srgb, var(--c), transparent 15%); background: color-mix(in srgb, var(--c), transparent 90%);
    padding: 0 3px; cursor: pointer; min-width: 1px; min-height: 1px;
}
.fm-lp-o > .t { pointer-events: none; }
.fm-lp-o > .t.cap { position: absolute; top: 1px; left: 3px; max-width: calc(100% - 6px); overflow: hidden; text-overflow: ellipsis;
    font-size: 8px; line-height: 1; opacity: .6; padding: 0; }
.fm-lp-stage.styled .fm-lp-o > .t.cap { display: none; }
.fm-lp-o.k-field { --c: var(--lp-field); }
.fm-lp-o.k-text { --c: var(--lp-text); background: transparent; border-style: dotted; }
.fm-lp-o.k-button { --c: var(--lp-button); border-radius: 4px; text-align: center; }
.fm-lp-o.k-portal { --c: var(--lp-portal); }
.fm-lp-o.k-panel { --c: var(--lp-panel); }
.fm-lp-o.k-popover { --c: var(--lp-popover); background: var(--lp-layout); box-shadow: 0 4px 16px rgba(0,0,0,.25); }
.fm-lp-o.k-shape { --c: var(--lp-shape); background: transparent; }
.fm-lp-o.k-web { --c: var(--lp-web); }
.fm-lp-o.oval { border-radius: 50%; }
.fm-lp-o.rrect { border-radius: 6px; }
.fm-lp-o.pane { border: 0; background: transparent; pointer-events: none; }
.fm-lp-o.hc { outline: 1px dashed var(--lp-hc); outline-offset: -1px;
    background-image: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in srgb, var(--lp-hc), transparent 88%) 5px 7px); }
.fm-lp-o.off { display: none; }
.fm-lp-bar .fm-lp-mode { display: inline-flex; gap: 4px; }
/* Styled: the theme's look (per-style rules are written per preview, see styleSheet). */
.fm-lp-stage.styled { color: #000; }
.fm-lp-stage.styled .fm-lp-layoutbox { background: #fff; }
.fm-lp-stage.styled .fm-lp-part { background: transparent; border-bottom-color: rgba(0,0,0,.18); }
.fm-lp-stage.styled .fm-lp-part > span { color: rgba(0,0,0,.45); }
.fm-lp-stage.styled .fm-lp-o {
    border: 0 solid transparent; background-color: transparent; border-radius: 0; padding: 0 2px; color: inherit;
    display: flex; flex-direction: column; justify-content: center; text-align: left;
}
.fm-lp-stage.styled .fm-lp-o > .t { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-lp-stage.styled .fm-lp-o.k-popover { background-color: #fff; }
.fm-lp-stage.styled .fm-lp-o.oval { border-radius: 50%; }
.fm-lp-stage.styled .fm-lp-o.pane { border: 0; background: transparent; }
.fm-lp-stage.styled .fm-lp-o.hc { background-image: none; outline-color: color-mix(in srgb, var(--lp-hc), transparent 45%); }
.fm-lp-stage.styled .fm-lp-o.off { display: none; }
.fm-lp-stage.styled .fm-lp-o.line-h { border-right-width: 0 !important; border-bottom-width: 0 !important; border-left-width: 0 !important; background: transparent !important; padding: 0; }
.fm-lp-stage.styled .fm-lp-o.line-v { border-top-width: 0 !important; border-right-width: 0 !important; border-bottom-width: 0 !important; background: transparent !important; padding: 0; }
.fm-lp-stage.styled .fm-lp-tabs > b { color: #333; }
/* Icons and graphics (P5). A glyph is the SVG used as a mask, painted in the style's icon colour
   (Styled) or the kind's colour (Wireframe); other images are drawn as they are (faded in Wireframe). */
.fm-lp-ic { position: absolute; display: block; pointer-events: none; box-sizing: border-box; }
.fm-lp-ic.ip1 { left: 50%; top: 50%; transform: translate(-50%, -50%); }
.fm-lp-ic.ip2 { left: 50%; top: 3px; transform: translateX(-50%); }
.fm-lp-ic.ip3 { left: 50%; bottom: 3px; transform: translateX(-50%); }
.fm-lp-ic.ip4 { left: 4px; top: 50%; transform: translateY(-50%); }
.fm-lp-ic.ip5 { right: 4px; top: 50%; transform: translateY(-50%); }
.fm-lp-ic.ipf { left: 0; top: 0; width: 100%; height: 100%; }
.fm-lp-ic.glyph { background-color: var(--c); opacity: .85;
    -webkit-mask: var(--src) center / contain no-repeat; mask: var(--src) center / contain no-repeat; }
img.fm-lp-ic { object-fit: contain; opacity: .45; filter: grayscale(1); }
.fm-lp-o.ic1 > .t { visibility: hidden; }
.fm-lp-o.ic4 > .t { padding-left: var(--ics); }
.fm-lp-o.ic5 > .t { padding-right: var(--ics); }
.fm-lp-o.ic2 > .t { padding-top: var(--ics); }
.fm-lp-o.ic3 > .t { padding-bottom: var(--ics); }
.fm-lp-o.im-skip { border-style: dashed; }
.fm-lp-stage.styled .fm-lp-ic.glyph { background-color: var(--lp-ic, currentColor); opacity: 1; }
.fm-lp-stage.styled img.fm-lp-ic { opacity: 1; filter: none; }
.fm-lp-tabs { position: absolute; left: 0; top: 0; right: 0; pointer-events: none; }
.fm-lp-tabs > b {
    position: absolute; top: 0; box-sizing: border-box; overflow: hidden; text-overflow: ellipsis; font-weight: 400;
    border: 1px solid color-mix(in srgb, var(--lp-panel), transparent 40%); border-bottom: 0; border-radius: 4px 4px 0 0;
    padding: 2px 4px; text-align: center; pointer-events: auto; background: var(--lp-layout);
}
.fm-lp-tabs > b.on { background: color-mix(in srgb, var(--lp-panel), transparent 75%); font-weight: 600; }
.fm-lp-dots { position: absolute; left: 0; right: 0; bottom: 3px; text-align: center; pointer-events: none; }
.fm-lp-dots > b { display: inline-block; width: 7px; height: 7px; margin: 0 3px; border-radius: 50%; pointer-events: auto;
    background: color-mix(in srgb, var(--lp-panel), transparent 60%); }
.fm-lp-dots > b.on { background: var(--lp-panel); }
.fm-lp-stage.focusing .fm-lp-o:not(.hit) { opacity: .22; }
.fm-lp-stage.focusing .fm-lp-o.hit { outline: 2px solid var(--lp-hit); outline-offset: 1px; opacity: 1; }
.fm-lp-box { position: absolute; pointer-events: none; z-index: 2000000; box-sizing: border-box; }
.fm-lp-box.sel { outline: 2px solid var(--lp-sel); outline-offset: 2px; }
.fm-lp-box.cur { outline: 3px solid var(--lp-hit); outline-offset: 4px; }
.fm-lp-box[hidden] { display: none; }
.fm-lp-side { flex: 0 0 290px; max-width: 290px; border-left: 1px solid var(--border); padding: 8px 10px; max-height: 70vh; overflow: auto; font-size: 12px; }
.fm-lp-full .fm-lp-side { max-height: calc(100vh - 230px); }
.fm-lp-side h4 { margin: 10px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.fm-lp-side h4:first-child { margin-top: 0; }
.fm-lp-side label { display: block; padding: 2px 0; }
.fm-lp-side select { max-width: 100%; }
.fm-lp-side dl { margin: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; }
.fm-lp-side dt { color: var(--muted); }
.fm-lp-side dd { margin: 0; overflow-wrap: anywhere; }
.fm-lp-side a { color: var(--accent); text-decoration: none; }
.fm-lp-side a:hover { text-decoration: underline; }
.fm-lp-side ol { margin: 0; padding-left: 18px; }
.fm-lp-side ol button { border: 0; background: none; padding: 1px 0; color: var(--accent); text-align: left; }
.fm-lp-side ol li.on button { font-weight: 700; }
.fm-lp-side code { font-size: 11px; }
.fm-lp-legend { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.fm-lp-legend span::before { content: ""; display: inline-block; width: 9px; height: 9px; margin-right: 4px; border: 1px solid var(--c); background: color-mix(in srgb, var(--c), transparent 80%); vertical-align: -1px; }
.fm-lp-tip { position: fixed; z-index: 50; pointer-events: none; max-width: 340px; background: var(--panel); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 12px; box-shadow: 0 4px 14px rgba(0,0,0,.18); }
.fm-lp-tip[hidden] { display: none; }
.fm-lp-tip .m { color: var(--muted); }
.fm-lp-empty { padding: 16px; color: var(--muted); }
@media (max-width: 800px) {
    .fm-lp-body { flex-direction: column; align-items: stretch; }
    .fm-lp-side { flex: none; max-width: none; border-left: 0; border-top: 1px solid var(--border); max-height: none; }
    .fm-lp-scroll { max-height: 60vh; }
    .fm-lp-full .fm-lp-scroll { align-self: stretch; }
    .fm-lp-bar .fm-lp-zoom { margin-left: 0; }
}`;
    function injectStyles() {
        if (document.getElementById('fm-lp-css')) return;
        const style = document.createElement('style');
        style.id = 'fm-lp-css';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    // ---- Styles -----------------------------------------------------------------
    // The style table is plain CSS resolved in Python (analyze/layout_css.py). It is checked
    // again here: known properties only, and values without anything that could end a rule.
    const STYLE_PROPS = new Set(['background-color', 'color', 'font-family', 'font-size', 'font-weight', 'font-style',
        'text-align', 'vertical-align', 'border-color', 'border-width', 'border-style', 'border-radius', 'padding',
        ...['top', 'right', 'bottom', 'left'].flatMap((s) => [`border-${s}-color`, `border-${s}-width`, `border-${s}-style`, `padding-${s}`]),
        ...['top-left', 'top-right', 'bottom-right', 'bottom-left'].map((c) => `border-${c}-radius`), 'icon-color']);
    const SAFE_VALUE = /^[#\w\s.,%()"'-]{1,200}$/;
    const VALIGN = { top: 'flex-start', middle: 'center', bottom: 'flex-end' };
    function styleSheet(uid, styles) {
        const scope = `.fm-lp-stage[data-lpm="${uid}"].styled`;
        return styles.map((st, k) => {
            const decls = [];
            for (const [prop, value] of Object.entries(st || {})) {
                if (!STYLE_PROPS.has(prop) || !SAFE_VALUE.test(String(value))) continue;
                if (prop === 'vertical-align') { if (VALIGN[value]) decls.push(`justify-content:${VALIGN[value]}`); }
                else if (prop === 'icon-color') decls.push(`--lp-ic:${value}`); // painted by .fm-lp-ic.glyph
                else decls.push(`${prop}:${value}`);
            }
            return decls.length ? `${scope} .s${k}{${decls.join(';')}}` : '';
        }).join('\n');
    }
    // The look people chose last time (per browser; storage can be off or throw).
    const MODE_KEY = 'fm-saxml-layout-preview-mode';
    function savedMode() { try { return localStorage.getItem(MODE_KEY); } catch (e) { return null; } }
    function saveMode(m) { try { localStorage.setItem(MODE_KEY, m); } catch (e) { /* not stored */ } }
    let mounted = 0;

    // ---- One preview ------------------------------------------------------------
    // mount(root, data, {file, full, select, highlight, q, mode, onSelect}) draws a layout into root.
    function mount(root, data, opts) {
        injectStyles();
        opts = opts || {};
        const objs = data.objects;
        const N = objs.length;
        const docIdOf = (i) => data.objPrefix + objs[i].id;
        const byDocId = new Map(objs.map((o, i) => [data.objPrefix + o.id, i]));
        const { ancestors, panelsOf, controls, inPopover } = facts(data);
        const tabSel = new Map(facts(data).defaultPanel); // control index -> shown panel index
        const popovers = objs.map((o, i) => (o.t === 'PopoverPanel' ? i : -1)).filter((i) => i >= 0);
        const popShown = new Set();
        let hideHc = false;

        // Stage extent: the layout, plus whatever sits outside it (drawn on the grey surround).
        const W = data.width || 0, H = data.height || 0;
        let minX = 0, minY = 0, maxX = W, maxY = H;
        for (const o of objs) {
            if (!o.b) continue;
            minX = Math.min(minX, o.b[1]); minY = Math.min(minY, o.b[0]);
            maxX = Math.max(maxX, o.b[3]); maxY = Math.max(maxY, o.b[2]);
        }
        const pad = 8;
        const offX = pad - minX, offY = pad - minY;
        const stageW = maxX - minX + 2 * pad, stageH = maxY - minY + 2 * pad;
        const layoutW = W || maxX;

        // Styled (theme colours, fonts, borders) when the data has styles, else the wireframe.
        const canStyle = !!(data.styles && data.styles.length);
        let mode = canStyle ? (opts.mode || savedMode() || 'styled') : 'wireframe';
        const uid = String(++mounted);

        const counts = data.problems || {};
        const problemBadges = Object.keys(PROBLEMS).filter((k) => counts[PROBLEM_COUNTS[k]] > 0)
            .map((k) => `<button type="button" data-problem="${k}" aria-pressed="false">${esc(PROBLEMS[k])}<span class="n">${counts[PROBLEM_COUNTS[k]]}</span></button>`).join('');
        root.innerHTML = `<div class="fm-lp${opts.full ? ' fm-lp-full' : ''}">
            <div class="fm-lp-bar">
                <input type="search" class="fm-lp-q" placeholder="Find on this layout…" aria-label="Find on this layout" autocomplete="off" spellcheck="false">
                <button type="button" class="fm-lp-prev" title="Previous match" aria-label="Previous match">↑</button>
                <button type="button" class="fm-lp-next" title="Next match" aria-label="Next match">↓</button>
                <button type="button" class="fm-lp-clear" title="Clear" aria-label="Clear the search">×</button>
                <span class="fm-lp-count" aria-live="polite"></span>
                ${canStyle ? `<span class="fm-lp-mode" role="group" aria-label="Look">
                    <button type="button" data-mode="styled" aria-pressed="false" title="The theme's colours, borders and fonts">Styled</button>
                    <button type="button" data-mode="wireframe" aria-pressed="false" title="Outlines coloured by kind of object">Wireframe</button>
                </span>` : ''}
                <span class="fm-lp-zoom">
                    <button type="button" data-zoom="fit" aria-pressed="true">Fit</button>
                    <button type="button" data-zoom="1" aria-pressed="false">100%</button>
                    <button type="button" data-zoom="2" aria-pressed="false">200%</button>
                </span>
            </div>
            <div class="fm-lp-badges">${problemBadges ? 'Problems: ' + problemBadges : `<span>${N} objects · no problems found</span>`}</div>
            <div class="fm-lp-body">
                <div class="fm-lp-scroll"><div class="fm-lp-canvas"><div class="fm-lp-stage"></div></div></div>
                <aside class="fm-lp-side"></aside>
            </div>
            <div class="fm-lp-tip" hidden></div>
        </div>`;
        const box = root.firstElementChild;
        const q = (sel) => box.querySelector(sel);
        const scroller = q('.fm-lp-scroll'), canvas = q('.fm-lp-canvas'), stage = q('.fm-lp-stage');
        const side = q('.fm-lp-side'), tip = q('.fm-lp-tip'), countEl = q('.fm-lp-count'), input = q('.fm-lp-q');

        // Draw: the layout's area, its parts, then every object back to front.
        const sy = (x) => (canStyle && Number.isInteger(x.sy) ? ` s${x.sy}` : '');
        let html = canStyle ? `<style>${styleSheet(uid, data.styles)}</style>` : '';
        html += `<div class="fm-lp-layoutbox${sy({ sy: data.bg })}" style="left:${offX}px;top:${offY}px;width:${layoutW}px;height:${H}px"></div>`;
        for (const p of data.parts || []) {
            html += `<div class="fm-lp-part${sy(p)}" style="left:${offX}px;top:${offY + p.top}px;width:${layoutW}px;height:${p.height}px"><span>${esc(p.name || p.type)}</span></div>`;
        }
        objs.forEach((o, i) => {
            if (!o.b) return;
            const [t, l, b, r] = o.b;
            const z = (inPopover[i] ? 1000000 : 10) + i;
            let inner = CONTAINERS.has(o.t) && !o.f
                ? (o.n && o.t !== 'Panel' ? `<span class="t cap">${esc(o.n)}</span>` : '')
                : `<span class="t">${esc(shown(o))}</span>`;
            if (o.t === 'Tab Control') inner = tabStrip(i, r - l);
            else if (o.t === 'Slide Control') inner = slideDots(i);
            let style = `left:${l + offX}px;top:${t + offY}px;width:${Math.max(r - l, 1)}px;height:${Math.max(b - t, 1)}px;z-index:${z}`;
            if (o.t === 'Portal' && o.pr && o.pr.rows > 1) {
                const rh = (b - t) / o.pr.rows;
                style += `;background-image:repeating-linear-gradient(to bottom,transparent 0 ${rh - 1}px,color-mix(in srgb,var(--lp-portal),transparent 55%) ${rh - 1}px ${rh}px)`;
            }
            const line = o.t === 'Line' ? (r - l >= b - t ? ' line-h' : ' line-v') : '';
            // Icons and graphics: an empty slot now, filled when its library script has loaded.
            let img = '';
            const drawable = (k) => !!(data.lib && data.lib[k] && !data.lib[k].x);
            if (o.ic && drawable(o.ic[0])) {
                const place = ICON_PLACES[o.ic[1]] ? o.ic[1] : 1;
                const size = Math.max(4, Math.min(Number(o.ic[2]) || 16, b - t, r - l));
                img += ` ic${place}`;
                style += `;--ics:${size + 4}px`;
                inner += `<i class="fm-lp-ic ip${place}" data-lib="${esc(o.ic[0])}" style="width:${size}px;height:${size}px"></i>`;
            }
            if (o.im) {
                if (drawable(o.im)) inner += `<i class="fm-lp-ic ipf" data-lib="${esc(o.im)}"></i>`;
                else img += ' im-skip';
            }
            const cls = `fm-lp-o k-${kindOf(o)}${SHAPES[o.t] ? ' ' + SHAPES[o.t] : ''}${o.hc ? ' hc' : ''}${line}${img}${sy(o)}`;
            html += `<div class="${cls}" data-i="${i}" data-id="${esc(o.id)}" style="${style}">${inner}</div>`;
        });
        html += '<div class="fm-lp-box sel" hidden></div><div class="fm-lp-box cur" hidden></div>';
        stage.innerHTML = html;
        stage.dataset.lpm = uid;
        stage.style.width = stageW + 'px';
        stage.style.height = stageH + 'px';
        const els = [];
        stage.querySelectorAll('.fm-lp-o').forEach((el) => { els[Number(el.dataset.i)] = el; });
        const selBox = q('.fm-lp-box.sel'), curBox = q('.fm-lp-box.cur');

        // Fill the icon / graphic slots (box.dataset.images: 'loading', then 'done').
        function drawImages() {
            const slots = Array.from(stage.querySelectorAll('.fm-lp-ic[data-lib]'));
            if (!slots.length) return;
            box.dataset.images = 'loading';
            Promise.all(slots.map(async (el) => {
                try {
                    const entry = await libraryImage(opts.file || '_', el.dataset.lib);
                    const src = imageSrc(entry);
                    if (!src) { el.remove(); return; }
                    if (entry.g) {
                        el.classList.add('glyph');
                        el.style.setProperty('--src', `url("${src}")`);
                    } else {
                        const pic = document.createElement('img');
                        pic.className = el.className;
                        pic.dataset.lib = el.dataset.lib;
                        pic.alt = '';
                        pic.setAttribute('style', el.getAttribute('style') || '');
                        pic.src = src;
                        el.replaceWith(pic);
                    }
                } catch (e) { el.remove(); }
            })).then(() => { box.dataset.images = 'done'; });
        }
        drawImages();

        function tabStrip(c, width) {
            const o = objs[c];
            const panels = panelsOf(c);
            if (!panels.length) return '';
            const h = (o.tab && o.tab.h) || 22;
            const even = width / panels.length;
            return '<div class="fm-lp-tabs">' + panels.map((p, k) => {
                const tab = objs[p].tab || {};
                const x = Number.isFinite(tab.x) ? tab.x : k * even;
                const w = Number.isFinite(tab.w) && tab.w > 0 ? tab.w : even;
                return `<b data-panel="${p}" style="left:${x}px;width:${w}px;height:${h}px" title="${esc(tab.l || `Tab ${k + 1}`)}">${esc(tab.l || `Tab ${k + 1}`)}</b>`;
            }).join('') + '</div>';
        }
        function slideDots(c) {
            const panels = panelsOf(c);
            return panels.length > 1 ? '<div class="fm-lp-dots">' + panels.map((p, k) => `<b data-panel="${p}" title="Slide ${k + 1}"></b>`).join('') + '</div>' : '';
        }

        // ---- Visibility: tab / slide panels, popovers, hide conditions ----------
        function visible(i) {
            const o = objs[i];
            if (hideHc && o.hc) return false;
            for (const a of [i, ...ancestors[i]]) {
                const x = objs[a];
                if (x.t === 'Panel' && x.pa !== undefined && tabSel.has(x.pa) && tabSel.get(x.pa) !== a) return false;
                if (x.t === 'PopoverPanel' && !popShown.has(a)) return false;
                if (a !== i && hideHc && x.hc) return false;
            }
            return true;
        }
        function applyVisibility() {
            for (let i = 0; i < N; i++) if (els[i]) els[i].classList.toggle('off', !visible(i));
            stage.querySelectorAll('[data-panel]').forEach((t) => {
                const p = Number(t.dataset.panel);
                t.classList.toggle('on', tabSel.get(objs[p].pa) === p);
            });
            placeBox(selBox, selected);
            placeBox(curBox, focus.cur >= 0 ? focus.ids[focus.cur] : -1);
        }
        // Make an object visible: bring its panels to the front and open its popovers.
        function reveal(i) {
            let changed = false;
            for (const a of [i, ...ancestors[i]]) {
                const x = objs[a];
                if (x.t === 'Panel' && tabSel.has(x.pa) && tabSel.get(x.pa) !== a) { tabSel.set(x.pa, a); changed = true; }
                if (x.t === 'PopoverPanel' && !popShown.has(a)) { popShown.add(a); changed = true; }
            }
            if (hideHc && (objs[i].hc || ancestors[i].some((a) => objs[a].hc))) { hideHc = false; changed = true; }
            if (changed) { applyVisibility(); renderLayers(); }
        }

        // ---- Look: Styled / Wireframe -----------------------------------------------
        function setMode(m) {
            mode = canStyle && m === 'styled' ? 'styled' : 'wireframe';
            stage.classList.toggle('styled', mode === 'styled');
            box.dataset.look = mode;
            box.querySelectorAll('[data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
            return mode;
        }
        const modeBar = box.querySelector('.fm-lp-mode');
        if (modeBar) {
            modeBar.addEventListener('click', (e) => {
                const b = e.target.closest('[data-mode]');
                if (b) saveMode(setMode(b.dataset.mode));
            });
        }
        setMode(mode);

        // ---- Zoom ----------------------------------------------------------------
        let zoomMode = 'fit', zoom = 1;
        function applyZoom() {
            if (zoomMode === 'fit') {
                const avail = scroller.clientWidth - 2;
                zoom = avail > 0 ? Math.min(2, avail / stageW) : 1;
            } else zoom = Number(zoomMode);
            stage.style.transform = `scale(${zoom})`;
            canvas.style.width = stageW * zoom + 'px';
            canvas.style.height = stageH * zoom + 'px';
            box.querySelectorAll('[data-zoom]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.zoom === String(zoomMode))));
        }
        box.querySelector('.fm-lp-zoom').addEventListener('click', (e) => {
            const b = e.target.closest('[data-zoom]');
            if (!b) return;
            zoomMode = b.dataset.zoom;
            applyZoom();
            const cur = selected >= 0 ? selected : -1;
            if (cur >= 0) scrollToObject(cur);
        });
        let resizeObs = null;
        if (typeof ResizeObserver !== 'undefined') {
            let lastW = -1;
            resizeObs = new ResizeObserver(() => { if (scroller.clientWidth !== lastW) { lastW = scroller.clientWidth; if (zoomMode === 'fit') applyZoom(); } });
            resizeObs.observe(scroller);
        }

        function placeBox(el, i) {
            const o = i >= 0 ? objs[i] : null;
            if (!o || !o.b || !visible(i)) { el.hidden = true; return; }
            el.hidden = false;
            el.style.left = o.b[1] + offX + 'px';
            el.style.top = o.b[0] + offY + 'px';
            el.style.width = Math.max(o.b[3] - o.b[1], 1) + 'px';
            el.style.height = Math.max(o.b[2] - o.b[0], 1) + 'px';
        }
        function scrollToObject(i) {
            const o = objs[i];
            if (!o || !o.b) return;
            const cx = (o.b[1] + o.b[3]) / 2 + offX, cy = (o.b[0] + o.b[2]) / 2 + offY;
            scroller.scrollLeft = Math.max(0, cx * zoom - scroller.clientWidth / 2);
            scroller.scrollTop = Math.max(0, cy * zoom - scroller.clientHeight / 2);
            // The preview may itself be below the fold of the page.
            const r = scroller.getBoundingClientRect();
            if (r.bottom < 0 || r.top > window.innerHeight) scroller.scrollIntoView({ block: 'nearest' });
        }

        // ---- Selection & details -------------------------------------------------
        let selected = -1;
        let stack = [];
        function select(i, opts2) {
            opts2 = opts2 || {};
            selected = i;
            if (i >= 0) {
                reveal(i);
                if (opts2.scroll !== false) scrollToObject(i);
            }
            if (!opts2.keepStack) stack = i >= 0 ? [i] : [];
            placeBox(selBox, i);
            renderSide();
            if (opts.onSelect) opts.onSelect(i >= 0 ? docIdOf(i) : null);
        }
        const objHref = (o) => (o.pg ? pageHref((o.pg.includes('/') ? '' : data.objDir) + o.pg) : null);
        function inLabel(i) {
            const out = [];
            for (const a of ancestors[i]) {
                const x = objs[a];
                if (x.t === 'Panel') {
                    const ctl = objs[x.pa] || {};
                    const k = panelsOf(x.pa).indexOf(a);
                    out.push(ctl.t === 'Slide Control' ? `slide ${k + 1}` : `tab "${(x.tab && x.tab.l) || k + 1}"`);
                } else if (x.t === 'PopoverPanel') {
                    const btn = x.pa !== undefined ? objs[x.pa] : null;
                    out.push(`popover "${popLabel(x, btn)}"`);
                } else if (x.t === 'Portal') out.push(x.n ? `portal "${x.n}"` : 'portal');
                else if (x.t === 'Button Bar') out.push(x.n ? `button bar "${x.n}"` : 'button bar');
            }
            return out.join(' › ');
        }
        function detailsHtml(i) {
            const o = objs[i];
            const rows = [];
            const row = (k, v) => { if (v) rows.push(`<dt>${esc(k)}</dt><dd>${v}</dd>`); };
            row('Type', esc(o.t));
            row('Name', o.n && esc(o.n));
            row('Label', o.l && esc(o.l));
            row('Field', o.f && (o.fp ? `<a href="${esc(pageHref(o.fp))}">${esc(o.f)}</a>` : esc(o.f)));
            row('Script', o.s && (o.sp ? `<a href="${esc(pageHref(o.sp))}">${esc(o.s)}</a>` : esc(o.s)));
            row('Action', o.st && `<code>${esc(o.st)}</code>`);
            row('Tooltip', o.tt && esc(o.tt));
            const imgRow = (info, extra) => `${esc(info.kind.toUpperCase())}${info.glyph ? ' glyph' : ''}${extra}`
                + (info.note ? ` <span class="m">(${esc(info.note)})</span>` : '');
            if (o.ic) row('Icon', imgRow(imageInfo(data, o.ic[0]), `, ${esc(ICON_PLACES[o.ic[1]] || o.ic[1])}, ${esc(o.ic[2])} pt`));
            if (o.im) row('Image', imgRow(imageInfo(data, o.im), ''));
            row('Hide when', o.hc && `<code>${esc(o.hc)}</code>`);
            row('Part', o.p && esc(o.p));
            row('In', esc(inLabel(i)));
            if (o.b) {
                const [t, l, b, r] = o.b;
                row('Bounds', `top ${t}, left ${l}, bottom ${b}, right ${r} <span class="m">(${+(r - l).toFixed(2)} × ${+(b - t).toFixed(2)} pt)</span>`);
            }
            if (o.pr) row('Portal', `${o.pr.rows} row${o.pr.rows === 1 ? '' : 's'}, from row ${o.pr.init}`);
            if (o.t === 'PopoverPanel' && o.pop !== undefined) row('Opens', esc(POP_SIDES[o.pop] || String(o.pop)));
            if (o.a) row('Anchors', esc(o.a === '-' ? 'none' : o.a.split('').map((c) => ANCHOR_NAMES[c] || c).join(', ')));
            if (o.x) row('Problems', esc(o.x.map((p) => PROBLEMS[p] || p).join(', ')));
            row('Z-order', `${i + 1} of ${N} <span class="m">(back to front)</span>`);
            const href = objHref(o);
            return `<h4>Selected</h4><dl>${rows.join('')}</dl>${href ? `<p><a class="fm-lp-objlink" href="${esc(href)}">Open the object's page →</a></p>` : ''}`;
        }
        function stackHtml() {
            if (stack.length < 2) return '';
            return `<h4>Objects here, front to back</h4><ol class="fm-lp-stack">${stack.map((i) => `<li${i === selected ? ' class="on"' : ''}><button type="button" data-pick="${i}">${esc(title(objs[i]))}</button> <span class="m">${esc(objs[i].t)}</span></li>`).join('')}</ol>`;
        }
        function layersHtml() {
            let out = '';
            const tabs = controls.filter((c) => panelsOf(c).length > 1);
            if (tabs.length) {
                out += '<h4>Panels</h4>' + tabs.map((c) => {
                    const o = objs[c];
                    const label = `${o.t === 'Slide Control' ? 'Slide control' : 'Tab control'}${o.n ? ' ' + o.n : ''} #${o.id}`;
                    const optsHtml = panelsOf(c).map((p, k) => {
                        const l = o.t === 'Slide Control' ? `Slide ${k + 1}` : (objs[p].tab && objs[p].tab.l) || `Tab ${k + 1}`;
                        return `<option value="${p}"${tabSel.get(c) === p ? ' selected' : ''}>${esc(l)}</option>`;
                    }).join('');
                    return `<label>${esc(label)}<br><select data-control="${c}">${optsHtml}</select></label>`;
                }).join('');
            }
            if (popovers.length) {
                out += '<h4>Popovers</h4>' + popovers.map((p) => {
                    const btn = objs[p].pa !== undefined ? objs[objs[p].pa] : null;
                    const label = popLabel(objs[p], btn);
                    return `<label><input type="checkbox" data-popover="${p}"${popShown.has(p) ? ' checked' : ''}> ${esc(label)}</label>`;
                }).join('');
            }
            const hcCount = objs.filter((o) => o.hc).length;
            if (hcCount) {
                out += `<h4>Hide conditions</h4><label><input type="checkbox" data-hidehc${hideHc ? ' checked' : ''}> Hide the ${hcCount} object${hcCount === 1 ? '' : 's'} with a hide condition</label>`;
            }
            out += '<h4>Legend</h4><div class="fm-lp-legend">' + Object.entries(KINDS).map(([k, l]) => `<span style="--c:var(--lp-${k})">${esc(l)}</span>`).join('')
                + (hcCount ? '<span style="--c:var(--lp-hc)">Has a hide condition</span>' : '') + '</div>';
            return out;
        }
        function renderSide() {
            const sel = selected >= 0 ? detailsHtml(selected) : '<h4>Selected</h4><p class="fm-muted">Click an object to see what it is. Hover for a summary.</p>';
            side.innerHTML = sel + stackHtml() + `<div class="fm-lp-layers">${layersHtml()}</div>`;
        }
        function renderLayers() {
            const l = side.querySelector('.fm-lp-layers');
            if (l) l.innerHTML = layersHtml();
        }
        side.addEventListener('change', (e) => {
            const t = e.target;
            if (t.dataset.control !== undefined) { tabSel.set(Number(t.dataset.control), Number(t.value)); applyVisibility(); }
            else if (t.dataset.popover !== undefined) { const p = Number(t.dataset.popover); if (t.checked) popShown.add(p); else popShown.delete(p); applyVisibility(); }
            else if (t.dataset.hidehc !== undefined) { hideHc = t.checked; applyVisibility(); }
        });
        side.addEventListener('click', (e) => {
            const b = e.target.closest('[data-pick]');
            if (b) select(Number(b.dataset.pick), { keepStack: true });
        });

        // ---- Pointer: hover summary, click = the objects under the point ----------
        function pointAt(e) {
            const r = stage.getBoundingClientRect();
            return { x: (e.clientX - r.left) / zoom - offX, y: (e.clientY - r.top) / zoom - offY };
        }
        function objectsAt(x, y) {
            const out = [];
            for (let i = N - 1; i >= 0; i--) {
                const o = objs[i];
                if (!o.b || !visible(i) || o.t === 'Panel') continue;
                if (x >= o.b[1] && x <= o.b[3] && y >= o.b[0] && y <= o.b[2]) out.push(i);
            }
            // Popovers float above the layout: their objects come first.
            return out.sort((a, b) => (inPopover[b] - inPopover[a]) || (b - a));
        }
        stage.addEventListener('click', (e) => {
            const tab = e.target.closest('[data-panel]');
            if (tab) {
                const p = Number(tab.dataset.panel);
                tabSel.set(objs[p].pa, p);
                applyVisibility();
                renderLayers();
                return;
            }
            const pt = pointAt(e);
            const here = objectsAt(pt.x, pt.y);
            stack = here;
            select(here.length ? here[0] : -1, { keepStack: true, scroll: false });
        });
        stage.addEventListener('mousemove', (e) => {
            const el = e.target.closest('.fm-lp-o');
            if (!el) { tip.hidden = true; return; }
            const o = objs[Number(el.dataset.i)];
            const lines = [`<strong>${esc(o.t)}</strong>${o.n ? ' ' + esc(o.n) : ''}`];
            if (o.f) lines.push(esc(o.f));
            else if (o.l) lines.push(esc(o.l));
            if (o.s) lines.push('Script: ' + esc(o.s));
            if (o.hc) lines.push('<span class="m">Has a hide condition</span>');
            if (o.b) lines.push(`<span class="m">top ${o.b[0]}, left ${o.b[1]} · ${+(o.b[3] - o.b[1]).toFixed(2)} × ${+(o.b[2] - o.b[0]).toFixed(2)} pt</span>`);
            tip.innerHTML = lines.join('<br>');
            tip.hidden = false;
            const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
            const y = e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16;
            tip.style.left = Math.max(4, x) + 'px';
            tip.style.top = Math.max(4, y) + 'px';
        });
        stage.addEventListener('mouseleave', () => { tip.hidden = true; });
        scroller.addEventListener('scroll', () => { tip.hidden = true; }, { passive: true });

        // ---- Focus set: search hits, deep-link highlights, problem filters --------
        const focus = { kind: '', ids: [], cur: -1 };
        function setFocus(kind, ids, go) {
            focus.kind = kind;
            focus.ids = ids;
            focus.cur = -1;
            for (let i = 0; i < N; i++) if (els[i]) els[i].classList.remove('hit');
            for (const i of ids) if (els[i]) els[i].classList.add('hit');
            stage.classList.toggle('focusing', !!kind);
            box.querySelectorAll('[data-problem]').forEach((b) => b.setAttribute('aria-pressed', String(kind === 'problem:' + b.dataset.problem)));
            if (go && ids.length) step(1); else { placeBox(curBox, -1); updateCount(); }
        }
        function updateCount() {
            if (!focus.kind) { countEl.textContent = ''; return; }
            countEl.textContent = focus.ids.length
                ? `${focus.cur >= 0 ? focus.cur + 1 : 0} of ${focus.ids.length}` : 'No matches';
        }
        function step(d) {
            if (!focus.ids.length) return;
            focus.cur = (focus.cur + d + focus.ids.length) % focus.ids.length;
            const i = focus.ids[focus.cur];
            reveal(i);
            placeBox(curBox, i);
            scrollToObject(i);
            updateCount();
            if (focus.ids.length === 1 || focus.kind === 'highlight' || focus.kind === 'search') { stack = [i]; selected = i; placeBox(selBox, i); renderSide(); }
        }
        function search(text) {
            if (!fold(text).trim()) { setFocus('', [], false); return []; }
            const ids = [];
            objs.forEach((o, i) => { if (matchesText(o, text)) ids.push(i); });
            setFocus('search', ids, true);
            return ids;
        }
        let searchTimer = null;
        input.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => search(input.value), 120); });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); clearTimeout(searchTimer); if (focus.kind === 'search' && fold(input.value).trim()) step(e.shiftKey ? -1 : 1); else search(input.value); }
            if (e.key === 'Escape') { input.value = ''; setFocus('', [], false); }
        });
        q('.fm-lp-next').addEventListener('click', () => step(1));
        q('.fm-lp-prev').addEventListener('click', () => step(-1));
        q('.fm-lp-clear').addEventListener('click', () => { input.value = ''; setFocus('', [], false); });
        box.querySelector('.fm-lp-badges').addEventListener('click', (e) => {
            const b = e.target.closest('[data-problem]');
            if (!b) return;
            const kind = 'problem:' + b.dataset.problem;
            if (focus.kind === kind) { setFocus('', [], false); return; }
            input.value = '';
            setFocus(kind, objs.map((o, i) => (o.x && o.x.includes(b.dataset.problem) ? i : -1)).filter((i) => i >= 0), true);
        });
        function highlight(docIds, go) {
            const ids = [].concat(docIds || []).map((d) => byDocId.get(d) ?? byDocId.get(data.objPrefix + d)).filter((i) => i !== undefined);
            input.value = '';
            setFocus(ids.length ? 'highlight' : '', ids, go !== false);
            return ids.map(docIdOf);
        }

        // ---- Start -----------------------------------------------------------------
        applyVisibility();
        applyZoom();
        renderSide();
        if (opts.highlight && opts.highlight.length) highlight(opts.highlight);
        if (opts.q) { input.value = opts.q; search(opts.q); }
        if (opts.select) {
            const i = byDocId.get(opts.select) ?? byDocId.get(data.objPrefix + opts.select);
            if (i !== undefined) select(i);
        }
        box.dataset.ready = '1';
        const api = {
            data, root: box, file: opts.file || '',
            select: (docId) => { const i = byDocId.get(docId) ?? byDocId.get(data.objPrefix + docId); if (i === undefined) return false; select(i); return true; },
            highlight, search: (text) => search(text).map(docIdOf),
            clear: () => { input.value = ''; setFocus('', [], false); select(-1, { scroll: false }); },
            objectsAt: (x, y) => objectsAt(x, y).map(docIdOf),
            visible: () => objs.map((o, i) => i).filter((i) => visible(i)).map(docIdOf),
            get selected() { return selected >= 0 ? docIdOf(selected) : null; },
            get zoom() { return zoom; },
            get mode() { return mode; },
            setMode: (m) => setMode(m),
            refit: () => applyZoom(),
            destroy: () => { if (resizeObs) resizeObs.disconnect(); root.innerHTML = ''; },
        };
        return api;
    }

    // ---- Where previews show up ----------------------------------------------------
    let current = null; // the preview on screen (inline or full page)
    let inline = null; // the layout page's preview block: {key, docId, details}, drawn when opened
    function setCurrent(p) {
        if (current && current !== p) current.destroy();
        current = p;
    }
    // The preview on screen, if it still is (other routes replace the page without telling us).
    const live = () => (current && current.root.isConnected ? current : null);

    // Inline block, field and object links, above a page's Markdown (index.html calls this per page).
    async function onPage(info) {
        setCurrent(null);
        inline = null;
        const slot = info && info.slot;
        if (!slot) return;
        slot.innerHTML = '';
        const meta = info.meta || {};
        const file = fileForPath(info.path);
        if (!file || !meta.docId) return;
        const seq = (slot._fmLpSeq = (slot._fmLpSeq || 0) + 1);
        const still = () => slot._fmLpSeq === seq;
        try {
            if (meta.entityType === 'layout') {
                const entry = await layoutEntry(file.key, meta.docId);
                if (!entry || !still()) return;
                const wide = !window.matchMedia || window.matchMedia('(min-width: 801px)').matches;
                const meta2 = `${entry.count} object${entry.count === 1 ? '' : 's'}${entry.problems ? ` · ${entry.problems} flagged` : ''}`;
                slot.innerHTML = `<details class="fm-lp-block"${wide ? ' open' : ''}><summary>Layout preview <span class="fm-lp-meta">${esc(meta2)}</span>`
                    + `<a class="fm-lp-full-link" href="${esc(urlFor({ layout: meta.docId, file: file.key }))}">Open full page ↗</a></summary><div class="fm-lp-host"></div></details>`;
                injectStyles();
                const details = slot.querySelector('details');
                const host = slot.querySelector('.fm-lp-host');
                const draw = async () => {
                    if (host.dataset.drawn) return;
                    host.dataset.drawn = '1';
                    const data = await layoutData(file.key, meta.docId);
                    if (!still()) return;
                    if (!data) { host.innerHTML = '<p class="fm-lp-empty">No preview data for this layout.</p>'; return; }
                    if (!data.objects.length) { host.innerHTML = '<p class="fm-lp-empty">This layout has no objects.</p>'; host.dataset.ready = '1'; return; }
                    setCurrent(mount(host, data, { file: file.key }));
                };
                inline = { key: file.key, docId: meta.docId, details };
                details.addEventListener('toggle', () => { if (details.open) draw(); });
                if (details.open) await draw();
            } else if (meta.entityType === 'layoutObject' && meta.layout) {
                const entry = await layoutEntry(file.key, meta.layout);
                if (!entry || !still()) return;
                slot.innerHTML = `<div class="fm-lp-links">Show on layout: <a class="fm-lp-show" href="${esc(urlFor({ layout: meta.layout, file: file.key, select: meta.docId }))}">${esc(entry.name)}</a></div>`;
            } else if (meta.entityType === 'field') {
                // This file's layouts, then other files' (a multi-file build lists those under xfields).
                const links = [];
                for (const f of [file, ...files().filter((x) => x !== file)]) {
                    const idx = await indexOf(f.key).catch(() => null);
                    if (!still()) return;
                    const uses = idx && (f === file ? idx.fields[meta.docId] : ((idx.xfields || {})[file.key] || {})[meta.docId]);
                    if (!uses) continue;
                    const byN = new Map(idx.layouts.map((r) => [r[1], r]));
                    const other = f === file ? '' : ` (${f.dir || f.key})`;
                    // ids are the objects' ids within the layout (docIds without the layout's objPrefix).
                    for (const [n, ids] of uses) {
                        const row = byN.get(n);
                        if (row) links.push(`<a class="fm-lp-show" href="${esc(urlFor({ layout: row[0], file: f.key, highlight: ids }))}">${esc(row[2] + other)}</a> <span class="fm-muted">(${ids.length})</span>`);
                    }
                }
                if (links.length) slot.innerHTML = `<div class="fm-lp-links">Show on layout: ${links.join(' · ')}</div>`;
            }
        } catch (err) {
            if (still()) slot.innerHTML = `<div class="fm-lp-links fm-error">${esc(err.message)}</div>`;
        }
    }
    // The full-page route: #/layout?doc=…&file=…
    async function renderRoute(container, hash) {
        injectStyles();
        setCurrent(null);
        inline = null;
        const r = parseRoute(hash);
        const file = fileByKey(r.file);
        if (!file || !r.layout) {
            container.innerHTML = `<div class="message">No layout preview for <code>${esc(r.layout || '(none)')}</code>.</div>`;
            return null;
        }
        let data;
        try { data = await layoutData(file.key, r.layout); } catch (err) { data = null; }
        if (!data) {
            container.innerHTML = `<div class="message">No layout preview for <code>${esc(r.layout)}</code>${files().length > 1 ? ` in ${esc(file.label || file.key)}` : ''}.</div>`;
            return null;
        }
        const multi = files().length > 1;
        container.innerHTML = `<div class="fm-lp-route"><h1>${esc(data.name)}</h1><div class="fm-lp-sub">Layout preview`
            + `${data.path ? ` · <a href="${esc(pageHref(data.path))}">Layout page</a>` : ''}${multi ? ` · ${esc(file.label || file.key)}` : ''}`
            + ` · ${data.objects.length} objects · ${data.width ? data.width + ' × ' : ''}${data.height} pt</div><div class="fm-lp-host"></div></div>`;
        const host = container.querySelector('.fm-lp-host');
        if (!data.objects.length) { host.innerHTML = '<p class="fm-lp-empty">This layout has no objects.</p>'; return data.path; }
        const onSelect = (docId) => {
            // Keep the URL a deep link to what is selected, without a new history entry.
            const now = parseRoute(location.hash);
            if (!/^#\/layout(\?|$)/.test(location.hash) || now.layout !== r.layout) return;
            const url = urlFor({ ...now, file: file.key, select: docId || '' });
            if (url !== location.hash) history.replaceState(null, '', url);
        };
        setCurrent(mount(host, data, { file: file.key, full: true, select: r.select, highlight: r.highlight, q: r.q, onSelect }));
        return data.path;
    }

    // "Show on layout" for a layoutObject row in the results view (webmcp.js).
    function objectLink(fileKey, layoutDocId, objectDocId) {
        if (!layoutDocId || !files().some((f) => f.key === fileKey)) return '';
        return `<a class="fm-lp-show" href="${esc(urlFor({ layout: layoutDocId, file: fileKey, select: objectDocId }))}">Show on layout</a>`;
    }

    // ---- JS API: open a layout's preview, highlight on it, clear ---------------------
    // For scripts and agents without WebMCP (and the WebMCP page tool show_on_this_layout).
    // A layout is given by docId or name; objects by docId or by the id after "::".
    async function findLayout(layout, fileKey) {
        const want = fold(layout).trim();
        if (!want) return null;
        const fs = fileKey ? files().filter((f) => f.key === fileKey || fold(f.dir) === fold(fileKey)) : files();
        const rows = [];
        for (const f of fs) {
            const idx = await indexOf(f.key);
            for (const r of (idx && idx.layouts) || []) rows.push({ key: f.key, r });
        }
        const hit = rows.find((x) => fold(x.r[0]) === want) || rows.find((x) => fold(x.r[2]) === want)
            || rows.find((x) => fold(x.r[0]) === 'layout:' + want);
        return hit ? { key: hit.key, docId: hit.r[0], name: hit.r[2], count: hit.r[3] } : null;
    }
    function waitForPreview(key, docId, ms) {
        const t0 = Date.now();
        return new Promise((resolve, reject) => {
            const tick = () => {
                const p = live();
                if (p && p.file === key && p.data.docId === docId) { resolve(p); return; }
                if (Date.now() - t0 > (ms || 15000)) { reject(new Error(`The preview of ${docId} did not open.`)); return; }
                setTimeout(tick, 40);
            };
            tick();
        });
    }
    // open(layout, {file, highlight, select, q}): shows the layout's preview (in place when it is
    // already on screen, or opening the layout page's folded block; otherwise the full-page
    // route) and applies the highlight / selection / search. Resolves once it is drawn.
    async function open(layout, o) {
        o = o || {};
        const hit = await findLayout(layout, o.file);
        if (!hit) throw new Error(`No layout preview for '${layout}'.`);
        const highlight = [].concat(o.highlight || []).map(String);
        const url = urlFor({ layout: hit.docId, file: hit.key, select: o.select, highlight, q: o.q });
        const result = { layout: hit.docId, name: hit.name, file: hit.key, url: absoluteUrl(url), highlighted: [] };
        let p = live();
        if (!(p && p.file === hit.key && p.data.docId === hit.docId)) p = null;
        if (!p && hit.count && inline && inline.key === hit.key && inline.docId === hit.docId && inline.details.isConnected) {
            if (!inline.details.open) inline.details.open = true; // its toggle event draws it
            p = await waitForPreview(hit.key, hit.docId);
        }
        if (p) {
            if (o.highlight !== undefined) result.highlighted = p.highlight(highlight);
            if (o.select) p.select(o.select);
            if (o.q) p.search(o.q);
            const r = p.root.getBoundingClientRect();
            if (r.bottom < 0 || r.top > window.innerHeight) p.root.scrollIntoView({ block: 'start' });
            return result;
        }
        if (!FM.ui) throw new Error('The viewer is not ready.');
        FM.ui.go(url);
        if (hit.count) {
            p = await waitForPreview(hit.key, hit.docId);
            const objs = new Set(p.data.objects.map((x) => p.data.objPrefix + x.id));
            result.highlighted = highlight.map((d) => (objs.has(d) ? d : p.data.objPrefix + d)).filter((d) => objs.has(d));
        }
        return result;
    }
    // highlight(ids) / clear() on the preview on screen; [] / false when there is none.
    function highlight(ids) { const p = live(); return p ? p.highlight([].concat(ids || []).map(String)) : []; }
    function clear() { const p = live(); if (!p) return false; p.clear(); return true; }

    FM.preview = {
        onPage, renderRoute, urlFor, parseRoute, objectLink, fileForPath,
        open, highlight, clear, findLayout,
        layout: (key, docId) => layoutData(key, docId),
        index: (key) => indexOf(key),
        // Reading a layout's data (for webmcp.js): one object described, a hit test, text search.
        describe, hitTest, matchesText, visibleAtOpen, shownIn, position,
        get current() { return live(); },
    };
})();
