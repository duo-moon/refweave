"""ADF (Atlassian Document Format) → StructuralElement list.

ADF is Jira Cloud's rich-text body format: a nested JSON tree with a
`type` tag on every node. Top-level `content` items become
`StructuralElement`s; inline text is projected recursively via
`_collect_text`.

Inline links / mentions / inlineCards are preserved in the raw JSON so
`LinkExtractor` can find them later — this parser only builds the
structural spine.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.base.elements import StructuralElement

logger = logging.getLogger(__name__)

_MAX_HEADING_LEVEL: Final = 6

# Module-level dedup for unfamiliar ADF block types — WARN once per
# unseen type, DEBUG on subsequent hits. Prevents log flood on corpora
# using ADF extensions (media, decisionItem, taskItem, ...). Small set
# in practice (dozens of distinct types across all Jira corpora).
_SEEN_UNKNOWN_TYPES: set[str] = set()

# Top-level ADF block type → ElementKind mapping.
_BLOCK_KIND: dict[str, str] = {
    "paragraph": SectionKind.PARAGRAPH,
    "heading": SectionKind.HEADING,
    "bulletList": SectionKind.LIST,
    "orderedList": SectionKind.LIST,
    "codeBlock": SectionKind.CODE,
    "blockquote": SectionKind.QUOTE,
    "table": SectionKind.TABLE,
    "panel": ElementKind.PANEL,
    "rule": SectionKind.HR,
}


def parse_adf(body: str) -> tuple[StructuralElement, ...]:
    """Parse an ADF JSON string into an ordered tuple of StructuralElements."""
    if not body:
        return ()
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("malformed ADF body; falling back to single paragraph")
        return (
            StructuralElement(
                seq=0,
                kind=SectionKind.PARAGRAPH,
                text=body,
                raw=body,
            ),
        )
    if not isinstance(doc, dict):
        return ()
    content = doc.get("content") or ()
    elements: list[StructuralElement] = []
    for node in content:
        if not isinstance(node, dict):
            continue
        element = _map_block(node, len(elements))
        if element is not None:
            elements.append(element)
    return tuple(elements)


def _map_block(node: dict[str, Any], seq: int) -> StructuralElement | None:
    node_type = str(node.get("type", ""))
    raw = json.dumps(node, ensure_ascii=False)
    text = _plain_text(node)
    kind = _BLOCK_KIND.get(node_type)

    if kind is None:
        if node_type and node_type not in _SEEN_UNKNOWN_TYPES:
            _SEEN_UNKNOWN_TYPES.add(node_type)
            logger.warning(
                "unknown ADF block type: %s (subsequent hits at DEBUG)",
                node_type,
            )
        else:
            logger.debug("unknown ADF block type: %s", node_type)
        return StructuralElement(
            seq=seq,
            kind=SectionKind.UNKNOWN,
            text=text,
            raw=raw,
            metadata={"adf_type": node_type} if node_type else {},
        )

    attrs = node.get("attrs") or {}
    metadata: dict[str, Any] = {}
    heading_level: int | None = None

    if kind == SectionKind.HEADING:
        level = attrs.get("level")
        if isinstance(level, int) and 1 <= level <= _MAX_HEADING_LEVEL:
            heading_level = level
    elif kind == SectionKind.LIST:
        metadata["list_kind"] = node_type  # bulletList | orderedList
    elif kind == SectionKind.CODE:
        language = attrs.get("language")
        if language:
            metadata["language"] = str(language)
    elif kind == ElementKind.PANEL:
        panel_type = attrs.get("panelType")
        if panel_type:
            metadata["panel_type"] = str(panel_type)
    elif kind == SectionKind.HR:
        text = ""

    return StructuralElement(
        seq=seq,
        kind=kind,
        text=text,
        raw=raw,
        heading_level=heading_level,
        metadata=metadata,
    )


def _plain_text(node: dict[str, Any]) -> str:
    """Walk the node recursively and produce a plain-text projection."""
    parts: list[str] = []
    _collect_text(node, parts)
    return " ".join(" ".join(parts).split())


def _collect_text(node: Any, parts: list[str]) -> None:
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "text":
        text = node.get("text")
        if text:
            parts.append(str(text))
        return
    if node_type == "mention":
        text = (node.get("attrs") or {}).get("text")
        if text:
            parts.append(str(text))
        return
    if node_type == "emoji":
        short = (node.get("attrs") or {}).get("shortName")
        if short:
            parts.append(str(short))
        return
    if node_type == "inlineCard":
        url = (node.get("attrs") or {}).get("url")
        if url:
            parts.append(str(url))
        return
    if node_type == "hardBreak":
        parts.append(" ")
        return
    for child in node.get("content") or ():
        _collect_text(child, parts)
