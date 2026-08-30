"""Extract Link edges from a Markdown file's body.

Walks the same markdown-it token stream that `parser.parse_markdown` uses
and maintains a parallel `section_seq` counter, so each emitted Link
lands on the correct owning Section. Distinguishes:

    - external:  URLs with a scheme (http/https/mailto/ftp/...)
    - internal:  relative or absolute paths pointing at another MD file
                 in the same corpus; resolver fills `target_document`.

Anchor-only links (`#section`) are treated as internal to the current
document — target_path stays empty, target_anchor carries the anchor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from refweave.model import Link
from refweave.plugins.source.base import document_id, link_id, section_id
from refweave.plugins.source.markdown.keys import (
    HREF_KEY,
    TARGET_PATH_KEY,
    TITLE_KEY,
)
from refweave.plugins.source.markdown.link_types import MarkdownLinkKind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from markdown_it.token import Token

logger = logging.getLogger(__name__)

# Top-level token types that produce an element (must match parser.py).
_BLOCK_STARTERS: Final = frozenset(
    {
        "heading_open",
        "paragraph_open",
        "bullet_list_open",
        "ordered_list_open",
        "blockquote_open",
        "table_open",
        "fence",
        "code_block",
        "hr",
        "html_block",
    },
)

# URL schemes considered external (link kind = external).
_EXTERNAL_SCHEMES: Final = frozenset(
    {"http", "https", "ftp", "ftps", "mailto", "tel", "ssh", "git"},
)


class LinkExtractor:
    """Stateless — walks a markdown-it token stream, yields Link edges.

    The caller (typically `MarkdownSource`) tokenizes the body once via
    `_shared.tokenize` and hands the same tokens to both `parse_markdown`
    and this extractor, so each file is parsed exactly once.
    """

    def extract(
        self,
        tokens: list[Token],
        *,
        source_id: str,
        external: str,
    ) -> Iterator[Link]:
        if not tokens:
            return
        doc_id = document_id(source_id, external)
        section_seq = -1
        link_seq = 0
        for token in tokens:
            if token.level == 0 and token.type in _BLOCK_STARTERS:
                section_seq += 1
                link_seq = 0
                continue
            if token.type != "inline" or section_seq < 0:
                continue
            for href, text in _iter_inline_links(token):
                yield _build_link(
                    href=href,
                    text=text,
                    source_id=source_id,
                    external=external,
                    doc_id=doc_id,
                    section_seq=section_seq,
                    link_seq=link_seq,
                )
                link_seq += 1


def _iter_inline_links(inline: Token) -> Iterator[tuple[str, str]]:
    """Yield (href, visible_text) for every `[text](href)` in an inline run."""
    children = inline.children or []
    i = 0
    while i < len(children):
        child = children[i]
        if child.type != "link_open":
            i += 1
            continue
        href = str(child.attrGet("href") or "")
        j = i + 1
        text_parts: list[str] = []
        while j < len(children) and children[j].type != "link_close":
            if children[j].type in ("text", "code_inline"):
                text_parts.append(children[j].content)
            elif children[j].type == "image":
                alt = children[j].content or ""
                if alt:
                    text_parts.append(alt)
            j += 1
        yield href, "".join(text_parts).strip()
        i = j + 1


def _build_link(
    *,
    href: str,
    text: str,
    source_id: str,
    external: str,
    doc_id: str,
    section_seq: int,
    link_seq: int,
) -> Link:
    parsed = urlparse(href)
    scheme = parsed.scheme.lower()
    # Any URL with a scheme goes to `external` — the well-known set
    # (`_EXTERNAL_SCHEMES`) covers the common cases so we can log a
    # debug line on unfamiliar ones (data:, chrome://, custom app
    # protocols). An unrecognized scheme is still external — never a
    # corpus-relative path — so we don't try to resolve `data:...` as
    # if it were a Markdown file.
    if scheme:
        if scheme not in _EXTERNAL_SCHEMES:
            logger.debug("markdown link uses unfamiliar scheme %r: %s", scheme, href)
        return _external(
            href=href,
            text=text,
            source_id=source_id,
            external=external,
            doc_id=doc_id,
            section_seq=section_seq,
            link_seq=link_seq,
        )
    # Internal: relative or absolute path within corpus, plus optional #anchor.
    target_path = parsed.path
    target_anchor = parsed.fragment or None
    return _internal(
        href=href,
        text=text,
        target_path=target_path,
        target_anchor=target_anchor,
        source_id=source_id,
        external=external,
        doc_id=doc_id,
        section_seq=section_seq,
        link_seq=link_seq,
    )


def _external(
    *,
    href: str,
    text: str,
    source_id: str,
    external: str,
    doc_id: str,
    section_seq: int,
    link_seq: int,
) -> Link:
    metadata: dict[str, Any] = {HREF_KEY: href}
    if text:
        metadata[TITLE_KEY] = text
    return Link(
        id=link_id(source_id, external, section_seq, link_seq),
        document=doc_id,
        section=section_id(source_id, external, section_seq),
        seq=link_seq,
        kind=MarkdownLinkKind.EXTERNAL,
        target_anchor=None,
        resolved=True,
        metadata=metadata,
    )


def _internal(
    *,
    href: str,
    text: str,
    target_path: str,
    target_anchor: str | None,
    source_id: str,
    external: str,
    doc_id: str,
    section_seq: int,
    link_seq: int,
) -> Link:
    metadata: dict[str, Any] = {
        HREF_KEY: href,
        TARGET_PATH_KEY: target_path,
    }
    if text:
        metadata[TITLE_KEY] = text
    return Link(
        id=link_id(source_id, external, section_seq, link_seq),
        document=doc_id,
        section=section_id(source_id, external, section_seq),
        seq=link_seq,
        kind=MarkdownLinkKind.INTERNAL,
        target_anchor=target_anchor,
        resolved=False,
        metadata=metadata,
    )
