"""Images of a FileMaker file: the ``<LibraryCatalog>`` and icons stored inline on layout objects.

Only the HTML viewer's layout preview uses them (button icons and graphics, layout_preview.md P5).
They are kept off the contract model: the normalizer keeps them beside it (``DocumentModel._library``).

``<LibraryCatalog><BinaryData><LibraryReference id key/><StreamList><Stream name type size>``:
the ``MAIN`` stream (type ``id``) names the stream that holds the picture (``SVG `` with a
space, ``PNGf``, ``JPEG``, ``GIFf``, ``PDF ``); ``GLPH`` marks an SVG icon that takes the
style's icon colour. Layout objects point at an entry by key (SaXML 2.3:
``<IconData><BinaryData><LibraryReference key/>``, ``<Graphic><BinaryData>…``), or carry the
same ``<StreamList>`` inline (SaXML 2.2). ``FNAM`` (the original file name, sometimes a full
path with a user name) and the other streams are never read.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Any

from lxml import etree

from ._helpers import attr, find_all_children, find_child, text_of

# MAIN stream → kind. Kinds the viewer can draw; anything else is kept as "other".
KINDS = {"SVG ": "svg", "PNGf": "png", "JPEG": "jpeg", "GIFf": "gif", "PDF ": "pdf", "BMPf": "bmp", "TIFF": "tiff"}
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def extract_library(container: etree._Element) -> dict[str, dict[str, Any]]:
    """``{key: entry}`` for each ``<LibraryCatalog>`` entry (see ``parse_streams`` for the entry)."""
    catalog = find_child(container, "LibraryCatalog")
    if catalog is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for binary in find_all_children(catalog, "BinaryData"):
        ref = find_child(binary, "LibraryReference")
        key = library_key(attr(ref, "key") or attr(ref, "id")) if ref is not None else None
        entry = parse_streams(find_child(binary, "StreamList"))
        if key and entry is not None:
            out[key] = entry
    return out


def library_key(key: str | None) -> str | None:
    """A catalog key as a file name: FileMaker's are 32 hex digits; anything else is hashed."""
    if not key:
        return None
    return key if _SAFE_KEY_RE.match(key) else "h" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]


def parse_streams(stream_list: etree._Element | None) -> dict[str, Any] | None:
    """``{kind, data, glyph}`` of a ``<StreamList>``: ``data`` is the picture's bytes (``None``
    when the export leaves them out), ``glyph`` whether an SVG takes the style's icon colour."""
    if stream_list is None:
        return None
    streams = {attr(s, "name"): s for s in find_all_children(stream_list, "Stream")}
    main = streams.get("MAIN")
    name = (main.text or "") if main is not None else ""  # not stripped: "SVG " ends in a space
    if not name.strip():
        return None
    data_elem = streams.get(name)
    if data_elem is None:
        data_elem = streams.get(name.strip())
    glyph = streams.get("GLPH")
    return {
        "kind": KINDS.get(name[:4].ljust(4), "other"),
        "data": _decode(data_elem) if data_elem is not None else None,
        "glyph": glyph is not None and text_of(glyph).strip() not in ("", "00"),
    }


def object_image(binary: etree._Element | None) -> tuple[str | None, dict[str, Any] | None]:
    """The image a ``<BinaryData>`` on a layout object points at: ``(key, inline entry or None)``.

    A catalog reference gives its key. An inline ``<StreamList>`` (SaXML 2.2) gives a key made
    from its bytes, so the same icon on many buttons is written once, and the entry itself.
    """
    if binary is None:
        return None, None
    ref = find_child(binary, "LibraryReference")
    if ref is not None:
        return library_key(attr(ref, "key") or attr(ref, "id")), None
    entry = parse_streams(find_child(binary, "StreamList"))
    if entry is None:
        return None, None
    digest = hashlib.sha1(entry["kind"].encode() + (entry["data"] or b"")).hexdigest()[:24]
    return "i" + digest, entry


def _decode(stream: etree._Element) -> bytes | None:
    text = "".join((stream.text or "").split())
    if not text:
        return None
    try:
        if (attr(stream, "type") or "").lower() == "hex":
            return binascii.unhexlify(text)
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
