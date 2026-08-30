"""Chunker — a plugin that turns a Document into Chunks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from refweave.model import Chunk, Document, Link


@runtime_checkable
class Chunker(Protocol):
    """Turns a Document into a stream of Chunks."""

    def chunk(
        self,
        document: Document,
        links: Sequence[Link],
    ) -> Iterator[Chunk]:
        """Yield the document's chunks in order of `seq` (0..N-1).

        `links` is the full set of the document's outgoing links.
        Implementations decide how to derive `Chunk.outgoing_links` from
        `links`. Yields nothing if the document has no sections.
        """
        ...
