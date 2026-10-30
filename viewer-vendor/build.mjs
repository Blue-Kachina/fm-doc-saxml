// Builds src/fm_saxml/render/html/vendor/ from the exact versions in package-lock.json.
// Run after changing package.json: `npm ci && npm run build` (see README.md).
import { build } from 'esbuild';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

const OUT = '../src/fm_saxml/render/html/vendor';
const require = createRequire(import.meta.url);
mkdirSync(OUT, { recursive: true });

// Crepe's default code-block languages are all of @codemirror/language-data, which
// would inline every grammar (a classic script can't be split into lazy chunks). The
// docs only have ```filemaker fences, and the viewer passes its own language list.
const noLanguageData = {
    name: 'no-language-data',
    setup(b) {
        b.onResolve({ filter: /^@codemirror\/language-data$/ }, () => ({ path: 'stub', namespace: 'no-language-data' }));
        b.onLoad({ filter: /.*/, namespace: 'no-language-data' }, () => ({ contents: 'export const languages = [];' }));
    },
};

const common = { bundle: true, minify: true, legalComments: 'none', metafile: true, logLevel: 'warning' };
const results = [await build({
    ...common,
    entryPoints: ['entry.js'],
    format: 'iife',
    globalName: 'FMVendor',
    target: 'es2020',
    define: {
        'process.env.NODE_ENV': '"production"',
        __VUE_OPTIONS_API__: 'false',
        __VUE_PROD_DEVTOOLS__: 'false',
        __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false',
    },
    plugins: [noLanguageData],
    outfile: join(OUT, 'crepe.js'),
})];
for (const [name, entry] of [['crepe.css', 'crepe.css'],
                             ['nord.css', require.resolve('@milkdown/crepe/theme/nord.css')],
                             ['nord-dark.css', require.resolve('@milkdown/crepe/theme/nord-dark.css')]]) {
    results.push(await build({ ...common, entryPoints: [entry], outfile: join(OUT, name) }));
}

// The notices of every package that ended up in the output (legalComments is off).
const packages = new Set();
for (const { metafile } of results) {
    for (const input of Object.keys(metafile.inputs)) {
        const m = input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//g);
        if (m) packages.add(m.at(-1).replace(/^node_modules\/|\/$/g, ''));
    }
}
let notices = 'Third-party software in crepe.js and the .css files here, built by viewer-vendor/build.mjs.\n';
for (const name of [...packages].sort()) {
    const dir = join('node_modules', name);
    const { version, license } = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
    const file = readdirSync(dir).find((f) => /^(licen[cs]e|copying)(\.|$)/i.test(f));
    const text = file ? readFileSync(join(dir, file), 'utf8').trim()
        : `No license file in the package; its package.json declares "${license}".`;
    notices += `\n${'='.repeat(78)}\n${name} ${version} (${license})\n${'='.repeat(78)}\n\n${text}\n`;
}
writeFileSync(join(OUT, 'THIRD_PARTY_LICENSES.txt'), notices);
console.log(`${packages.size} packages bundled; notices in ${OUT}/THIRD_PARTY_LICENSES.txt`);
if (!existsSync(join(OUT, 'crepe.js'))) process.exit(1);
