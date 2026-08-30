"""Markdown → StructuralElement list, via markdown-it-py (CommonMark + GFM).

Walks the flat token stream and picks off top-level (`level==0`) blocks
one at a time. Nested content (inline runs, list items, table cells) is
folded into the parent block's `text` projection. The `raw` field carries
the original Markdown fragment, sliced from the source via `token.map`.

Heading anchors are auto-slugified from the heading text (GitHub-style).
For explicit anchors — `## Heading {#custom}` — see the trailing `_ATX_ID_RE`
which strips them off the visible text.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Final

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.base import StructuralElement
from refweave.plugins.source.markdown.elements import ElementKind

if TYPE_CHECKING:
    from markdown_it.token import Token

logger = logging.getLogger(__name__)

_SLUG_STRIP: Final = re.compile(r"[^\w\s-]")
_SLUG_HYPHEN: Final = re.compile(r"[\s_]+")
# `## Heading text {#custom-id}` — trailing `{#id}` is an anchor override.
# mkdocs-material and Kramdown accept `{ #id }` with optional whitespace
# inside the braces; our regex tolerates both forms.
_ATX_ID_RE: Final = re.compile(r"\s*\{\s*#([\w-]+)\s*\}\s*$")


def slugify(text: str) -> str:
    """GitHub-like slug: lowercase, strip punctuation, hyphens for whitespace."""
    text = _SLUG_STRIP.sub("", text.lower())
    text = _SLUG_HYPHEN.sub("-", text.strip())
    return text.strip("-")


def parse_markdown(
    tokens: list[Token],
    body: str,
) -> tuple[StructuralElement, ...]:
    """Convert a markdown-it token stream into ordered StructuralElements.

    `body` is retained so `raw` slices land on the original source lines
    via each token's `token.map`. The caller (typically `MarkdownSource`)
    tokenizes once via `_shared.tokenize(body)` and passes the tokens to
    both this function and `LinkExtractor.extract`.
    """
    if not tokens:
        return ()
    lines = body.splitlines()
    elements: list[StructuralElement] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.level != 0:
            i += 1
            continue
        element, next_i = _consume(tokens, i, len(elements), lines)
        if element is not None:
            elements.append(element)
        i = next_i
    return tuple(elements)


def _consume(
    tokens: list[Token],
    i: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement | None, int]:
    token = tokens[i]
    builder = _BLOCK_BUILDERS.get(token.type)
    if builder is not None:
        return builder(tokens, i, seq, lines)
    single = _SINGLE_BUILDERS.get(token.type)
    if single is not None:
        return single(token, seq, lines), i + 1
    logger.debug("unhandled top-level markdown token type: %s", token.type)
    return None, i + 1


def _match_close(tokens: list[Token], start: int, close_type: str) -> int:
    for j in range(start + 1, len(tokens)):
        if tokens[j].type == close_type and tokens[j].level == tokens[start].level:
            return j
    return len(tokens) - 1


def _build_heading(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    end = _match_close(tokens, start, "heading_close")
    open_token = tokens[start]
    inline = tokens[start + 1] if start + 1 < len(tokens) else None
    text = _plain_text_inline(inline) if inline and inline.type == "inline" else ""
    anchor: str | None = None
    id_match = _ATX_ID_RE.search(text)
    if id_match:
        anchor = id_match.group(1)
        text = _ATX_ID_RE.sub("", text).rstrip()
    elif text:
        anchor = slugify(text)
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.HEADING,
            text=text,
            raw=_slice_raw(open_token.map, lines),
            heading_level=int(open_token.tag[1:]),
            anchor=anchor,
        ),
        end + 1,
    )


def _build_paragraph(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    end = _match_close(tokens, start, "paragraph_close")
    text = _collect_inline_text(tokens, start + 1, end)
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.PARAGRAPH,
            text=text,
            raw=_slice_raw(tokens[start].map, lines),
        ),
        end + 1,
    )


def _build_bullet_list(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    return _build_list_generic(tokens, start, seq, lines, "bullet_list_close", "bullet")


def _build_ordered_list(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    return _build_list_generic(tokens, start, seq, lines, "ordered_list_close", "ordered")


def _build_list_generic(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
    close_type: str,
    list_kind: str,
) -> tuple[StructuralElement, int]:
    end = _match_close(tokens, start, close_type)
    text = _collect_inline_text(tokens, start + 1, end, sep="\n")
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.LIST,
            text=text,
            raw=_slice_raw(tokens[start].map, lines),
            metadata={"list_kind": list_kind},
        ),
        end + 1,
    )


def _build_quote(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    end = _match_close(tokens, start, "blockquote_close")
    text = _collect_inline_text(tokens, start + 1, end, sep=" ")
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.QUOTE,
            text=text,
            raw=_slice_raw(tokens[start].map, lines),
        ),
        end + 1,
    )


def _build_table(
    tokens: list[Token],
    start: int,
    seq: int,
    lines: list[str],
) -> tuple[StructuralElement, int]:
    end = _match_close(tokens, start, "table_close")
    text = _collect_inline_text(tokens, start + 1, end, sep=" ")
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.TABLE,
            text=text,
            raw=_slice_raw(tokens[start].map, lines),
        ),
        end + 1,
    )


def _build_fence(token: Token, seq: int, lines: list[str]) -> StructuralElement:
    metadata: dict[str, Any] = {}
    if token.info:
        # ```python arg=val → language = "python", extras discarded
        first = token.info.split(maxsplit=1)[0]
        if first:
            metadata["language"] = first
    return StructuralElement(
        seq=seq,
        kind=SectionKind.CODE,
        text=token.content.rstrip(),
        raw=_slice_raw(token.map, lines),
        metadata=metadata,
    )


def _build_code_block(token: Token, seq: int, lines: list[str]) -> StructuralElement:
    return StructuralElement(
        seq=seq,
        kind=SectionKind.CODE,
        text=token.content.rstrip(),
        raw=_slice_raw(token.map, lines),
    )


def _build_hr(token: Token, seq: int, lines: list[str]) -> StructuralElement:
    return StructuralElement(
        seq=seq,
        kind=SectionKind.HR,
        text="",
        raw=_slice_raw(token.map, lines),
    )


def _build_html_block(token: Token, seq: int, lines: list[str]) -> StructuralElement:
    return StructuralElement(
        seq=seq,
        kind=ElementKind.HTML,
        text=token.content.strip(),
        raw=_slice_raw(token.map, lines),
    )


def _slice_raw(token_map: list[int] | None, lines: list[str]) -> str:
    if token_map is None:
        return ""
    start, end = token_map
    return "\n".join(lines[start:end])


def _plain_text_inline(inline: Token) -> str:
    parts: list[str] = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type == "image":
            alt = child.content or ""
            if alt:
                parts.append(alt)
    # Consecutive whitespace (from stacked softbreaks or literal double
    # spaces around inline markup) collapses to a single space so the
    # plain-text projection reads naturally.
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _collect_inline_text(
    tokens: list[Token],
    start: int,
    end: int,
    sep: str = " ",
) -> str:
    parts: list[str] = []
    for j in range(start, end):
        if tokens[j].type == "inline":
            text = _plain_text_inline(tokens[j])
            if text:
                parts.append(text)
    return sep.join(parts)


_BLOCK_BUILDERS: Final = {
    "heading_open": _build_heading,
    "paragraph_open": _build_paragraph,
    "bullet_list_open": _build_bullet_list,
    "ordered_list_open": _build_ordered_list,
    "blockquote_open": _build_quote,
    "table_open": _build_table,
}

_SINGLE_BUILDERS: Final = {
    "fence": _build_fence,
    "code_block": _build_code_block,
    "hr": _build_hr,
    "html_block": _build_html_block,
}
