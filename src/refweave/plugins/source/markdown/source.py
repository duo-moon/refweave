"""Markdown source — consumes a `RawFileProvider`, yields SyncedDocuments.

The Markdown-specific work (frontmatter, tokenizing, element extraction,
link extraction, doc assembly) lives here. File discovery and reading
are delegated to the injected provider — `LocalDirectoryProvider` for
filesystem trees, `GitCloneProvider` for remote git repos, or a
consumer-supplied implementation of `RawFileProvider`.

Convenience: constructing `MarkdownSource(root=...)` creates a
`LocalDirectoryProvider` internally, preserving the pre-0.1 API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from refweave.pipeline import SyncedDocument
from refweave.plugins.source.base import document_id
from refweave.plugins.source.markdown._shared import tokenize
from refweave.plugins.source.markdown.build import build_document
from refweave.plugins.source.markdown.frontmatter import parse_frontmatter
from refweave.plugins.source.markdown.links import LinkExtractor
from refweave.plugins.source.markdown.parser import parse_markdown
from refweave.plugins.source.markdown.providers import (
    LocalDirectoryProvider,
    RawFileProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from refweave.model import Link
    from refweave.plugins.source.markdown.types import RawFile

logger = logging.getLogger(__name__)

__all__ = ["MarkdownSource"]


class MarkdownSource:
    """Turns a stream of `RawFile`s (from a `RawFileProvider`) into
    `SyncedDocument`s.

    Two ways to construct:

        # Local filesystem (default, uses LocalDirectoryProvider).
        MarkdownSource(source_id="docs", root="./docs")

        # Explicit provider — remote git, or custom implementation.
        MarkdownSource(
            source_id="docs",
            provider=GitCloneProvider(url="https://github.com/foo/docs.git"),
        )

    `patterns` / `exclude_patterns` are wired into the default
    `LocalDirectoryProvider` when `root` is used. When passing an
    explicit `provider`, those parameters go on the provider itself.
    """

    def __init__(
        self,
        *,
        source_id: str,
        provider: RawFileProvider | None = None,
        root: Path | str | None = None,
        patterns: Sequence[str] = ("**/*.md",),
        exclude_patterns: Sequence[str] = (),
        link_extractor: LinkExtractor | None = None,
    ) -> None:
        if provider is None:
            if root is None:
                msg = "MarkdownSource requires either `provider` or `root`"
                raise ValueError(msg)
            provider = LocalDirectoryProvider(
                root, patterns=patterns, exclude_patterns=exclude_patterns,
            )
        elif root is not None:
            msg = "pass either `provider` or `root`, not both"
            raise ValueError(msg)
        self.source_id = source_id
        self._provider = provider
        self._link_extractor = link_extractor or LinkExtractor()

    async def aclose(self) -> None:
        await self._provider.aclose()

    async def __aenter__(self) -> MarkdownSource:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        # `_synced` runs the CPU-heavy pipeline (frontmatter parse,
        # markdown-it tokenize, StructuralElement build, Document
        # assembly) which can take tens of ms on large files. Offload
        # to a worker thread so the event loop stays responsive to
        # other tasks (parallel Sources, network fan-out, UI updates)
        # between yields.
        async for raw in self._provider.iter():
            yield await asyncio.to_thread(self._synced, raw)

    def _synced(self, raw: RawFile) -> SyncedDocument:
        metadata, body_without_fm, fmt = parse_frontmatter(raw.body)
        tokens = tokenize(body_without_fm)
        elements = parse_markdown(tokens, body_without_fm)
        document = build_document(
            raw,
            elements,
            source_id=self.source_id,
            frontmatter=metadata,
            frontmatter_format=fmt,
        )
        links: list[Link] = list(
            self._link_extractor.extract(
                tokens,
                source_id=self.source_id,
                external=raw.path,
            ),
        )
        if links and not document.sections:
            logger.warning(
                "markdown source %s emitted %d links but document has no sections; "
                "doc_id=%s",
                self.source_id,
                len(links),
                document_id(self.source_id, raw.path),
            )
        return SyncedDocument(document=document, links=tuple(links))
