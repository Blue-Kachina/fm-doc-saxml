# viewer-vendor

Builds the HTML viewer's Markdown renderer (Milkdown Crepe, CodeMirror's language
support and fmscriptui's FileMaker calculation grammar) into
`src/fm_saxml/render/html/vendor/`, which ships in the wheel and is copied into each
docs folder's `_viewer/vendor/`. The viewer then works offline and from `file://`, and
doesn't depend on a CDN. Users only need Python; Node is needed only to rebuild.

The output is committed. Rebuild it after changing a version in `package.json`:

```
cd viewer-vendor
npm install        # updates package-lock.json; use `npm ci` to rebuild the locked versions as-is
npm run build
```

Then run the tests and check the viewer in a browser (`fm-saxml build ... --html`).

Notes:

- `crepe.js` is a classic script (IIFE) that sets `window.FMVendor`, because browsers
  don't load local ES modules on `file://` pages.
- It's one bundle so Crepe and the FileMaker grammar share one `@codemirror/language`
  instance, which CodeMirror's Language facet requires. Check `npm ls @codemirror/language`
  shows a single version after an upgrade.
- `codemirror` is pinned to 6.0.2: npm's 6.65.7 is a mis-published v5 build.
- `@codemirror/language-data` is stubbed out (it would inline every grammar). The docs
  only have ```` ```filemaker ```` fences; to highlight another language, import its
  `@codemirror/lang-*` package in `entry.js` and add it to the viewer's list.
- `THIRD_PARTY_LICENSES.txt` is regenerated from the packages that end up in the bundle.
