// The viewer's renderer as one classic script: file:// pages can't load local ES
// modules, so index.html loads this with <script src> and reads window.FMVendor.
// It's one bundle so Crepe and the FileMaker grammar share one @codemirror/language,
// which the Language facet requires.
export { Crepe } from '@milkdown/crepe';
export { LanguageDescription } from '@codemirror/language';
export { filemakerCalc } from 'fmscriptui/filemaker-codemirror';
