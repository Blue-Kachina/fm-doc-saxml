// The viewer's renderer as one classic script: file:// pages can't load local ES
// modules, so index.html loads this with <script src> and reads window.FMVendor.
// It's one bundle so Crepe, the FileMaker grammar and the viewer's script-step
// decorations and folding share one @codemirror/language, view and state, which the
// facets, state fields and effects require.
export { Crepe } from '@milkdown/crepe';
export {
    LanguageDescription, StreamLanguage,
    foldService, foldGutter, codeFolding, foldEffect, unfoldEffect, foldedRanges,
} from '@codemirror/language';
export { Decoration, ViewPlugin, EditorView, WidgetType, gutter, GutterMarker } from '@codemirror/view';
export { RangeSetBuilder, StateField, StateEffect } from '@codemirror/state';
export { filemakerCalc } from 'fmscriptui/filemaker-codemirror';
