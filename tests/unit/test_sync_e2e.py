"""End-to-end smoke: sync() over MemoryStore + fake source + real chunker + resolver.

Verifies that the shipping components wire together — MemoryStore's
DocumentStore + LinkStore + ChunkStore + DataIndex + GraphIndex +
GraphQuery all cooperate under the orchestrator without hidden coupling
that the FakePersistence-based orchestrator tests could miss.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.ids import chunk_id, document_id, link_id, section_id
from refweave.model import Document, Link, Section, SyncState
from refweave.pipeline import Persistence, SyncedDocument, rechunk, recompute_clusters, sync
from refweave.plugins.chunker import HeadingRule, Policy, PolicyChunker, SizeLimitRule
from refweave.plugins.kinds import SectionKind
from refweave.plugins.store import MemoryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _doc(source_id: str, external: str, *, title: str, body: str) -> Document:
    """Two-section doc: a heading + a paragraph carrying `body`."""
    doc_id = document_id(source_id, external)
    return Document(
        id=doc_id,
        title=title,
        sections=(
            Section(
                id=section_id(source_id, external, 0),
                document=doc_id,
                seq=0,
                kind=SectionKind.HEADING,
                text=title,
                raw=f"# {title}",
                metadata={"heading_level": 1},
            ),
            Section(
                id=section_id(source_id, external, 1),
                document=doc_id,
                seq=1,
                kind=SectionKind.PARAGRAPH,
                text=body,
                raw=body,
            ),
        ),
        sync=SyncState(version=1, updated_at=_NOW),
    )


def _link(
    source_id: str,
    external: str,
    section_seq: int,
    link_seq: int,
    target: str,
) -> Link:
    doc_id = document_id(source_id, external)
    return Link(
        id=link_id(source_id, external, section_seq, link_seq),
        document=doc_id,
        section=section_id(source_id, external, section_seq),
        seq=link_seq,
        kind="internal",
        target_document=target,
        resolved=True,
    )


class _FakeSource:
    """Yields a fixed set of `SyncedDocument`s. Docs pre-linked A → B."""

    def __init__(self, source_id: str = "s") -> None:
        self.source_id = source_id
        doc_a = _doc(source_id, "a", title="Doc A", body="alpha content")
        doc_b = _doc(source_id, "b", title="Doc B", body="beta content")
        doc_c = _doc(source_id, "c", title="Doc C", body="gamma content")
        self._items: list[SyncedDocument] = [
            SyncedDocument(
                document=doc_a,
                links=(
                    _link(source_id, "a", 1, 0, document_id(source_id, "b")),
                    _link(source_id, "a", 1, 1, document_id(source_id, "c")),
                ),
            ),
            SyncedDocument(document=doc_b, links=()),
            SyncedDocument(document=doc_c, links=()),
        ]

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        for item in self._items:
            yield item

    async def aclose(self) -> None:
        pass


async def _persistence() -> Persistence:
    store = MemoryStore()
    await store.init()
    return Persistence(
        documents=store.documents,
        links=store.links,
        chunks=store.chunks,
        data=store.data,
        graph=store.graph,
        query=store.query(),
    )


def _chunker() -> PolicyChunker:
    return PolicyChunker(
        policy=Policy([HeadingRule(), SizeLimitRule(max_chars=4000)]),
    )


@pytest.mark.asyncio
async def test_sync_stores_docs_and_links_and_chunks() -> None:
    persistence = await _persistence()
    report = await sync(_FakeSource(), _chunker(), persistence)

    assert report.created == 3
    assert report.skipped == 0
    assert report.deleted == 0

    stored_a = await persistence.documents.get("s", document_id("s", "a"))
    assert stored_a is not None
    assert stored_a.title == "Doc A"

    a_links = [link async for link in persistence.links.get("s", document_id("s", "a"))]
    assert len(a_links) == 2
    assert {link.target_document for link in a_links} == {
        document_id("s", "b"),
        document_id("s", "c"),
    }

    a_chunks = [cwg async for cwg in persistence.query.get_chunks("s", document_id("s", "a"))]
    assert len(a_chunks) >= 1
    assert any("alpha content" in cwg.chunk.text for cwg in a_chunks)


@pytest.mark.asyncio
async def test_sync_second_run_skips_unchanged() -> None:
    persistence = await _persistence()
    await sync(_FakeSource(), _chunker(), persistence)
    report = await sync(_FakeSource(), _chunker(), persistence)

    assert report.skipped == 3
    assert report.created == 0
    assert report.updated == 0


@pytest.mark.asyncio
async def test_rechunk_uses_new_policy_without_resync() -> None:
    persistence = await _persistence()
    await sync(_FakeSource(), _chunker(), persistence)

    tighter = PolicyChunker(policy=Policy([SizeLimitRule(max_chars=10)]))
    report = await rechunk("s", tighter, persistence)

    assert report.rechunked == 3
    a_chunks = [cwg async for cwg in persistence.query.get_chunks("s", document_id("s", "a"))]
    # Tiny limit → more chunks than the loose baseline.
    assert len(a_chunks) >= 2


@pytest.mark.asyncio
async def test_recompute_clusters_produces_clusters() -> None:
    persistence = await _persistence()
    await sync(_FakeSource(), _chunker(), persistence)
    report = await recompute_clusters("s", persistence)

    # 3 docs, 2 edges (A→B, A→C) — one connected component, one cluster.
    assert report.clusters >= 1


@pytest.mark.asyncio
async def test_sync_tombstones_removed_docs() -> None:
    persistence = await _persistence()
    await sync(_FakeSource(), _chunker(), persistence)

    class _Shorter:
        source_id = "s"

        async def iter(self) -> AsyncIterator[SyncedDocument]:
            source = _FakeSource()
            for i, item in enumerate(source._items):
                if i == 0:
                    yield item

        async def aclose(self) -> None:
            pass

    report = await sync(_Shorter(), _chunker(), persistence)
    assert report.deleted == 2

    b_stored = await persistence.documents.get("s", document_id("s", "b"))
    assert b_stored is not None
    assert b_stored.sync.deleted_at is not None


@pytest.mark.asyncio
async def test_sync_ids_use_id_helpers() -> None:
    """Ensures round-trip: sync produces id shapes that match `refweave.ids` helpers."""
    persistence = await _persistence()
    await sync(_FakeSource(), _chunker(), persistence)

    a_chunks = [cwg async for cwg in persistence.query.get_chunks("s", document_id("s", "a"))]
    assert a_chunks[0].chunk.id == chunk_id("s", "a", 0)


class _CyclicSource:
    """A ↔ B with reciprocal links, plus A → A self-loop."""

    source_id = "cyc"

    def __init__(self) -> None:
        a_id = document_id("cyc", "a")
        b_id = document_id("cyc", "b")
        doc_a = _doc("cyc", "a", title="Doc A", body="alpha")
        doc_b = _doc("cyc", "b", title="Doc B", body="beta")
        self._items: list[SyncedDocument] = [
            SyncedDocument(
                document=doc_a,
                links=(
                    _link("cyc", "a", 1, 0, b_id),
                    _link("cyc", "a", 1, 1, a_id),  # self-loop
                ),
            ),
            SyncedDocument(
                document=doc_b,
                links=(_link("cyc", "b", 1, 0, a_id),),
            ),
        ]

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        for item in self._items:
            yield item

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_sync_handles_cyclic_and_self_referential_links() -> None:
    """Cyclic (A→B→A) and self-loop (A→A) links must not break the pipeline."""
    persistence = await _persistence()
    await sync(_CyclicSource(), _chunker(), persistence)
    report = await recompute_clusters("cyc", persistence)

    # 2 docs, a mutual edge + one self-loop → at least one cluster.
    assert report.clusters >= 1
