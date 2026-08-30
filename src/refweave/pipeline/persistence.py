"""Persistence layer: storage protocols and the Persistence bundle.

Groups every contract a pipeline consumer needs to store, index, and read
back documents/links/chunks:

    Content-blob stores    — DocumentStore, LinkStore, ChunkStore
    Index tables           — DataIndex, GraphIndex + DocumentState
    Read-side projections  — GraphQuery
    Bundle                 — Persistence (aggregates all of the above and
                             exposes paired-write shortcuts)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

    from refweave.model import Chunk, ChunkWithGraph, Document, Link


@runtime_checkable
class DocumentStore(Protocol):
    """Persistent store for Document blobs, keyed by document id."""

    async def put(self, document: Document) -> None: ...
    async def get(self, source_id: str, document_id: str) -> Document | None: ...
    def iter(self, source_id: str) -> AsyncIterator[Document]: ...


@runtime_checkable
class LinkStore(Protocol):
    """Persistent store for a document's outgoing links."""

    async def put(self, document: Document, links: Sequence[Link]) -> None: ...
    def get(self, source_id: str, document_id: str) -> AsyncIterator[Link]: ...


@runtime_checkable
class ChunkStore(Protocol):
    """Persistent store for a document's chunks."""

    async def put(self, document: Document, chunks: Sequence[Chunk]) -> None: ...
    def get(self, source_id: str, document_id: str) -> AsyncIterator[Chunk]: ...


@dataclass(frozen=True, slots=True)
class DocumentState:
    """Minimal snapshot per document for sync/tombstone decisions."""

    id: str
    version: int
    deleted_at: datetime | None


@runtime_checkable
class DataIndex(Protocol):
    """Per-document index rows and per-source counters.

    Holds a minimal `DocumentState` snapshot per document that supports
    skip-detection on re-sync without loading full Document blobs, a
    monotonic `graph_version` counter per source, and secondary rows
    (e.g. chunk anchors) populated on chunk replacement.
    """

    async def bump_graph_version(self, source_id: str) -> int:
        """Atomically increment and return the source's `graph_version`."""
        ...

    async def put(self, document: Document) -> None:
        """Upsert the document's index row from its `id`, `sync`, and
        `graph_version` fields.
        """
        ...

    def iter(self, source_id: str) -> AsyncIterator[DocumentState]:
        """Yield the minimal state for every document under `source_id`."""
        ...

    async def replace_chunks(
        self,
        document: Document,
        chunks: Sequence[Chunk],
    ) -> None:
        """Replace all secondary index rows tied to the document's chunks
        (chunk id → document mapping, anchors, ...) with the given set.
        """
        ...


@runtime_checkable
class GraphIndex(Protocol):
    """Chunk-to-chunk graph state.

    Owns per-document outbound chunk-target edges, per-document cluster
    assignments, and materialized chunk-to-chunk relations derived from
    those edges.
    """

    async def replace_chunk_targets(
        self,
        document: Document,
        rows: Sequence[tuple[str, str, str | None]],
    ) -> None:
        """Replace this document's chunk-target edges.

        `rows` is a sequence of `(chunk_id, target_document, target_anchor)`
        triples; edge-set semantics — duplicates are deduplicated upstream.
        """
        ...

    async def rebuild_clusters(self, source_id: str) -> int:
        """Recompute cluster assignments for `source_id`; return the number
        of distinct clusters. Prior assignments are replaced (no history).
        """
        ...

    async def materialize_relations(self, source_id: str) -> int:
        """Rebuild materialized chunk-to-chunk relations for `source_id`;
        return the number of relation rows written. Channel vocabulary and
        inclusion rules are implementation-defined; see the store's
        constructor for behavioral config.
        """
        ...


@runtime_checkable
class GraphQuery(Protocol):
    """Backend-agnostic read of enriched chunks.

    Implementations assemble `ChunkWithGraph` from two sources: chunk
    content (blob or index) and post-hoc graph state (cluster membership,
    backlinks, ...) populated by whichever code owns the graph indices.
    """

    async def get_chunk(
        self,
        source_id: str,
        chunk_id: str,
    ) -> ChunkWithGraph | None:
        """Return one enriched chunk, or None if `chunk_id` is unknown."""
        ...

    def get_chunks(
        self,
        source_id: str,
        document_id: str,
    ) -> AsyncIterator[ChunkWithGraph]:
        """Yield all chunks of one document with enriched graph state,
        ordered by chunk `seq`. Yields nothing if `document_id` is unknown.
        """
        ...

    def cluster_peers(
        self,
        source_id: str,
        chunk_id: str,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        """Yield chunks in the same cluster as `chunk_id` (excluding itself).

        The definition of "same cluster" is set by the implementation; peer
        granularity (per-document vs per-chunk) is an implementation detail.
        Order is not guaranteed. If `limit` is set, the result is capped at
        that count; otherwise all peers are yielded. Yields nothing if
        `chunk_id` is unknown or has no cluster assigned.
        """
        ...

    def by_cluster(
        self,
        source_id: str,
        cluster_id: int,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        """Yield all chunks belonging to `cluster_id`.

        Order is not guaranteed. If `limit` is set, the result is capped;
        otherwise all chunks are yielded. Yields nothing if the cluster
        contains no chunks (unknown cluster id or empty cluster).
        """
        ...


@dataclass(frozen=True, slots=True)
class Persistence:
    """Bundle of storage backends used by the orchestrator.

    Content-blob stores (documents/links/chunks) and index tables (data/graph)
    always update together on write. `save_*` helpers hide the pair so callers
    can't forget one half.
    """

    documents: DocumentStore
    links: LinkStore
    chunks: ChunkStore
    data: DataIndex
    graph: GraphIndex
    query: GraphQuery

    async def save_document(self, document: Document) -> None:
        """Persist a Document to the blob store and its index row."""
        await self.documents.put(document)
        await self.data.put(document)

    async def save_links(self, document: Document, links: Sequence[Link]) -> None:
        """Persist a document's links to the blob store."""
        await self.links.put(document, links)

    async def save_chunks(self, document: Document, chunks: Sequence[Chunk]) -> None:
        """Persist a document's chunks: blobs, index rows, and graph targets."""
        await self.chunks.put(document, chunks)
        await self.data.replace_chunks(document, chunks)
        await self.graph.replace_chunk_targets(document, _build_target_rows(chunks))


def _build_target_rows(
    chunks: Sequence[Chunk],
) -> list[tuple[str, str, str | None]]:
    seen: set[tuple[str, str, str | None]] = set()
    rows: list[tuple[str, str, str | None]] = []
    for chunk in chunks:
        for ref in chunk.outgoing_links:
            if ref.target_document is None:
                continue
            row = (chunk.id, ref.target_document, ref.target_anchor)
            if row in seen:
                continue
            seen.add(row)
            rows.append(row)
    return rows
