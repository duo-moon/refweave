"""In-memory implementation of every storage / index / query surface.

Backed by plain dicts — no persistence between process runs, no disk,
no schema. Semantic parity with `SqliteStore + FsStore`: same protocols,
same materialize/cluster invariants, same edge-set semantics for
`chunk_target`.

Intended uses:
- fast unit tests that don't want SQLite / filesystem setup
- notebooks, ad-hoc experiments, tiny corpora
- reference implementation for authors writing new storage backends
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from refweave.graph import run_leiden
from refweave.ids import source_of
from refweave.model import Chunk, ChunkWithGraph, Document, Link
from refweave.pipeline.persistence import ChunkStore, DocumentState
from refweave.plugins.keys import chunk_anchors
from refweave.plugins.store._defaults import SAME_TARGET_EXCLUDED_KINDS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

__all__ = ["MemoryStore"]

_SAME_TARGET: Final = "same_target"
_ANCHOR_FOLLOW: Final = "anchor_follow"
_JACCARD_MIN: Final = 1e-6
_MIN_TARGETS_FOR_SAME_TARGET: Final = 2


@dataclass
class _State:
    """Shared mutable state across all MemoryStore sub-stores.

    Keeping every backend keyed dict on one dataclass makes concurrent
    reads/writes consistent (as long as callers don't multithread) and
    keeps the code readable — every field's shape is explicit.
    """

    documents: dict[tuple[str, str], Document] = field(default_factory=dict)
    links: dict[tuple[str, str], tuple[Link, ...]] = field(default_factory=dict)
    chunks: dict[tuple[str, str], tuple[Chunk, ...]] = field(default_factory=dict)

    document_states: dict[tuple[str, str], DocumentState] = field(default_factory=dict)
    graph_versions: dict[str, int] = field(default_factory=dict)

    # chunk_id → doc_id (source_id part recoverable via `source_of`)
    chunk_document: dict[str, str] = field(default_factory=dict)
    # chunk_id → kind (used to exclude NAVIGATION chunks from same_target)
    chunk_kind: dict[str, str] = field(default_factory=dict)
    # chunk_id → tuple of anchor strings
    chunk_anchors: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # (source_id, doc_id) → list of (chunk_id, target_doc, target_anchor)
    chunk_targets: dict[tuple[str, str], list[tuple[str, str, str | None]]] = field(
        default_factory=dict,
    )
    # source_id → list of (from_chunk, to_chunk, channel, weight)
    chunk_relations: dict[str, list[tuple[str, str, str, float]]] = field(
        default_factory=dict,
    )
    # (source_id, doc_id) → cluster_id
    clusters: dict[tuple[str, str], int] = field(default_factory=dict)


class MemoryStore:
    """All-in-memory MemoryStore facade.

    Exposes the same attributes as `FsStore + SqliteStore` combined
    (`documents`, `links`, `chunks`, `data`, `graph`), plus a `query()`
    builder identical in signature to `SqliteStore.query()`. Callers can
    swap MemoryStore in place of the on-disk pair without touching the
    Persistence bundle wiring.
    """

    def __init__(
        self,
        *,
        exclude_from_same_target: Iterable[str] = SAME_TARGET_EXCLUDED_KINDS,
    ) -> None:
        """`exclude_from_same_target` — chunk kinds that must not source
        `same_target` edges. Only the same_target channel is filtered;
        `anchor_follow` ignores this parameter. Default matches
        `NavigationClassifier`'s default output kind — see
        `plugins.store._defaults` for the shared constant.
        """
        state = _State()
        self._state = state
        self.documents = _MemoryDocumentStore(state)
        self.links = _MemoryLinkStore(state)
        self.chunks = _MemoryChunkStore(state)
        self.data = _MemoryDataIndex(state)
        self.graph = _MemoryGraphIndex(
            state,
            exclude_from_same_target=exclude_from_same_target,
        )

    async def init(self) -> None:
        return None

    def query(self, chunks: ChunkStore | None = None) -> _MemoryGraphQuery:
        """Build a GraphQuery bound to a chunk store (defaults to ours)."""
        return _MemoryGraphQuery(self._state, chunks or self.chunks)

    async def close(self) -> None:
        return None


class _MemoryDocumentStore:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def put(self, document: Document) -> None:
        source_id = source_of(document.id)
        self._state.documents[(source_id, document.id)] = document

    async def get(self, source_id: str, document_id: str) -> Document | None:
        return self._state.documents.get((source_id, document_id))

    async def iter(self, source_id: str) -> AsyncIterator[Document]:
        for (src, _doc_id), doc in list(self._state.documents.items()):
            if src == source_id:
                yield doc


class _MemoryLinkStore:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def put(self, document: Document, links: Sequence[Link]) -> None:
        source_id = source_of(document.id)
        self._state.links[(source_id, document.id)] = tuple(links)

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[Link]:
        for link in self._state.links.get((source_id, document_id), ()):
            yield link


class _MemoryChunkStore:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def put(self, document: Document, chunks: Sequence[Chunk]) -> None:
        source_id = source_of(document.id)
        self._state.chunks[(source_id, document.id)] = tuple(chunks)

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[Chunk]:
        for chunk in self._state.chunks.get((source_id, document_id), ()):
            yield chunk


class _MemoryDataIndex:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def bump_graph_version(self, source_id: str) -> int:
        new = self._state.graph_versions.get(source_id, 0) + 1
        self._state.graph_versions[source_id] = new
        return new

    async def put(self, document: Document) -> None:
        source_id = source_of(document.id)
        self._state.document_states[(source_id, document.id)] = DocumentState(
            id=document.id,
            version=document.sync.version,
            deleted_at=document.sync.deleted_at,
        )

    async def iter(self, source_id: str) -> AsyncIterator[DocumentState]:
        for (src, _), state in list(self._state.document_states.items()):
            if src == source_id:
                yield state

    async def replace_chunks(
        self,
        document: Document,
        chunks: Sequence[Chunk],
    ) -> None:
        stale = [
            chunk_id
            for chunk_id, doc_id in self._state.chunk_document.items()
            if doc_id == document.id
        ]
        for chunk_id in stale:
            self._state.chunk_document.pop(chunk_id, None)
            self._state.chunk_kind.pop(chunk_id, None)
            self._state.chunk_anchors.pop(chunk_id, None)
        for chunk in chunks:
            self._state.chunk_document[chunk.id] = document.id
            self._state.chunk_kind[chunk.id] = chunk.kind
            anchors = chunk_anchors(chunk)
            if anchors:
                self._state.chunk_anchors[chunk.id] = anchors


class _MemoryGraphIndex:
    def __init__(
        self,
        state: _State,
        *,
        exclude_from_same_target: Iterable[str] = SAME_TARGET_EXCLUDED_KINDS,
    ) -> None:
        self._state = state
        self._excluded = frozenset(exclude_from_same_target)

    async def replace_chunk_targets(
        self,
        document: Document,
        rows: Sequence[tuple[str, str, str | None]],
    ) -> None:
        source_id = source_of(document.id)
        self._state.chunk_targets[(source_id, document.id)] = list(rows)

    async def rebuild_clusters(self, source_id: str) -> int:
        edges: list[tuple[str, str]] = []
        for (src, doc_id), rows in self._state.chunk_targets.items():
            if src != source_id:
                continue
            for _chunk_id, target_doc, _target_anchor in rows:
                edges.append((doc_id, target_doc))

        # Wipe prior cluster assignments for this source only.
        for key in list(self._state.clusters.keys()):
            if key[0] == source_id:
                del self._state.clusters[key]

        mapping = await run_leiden(edges)
        if not mapping:
            return 0
        for doc_id, cluster_id in mapping.items():
            self._state.clusters[(source_id, doc_id)] = cluster_id
        return len(set(mapping.values()))

    async def materialize_relations(self, source_id: str) -> int:
        rows: list[tuple[str, str, str, float]] = []
        rows.extend(self._compute_same_target(source_id))
        rows.extend(self._compute_anchor_follow(source_id))
        self._state.chunk_relations[source_id] = rows
        return len(rows)

    def _compute_same_target(
        self,
        source_id: str,
    ) -> list[tuple[str, str, str, float]]:
        # chunk_id → set of target_docs it points at
        by_chunk: dict[str, set[str]] = {}
        # target_doc → set of chunks pointing at it
        by_target: dict[str, set[str]] = {}
        for (src, _), rows_for_doc in self._state.chunk_targets.items():
            if src != source_id:
                continue
            for chunk_id, target_doc, _anchor in rows_for_doc:
                if self._state.chunk_kind.get(chunk_id) in self._excluded:
                    continue
                by_chunk.setdefault(chunk_id, set()).add(target_doc)
                by_target.setdefault(target_doc, set()).add(chunk_id)

        out: list[tuple[str, str, str, float]] = []
        for chunk_id, targets in by_chunk.items():
            if len(targets) < _MIN_TARGETS_FOR_SAME_TARGET:
                continue
            candidates: set[str] = set()
            for target in targets:
                candidates.update(by_target.get(target, set()))
            candidates.discard(chunk_id)
            for other in candidates:
                other_targets = by_chunk.get(other, set())
                union = targets | other_targets
                if not union:
                    continue
                jaccard = len(targets & other_targets) / len(union)
                if jaccard < _JACCARD_MIN:
                    continue
                out.append((chunk_id, other, _SAME_TARGET, jaccard))
        return out

    def _compute_anchor_follow(
        self,
        source_id: str,
    ) -> list[tuple[str, str, str, float]]:
        # For every (from_chunk, target_doc, target_anchor) with a non-empty
        # anchor, find every chunk in target_doc whose anchors include it.
        anchor_index: dict[tuple[str, str], list[str]] = {}
        for chunk_id, anchors in self._state.chunk_anchors.items():
            doc_id = self._state.chunk_document.get(chunk_id)
            if doc_id is None:
                continue
            for anchor in anchors:
                anchor_index.setdefault((doc_id, anchor), []).append(chunk_id)

        rows: list[tuple[str, str, str, float]] = []
        for (src, _), targets_for_doc in self._state.chunk_targets.items():
            if src != source_id:
                continue
            for chunk_id, target_doc, target_anchor in targets_for_doc:
                if not target_anchor:
                    continue
                for to_chunk_id in anchor_index.get((target_doc, target_anchor), ()):
                    if to_chunk_id == chunk_id:
                        continue
                    rows.append((chunk_id, to_chunk_id, _ANCHOR_FOLLOW, 1.0))
        return rows


class _MemoryGraphQuery:
    def __init__(self, state: _State, chunks: ChunkStore) -> None:
        self._state = state
        self._chunks = chunks

    async def get_chunk(
        self,
        source_id: str,
        chunk_id: str,
    ) -> ChunkWithGraph | None:
        doc_id = self._state.chunk_document.get(chunk_id)
        if doc_id is None:
            return None
        async for enriched in self.get_chunks(source_id, doc_id):
            if enriched.chunk.id == chunk_id:
                return enriched
        return None

    async def get_chunks(
        self,
        source_id: str,
        document_id: str,
    ) -> AsyncIterator[ChunkWithGraph]:
        cluster_id = self._state.clusters.get((source_id, document_id))
        backlinks = self._backlinks_for_doc(source_id, document_id)
        async for chunk in self._chunks.get(source_id, document_id):
            yield ChunkWithGraph(
                chunk=chunk,
                cluster_id=cluster_id,
                incoming_anchor_from=tuple(backlinks.get(chunk.id, ())),
            )

    async def cluster_peers(
        self,
        source_id: str,
        chunk_id: str,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        doc_id = self._state.chunk_document.get(chunk_id)
        if doc_id is None:
            return
        cluster_id = self._state.clusters.get((source_id, doc_id))
        if cluster_id is None:
            return
        yielded = 0
        for (src, peer_doc), cid in list(self._state.clusters.items()):
            if src != source_id or cid != cluster_id or peer_doc == doc_id:
                continue
            async for enriched in self.get_chunks(source_id, peer_doc):
                if limit is not None and yielded >= limit:
                    return
                yield enriched
                yielded += 1

    async def by_cluster(
        self,
        source_id: str,
        cluster_id: int,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        yielded = 0
        for (src, doc_id), cid in list(self._state.clusters.items()):
            if src != source_id or cid != cluster_id:
                continue
            async for enriched in self.get_chunks(source_id, doc_id):
                if limit is not None and yielded >= limit:
                    return
                yield enriched
                yielded += 1

    def _backlinks_for_doc(
        self,
        source_id: str,
        document_id: str,
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for from_id, to_id, channel, _weight in self._state.chunk_relations.get(
            source_id,
            (),
        ):
            if channel != _ANCHOR_FOLLOW:
                continue
            to_doc = self._state.chunk_document.get(to_id)
            if to_doc != document_id:
                continue
            result.setdefault(to_id, []).append(from_id)
        return result
