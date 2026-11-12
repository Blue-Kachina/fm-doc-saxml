"""Layout -> theme (usesTheme) and custom theme -> base theme (derivedFrom) references."""

from fm_saxml.model.document_model import DocumentModel
from fm_saxml.model.document_model import SourceInfo
from fm_saxml.model.entities import ThemeEntity
from fm_saxml.normalize.ids import theme_doc_id
from fm_saxml.normalize.references import _link_themes


def _theme(name, base=None):
    return ThemeEntity(docId=theme_doc_id(name), name=name, fmpId="1", baseName=base)


def _model(*themes):
    model = DocumentModel(source=SourceInfo(fileName="t.xml"))
    for t in themes:
        model.entities.themes[t.doc_id] = t
    return model


def test_custom_theme_derived_from_base_in_file():
    base, custom = "com.filemaker.theme.apex_blue", "com.filemaker.theme.custom.ABC"
    model = _model(_theme(base), _theme(custom, base))
    _link_themes(model)
    [ref] = model.references
    assert (ref.source_doc_id, ref.target_doc_id, ref.relationship_type) == (
        theme_doc_id(custom), theme_doc_id(base), "derivedFrom")


def test_no_reference_when_base_not_in_file():
    model = _model(_theme("com.filemaker.theme.custom.ABC", "com.filemaker.theme.vibrant"))
    _link_themes(model)
    assert model.references == []
