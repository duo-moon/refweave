"""Parses Confluence storage format (XHTML) into an ordered list of
StructuralElement objects.

Scope: top-level elements only (headings, paragraphs, lists, tables, macros).
Inline content (links inside a paragraph, images, etc.) is left in `raw_html`
and mined by later stages (link extraction, chunker).
"""

from __future__ import annotations

import dataclasses
import html.entities
import logging
import re
from typing import Final

from lxml import etree

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.confluence.elements import ElementKind, StructuralElement
from refweave.plugins.source.atlassian.confluence.macros import (
    AC_NS,
    RI_NS,
    MacroHandler,
    UnknownMacro,
    default_registry,
    get_macro_name,
    serialize,
)

logger = logging.getLogger(__name__)

_HEADING_TAGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_LIST_TAGS: Final = frozenset({"ul", "ol"})
_AC_STRUCTURED_MACRO: Final = f"{{{AC_NS}}}structured-macro"

# Macros dropped outright — rendered as UI in Confluence, no textual content
# to carry through the pipeline.
_DROP_MACROS: Final = frozenset({"toc"})

_SIMPLE_TAG_KINDS: Final = {
    "p": SectionKind.PARAGRAPH,
    "table": SectionKind.TABLE,
    "pre": SectionKind.CODE,
    "blockquote": SectionKind.QUOTE,
    "hr": SectionKind.HR,
}

_ROOT_OPEN: Final = f'<root xmlns:ac="{AC_NS}" xmlns:ri="{RI_NS}">'
_ROOT_CLOSE: Final = "</root>"

# The XML parser only knows the five XHTML-safe named entities; everything
# else (&nbsp; &mdash; &copy; …) has to be rewritten to numeric form before
# lxml sees it, or the fragment is dropped by recover mode.
_XML_SAFE_ENTITIES: Final = frozenset({"amp", "lt", "gt", "quot", "apos"})
_NAMED_ENTITY_RE: Final = re.compile(r"&([a-zA-Z][a-zA-Z0-9]+);")


class ConfluenceParser:
    """Storage-format parser. Stateless besides its macro registry."""

    def __init__(
        self,
        macros: dict[str, MacroHandler] | None = None,
    ) -> None:
        self._macros = macros if macros is not None else default_registry()
        self._unknown_handler = UnknownMacro()

    def parse(self, xhtml: str) -> list[StructuralElement]:
        wrapped = _ROOT_OPEN + _substitute_entities(xhtml) + _ROOT_CLOSE
        # `resolve_entities=False` + `no_network=True` block XXE — a
        # hostile Confluence tenant can otherwise inject
        # `<!ENTITY xxe SYSTEM "file:///etc/passwd">` and exfiltrate.
        parser = etree.XMLParser(
            recover=True,
            remove_blank_text=False,
            resolve_entities=False,
            no_network=True,
        )
        root = etree.fromstring(wrapped.encode("utf-8"), parser=parser)  # noqa: S320
        if root is None:
            return []
        raw: list[StructuralElement] = []
        for node in root:
            # lxml exposes comments and processing instructions as nodes
            # whose `.tag` is a callable; skip them outright.
            if not isinstance(node.tag, str):
                continue
            handled = self._handle_node(node, len(raw))
            if handled is not None:
                raw.append(handled)
        return _merge_pending_anchors(raw)

    def _handle_node(
        self,
        node: etree._Element,
        seq: int,
    ) -> StructuralElement | None:
        tag = _local_name(node.tag)
        raw = serialize(node)
        text = _text_of(node)

        if tag in _HEADING_TAGS:
            return StructuralElement(
                seq=seq,
                kind=SectionKind.HEADING,
                text=text,
                raw=raw,
                anchor=node.get("id") or None,
                heading_level=int(tag[1]),
            )

        if node.tag == _AC_STRUCTURED_MACRO:
            name = get_macro_name(node)
            if name in _DROP_MACROS:
                return None
            handler = self._macros.get(name, self._unknown_handler)
            return handler.handle(node, seq)

        if tag in _LIST_TAGS:
            return StructuralElement(
                seq=seq,
                kind=SectionKind.LIST,
                text=text,
                raw=raw,
                metadata={"list_kind": tag},
            )

        simple = _SIMPLE_TAG_KINDS.get(tag)
        if simple is not None:
            return StructuralElement(
                seq=seq,
                kind=simple,
                text="" if simple == SectionKind.HR else text,
                raw=raw,
            )

        logger.warning("unknown top-level element in storage format: tag=%s", tag)
        return StructuralElement(
            seq=seq,
            kind=SectionKind.UNKNOWN,
            text=text,
            raw=raw,
            metadata={"tag": tag},
        )


def _local_name(tag: str) -> str:
    """Strip Clark-notation namespace, if any."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _text_of(node: etree._Element) -> str:
    parts: list[str] = []
    for t in node.itertext():
        chunk = str(t).strip()
        if chunk:
            parts.append(chunk)
    return " ".join(parts)


def _substitute_entities(xhtml: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _XML_SAFE_ENTITIES:
            return match.group(0)
        char = html.entities.html5.get(name + ";")
        if char is None:
            return match.group(0)
        return "".join(f"&#{ord(c)};" for c in char)

    return _NAMED_ENTITY_RE.sub(replace, xhtml)


def _merge_pending_anchors(
    elements: list[StructuralElement],
) -> list[StructuralElement]:
    """Attach `<ac:structured-macro name="anchor">` names to the next element.

    An anchor macro marks the *following* element as an anchor target. We
    attach to the next non-ANCHOR element that doesn't already carry an
    anchor; anchor macros without a name are dropped. A trailing anchor
    (no next element) is kept as a standalone ANCHOR so resolvers can
    still find it.
    """
    result: list[StructuralElement] = []
    pending: str | None = None
    for elt in elements:
        if elt.kind == ElementKind.ANCHOR:
            if elt.anchor:
                pending = elt.anchor
            continue
        merged = dataclasses.replace(elt, anchor=pending) if pending and elt.anchor is None else elt
        pending = None
        result.append(merged)
    if pending is not None:
        result.append(
            StructuralElement(
                seq=len(result),
                kind=ElementKind.ANCHOR,
                text="",
                raw="",
                anchor=pending,
            ),
        )
    # Renumber seq so the invariant holds (contiguous 0..N-1).
    return [dataclasses.replace(elt, seq=i) for i, elt in enumerate(result)]
