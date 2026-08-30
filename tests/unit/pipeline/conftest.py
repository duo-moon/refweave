"""In-memory Persistence + fake Source/Chunker/Resolver for orchestrator tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeAlias

import pytest

from refweave.ids import parse_document_id
from refweave.model import Chunk, ChunkWithGraph, Document, Link, SyncState
from refweave.pipeline import Persistence, SyncedDocument
from refweave.pipeline.persistence import DocumentState


class FakeDocumentStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Document] = {}

    async def put(self, document: Document) -> None:
        source_id, _ = parse_document_id(document.id)
        self._data[(source_id, document.id)] = document

    async def get(self, source_id: str, document_id: str) -> Document | None:
        return self._data.get((source_id, document_id))

    async def iter(self, source_id: str) -> AsyncIterator[Document]:
        for (sid, _), doc in self._data.items():
            if sid == source_id:
                yield doc


class FakeLinkStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[Link]] = {}

    async def put(self, document: Document, links: Sequence[Link]) -> None:
        source_id, _ = parse_document_id(document.id)
        self._data[(source_id, document.id)] = list(links)

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[Link]:
        for link in self._data.get((source_id, document_id), ()):
            yield link


class FakeChunkStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[Chunk]] = {}

    async def put(self, document: Document, chunks: Sequence[Chunk]) -> None:
        source_id, _ = parse_document_id(document.id)
        self._data[(source_id, document.id)] = list(chunks)

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[Chunk]:
        for chunk in self._data.get((source_id, document_id), ()):
            yield chunk


class FakeDataIndex:
    def __init__(self) -> None:
        self._states: dict[str, DocumentState] = {}
        self._versions: dict[str, int] = {}

    async def bump_graph_version(self, source_id: str) -> int:
        self._versions[source_id] = self._versions.get(source_id, 0) + 1
        return self._versions[source_id]

    async def put(self, document: Document) -> None:
        self._states[document.id] = DocumentState(
            id=document.id,
            version=document.sync.version,
            deleted_at=document.sync.deleted_at,
        )

    async def iter(self, source_id: str) -> AsyncIterator[DocumentState]:
        for state in self._states.values():
            state_source_id, _ = parse_document_id(state.id)
            if state_source_id == source_id:
                yield state

    async def replace_chunks(self, document: Document, chunks: Sequence[Chunk]) -> None:
        del document, chunks


class FakeGraphIndex:
    def __init__(self) -> None:
        self.materialize_calls: list[str] = []
        self.rebuild_calls: list[str] = []

    async def replace_chunk_targets(
        self,
        document: Document,
        rows: Sequence[tuple[str, str, str | None]],
    ) -> None:
        del document, rows

    async def rebuild_clusters(self, source_id: str) -> int:
        self.rebuild_calls.append(source_id)
        return 42

    async def materialize_relations(self, source_id: str) -> int:
        self.materialize_calls.append(source_id)
        return 7


class FakeGraphQuery:
    async def get_chunk(
        self,
        source_id: str,
        chunk_id: str,
    ) -> ChunkWithGraph | None:
        del source_id, chunk_id
        return None

    async def get_chunks(
        self,
        source_id: str,
        document_id: str,
    ) -> AsyncIterator[ChunkWithGraph]:
        del source_id, document_id
        if False:
            yield  # type: ignore[unreachable]

    async def cluster_peers(
        self,
        source_id: str,
        chunk_id: str,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        del source_id, chunk_id, limit
        if False:
            yield  # type: ignore[unreachable]

    async def by_cluster(
        self,
        source_id: str,
        cluster_id: int,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ChunkWithGraph]:
        del source_id, cluster_id, limit
        if False:
            yield  # type: ignore[unreachable]


@dataclass
class FakePersistence:
    documents: FakeDocumentStore = field(default_factory=FakeDocumentStore)
    links: FakeLinkStore = field(default_factory=FakeLinkStore)
    chunks: FakeChunkStore = field(default_factory=FakeChunkStore)
    data: FakeDataIndex = field(default_factory=FakeDataIndex)
    graph: FakeGraphIndex = field(default_factory=FakeGraphIndex)
    query: FakeGraphQuery = field(default_factory=FakeGraphQuery)

    async def save_document(self, document: Document) -> None:
        await self.documents.put(document)
        await self.data.put(document)

    async def save_links(self, document: Document, links: Sequence[Link]) -> None:
        await self.links.put(document, links)

    async def save_chunks(self, document: Document, chunks: Sequence[Chunk]) -> None:
        await self.chunks.put(document, chunks)
        await self.data.replace_chunks(document, chunks)
        rows: list[tuple[str, str, str | None]] = []
        for chunk in chunks:
            for ref in chunk.outgoing_links:
                if ref.target_document is None:
                    continue
                rows.append((chunk.id, ref.target_document, ref.target_anchor))
        await self.graph.replace_chunk_targets(document, rows)


@pytest.fixture
def persistence() -> Persistence:
    return FakePersistence()  # type: ignore[return-value]


class FakeSource:
    def __init__(self, source_id: str, items: Sequence[SyncedDocument]) -> None:
        self.source_id = source_id
        self._items = list(items)

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        for item in self._items:
            yield item

    async def aclose(self) -> None:
        pass


class FakeChunker:
    """Emits one chunk per document that concatenates all section texts."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []  # (doc_id, len(links))

    def chunk(
        self,
        document: Document,
        links: Sequence[Link],
    ) -> Iterator[Chunk]:
        self.calls.append((document.id, len(links)))
        source_id, external = parse_document_id(document.id)
        yield Chunk(
            id=f"chk:{source_id}:{external}:0",
            document=document.id,
            seq=0,
            text=" ".join(s.text for s in document.sections),
            sections=tuple(s.id for s in document.sections),
        )


class FakeResolver:
    def __init__(self) -> None:
        self.prepare_calls: int = 0
        self.resolve_calls: list[str] = []

    async def prepare(self, docs: AsyncIterator[Document]) -> None:
        self.prepare_calls += 1
        async for _ in docs:
            pass

    def resolve(self, doc: Document, links: Sequence[Link]) -> Sequence[Link]:
        self.resolve_calls.append(doc.id)
        return links


def make_document(
    source_id: str,
    external: str,
    *,
    version: int = 1,
    deleted_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Document:
    ts = updated_at or datetime(2026, 1, 1, tzinfo=UTC)
    return Document(
        id=f"doc:{source_id}:{external}",
        title=f"Page {external}",
        sync=SyncState(version=version, updated_at=ts, deleted_at=deleted_at),
    )


def make_synced(
    source_id: str,
    external: str,
    *,
    version: int = 1,
    deleted_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SyncedDocument:
    document = make_document(
        source_id,
        external,
        version=version,
        deleted_at=deleted_at,
        updated_at=updated_at,
    )
    return SyncedDocument(document=document, links=())


SourceFactory: TypeAlias = Callable[[Sequence[SyncedDocument]], FakeSource]


@pytest.fixture
def source_factory() -> SourceFactory:
    def _make(items: Sequence[SyncedDocument]) -> FakeSource:
        return FakeSource(source_id="src", items=items)

    return _make


@pytest.fixture
def chunker() -> FakeChunker:
    return FakeChunker()


@pytest.fixture
def resolver() -> FakeResolver:
    return FakeResolver()
