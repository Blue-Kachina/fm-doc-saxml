"""Detect FileMaker version and XML format variant from the root element."""

from __future__ import annotations

from lxml import etree


def detect_version(root: etree._Element) -> str:
    """Return a FileMaker version string from the <Product> element, or 'unknown'."""
    product = root.find("Product")
    if product is None:
        # Try with namespace
        for child in root:
            if child.tag.endswith("}Product") or child.tag == "Product":
                product = child
                break
    if product is not None:
        version = product.get("Version") or product.get("version") or ""
        build = product.get("Build") or product.get("build") or ""
        if version:
            return f"{version} (build {build})" if build else version
    return "unknown"


def strip_namespace(tag: str) -> str:
    """Remove XML namespace prefix from an element tag."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def get_ns(root: etree._Element) -> str:
    """Return the namespace URI of the root element, or empty string."""
    tag = root.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[0][1:]
    return ""


def ns(namespace: str, local: str) -> str:
    """Build a Clark-notation tag: {namespace}local."""
    if namespace:
        return f"{{{namespace}}}{local}"
    return local
