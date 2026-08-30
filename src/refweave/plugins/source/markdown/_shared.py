"""Shared markdown-it configuration for the Markdown plugin.

Both `parser.parse_markdown` and `LinkExtractor.extract` consume the
same token stream. Keeping the `MarkdownIt` instance in one place lets
`MarkdownSource` parse each file once and hand the tokens to both
consumers, halving parse cost per document.

The `MarkdownIt` instance is a module-level singleton. `MarkdownSource`
runs `_synced` in a worker thread via `asyncio.to_thread`, so multiple
threads may hit `_MD.parse` concurrently — that is safe because
markdown-it-py's `parse` is stateless (it produces a fresh token list
per call and does not mutate the parser).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from markdown_it.token import Token

_MD = MarkdownIt("commonmark").enable("table").enable("strikethrough")


def tokenize(body: str) -> list[Token]:
    """Parse `body` into a flat markdown-it token stream."""
    return _MD.parse(body)
