"""Orchestrator: sync / rechunk / recompute_clusters."""

from __future__ import annotations

from datetime import UTC, datetime

from refweave.pipeline import rechunk, recompute_clusters, sync
from tests.unit.pipeline.conftest import (
    FakeChunker,
    FakePersistence,
    FakeResolver,
    SourceFactory,
    make_document,
    make_synced,
)


async def test_sync_creates_new_document(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    source = source_factory([make_synced("src", "1")])
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]

    assert report.created == 1
    assert report.updated == 0
    assert report.skipped == 0
    stored = await persistence.documents.get("src", "doc:src:1")
    assert stored is not None
    assert chunker.calls == [("doc:src:1", 0)]
    assert persistence.graph.materialize_calls == ["src"]


async def test_sync_skips_unchanged_document(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    await persistence.documents.put(make_document("src", "1", version=5))
    await persistence.data.put(make_document("src", "1", version=5))

    source = source_factory([make_synced("src", "1", version=5)])
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]

    assert report.skipped == 1
    assert report.created == 0
    assert chunker.calls == []  # skipped docs not rechunked


async def test_sync_updates_changed_document(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    await persistence.documents.put(make_document("src", "1", version=1))
    await persistence.data.put(make_document("src", "1", version=1))

    source = source_factory([make_synced("src", "1", version=2)])
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]

    assert report.updated == 1
    assert report.created == 0
    stored = await persistence.documents.get("src", "doc:src:1")
    assert stored is not None
    assert stored.sync.version == 2


async def test_sync_tombstones_missing_document(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    await persistence.documents.put(make_document("src", "1"))
    await persistence.data.put(make_document("src", "1"))

    source = source_factory([])  # source no longer sees the doc
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]

    assert report.deleted == 1
    tombstoned = await persistence.documents.get("src", "doc:src:1")
    assert tombstoned is not None
    assert tombstoned.sync.deleted_at is not None


async def test_sync_resurrects_tombstoned_document(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    tomb = make_document("src", "1", version=1, deleted_at=ts)
    await persistence.documents.put(tomb)
    await persistence.data.put(tomb)

    source = source_factory([make_synced("src", "1", version=2)])
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]

    assert report.resurrected == 1
    assert report.updated == 0
    revived = await persistence.documents.get("src", "doc:src:1")
    assert revived is not None
    assert revived.sync.deleted_at is None


async def test_sync_calls_resolver_when_provided(
    persistence: FakePersistence,
    chunker: FakeChunker,
    resolver: FakeResolver,
    source_factory: SourceFactory,
) -> None:
    source = source_factory([make_synced("src", "1")])
    await sync(source, chunker, persistence, resolver)  # type: ignore[arg-type]
    assert resolver.prepare_calls == 1
    assert resolver.resolve_calls == ["doc:src:1"]


async def test_sync_without_resolver_works(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    source = source_factory([make_synced("src", "1")])
    report = await sync(source, chunker, persistence)  # type: ignore[arg-type]
    assert report.created == 1


async def test_sync_materializes_relations_last(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    source = source_factory([make_synced("src", "1")])
    await sync(source, chunker, persistence)  # type: ignore[arg-type]
    assert persistence.graph.materialize_calls == ["src"]


async def test_sync_stamps_graph_version_on_docs(
    persistence: FakePersistence,
    chunker: FakeChunker,
    source_factory: SourceFactory,
) -> None:
    source = source_factory([make_synced("src", "1")])
    await sync(source, chunker, persistence)  # type: ignore[arg-type]
    stored = await persistence.documents.get("src", "doc:src:1")
    assert stored is not None
    assert stored.graph_version == 1  # bump_graph_version increments to 1


async def test_rechunk_processes_all_live_docs(
    persistence: FakePersistence,
    chunker: FakeChunker,
) -> None:
    for external in ("1", "2"):
        doc = make_document("src", external)
        await persistence.documents.put(doc)
        await persistence.data.put(doc)

    report = await rechunk("src", chunker, persistence)  # type: ignore[arg-type]

    assert report.rechunked == 2
    assert {c[0] for c in chunker.calls} == {"doc:src:1", "doc:src:2"}


async def test_rechunk_skips_tombstoned(
    persistence: FakePersistence,
    chunker: FakeChunker,
) -> None:
    live = make_document("src", "1")
    tomb = make_document("src", "2", deleted_at=datetime(2026, 1, 1, tzinfo=UTC))
    for doc in (live, tomb):
        await persistence.documents.put(doc)
        await persistence.data.put(doc)

    report = await rechunk("src", chunker, persistence)  # type: ignore[arg-type]

    assert report.rechunked == 1
    assert chunker.calls == [("doc:src:1", 0)]


async def test_recompute_clusters_delegates_to_graph_index(
    persistence: FakePersistence,
) -> None:
    report = await recompute_clusters("src", persistence)  # type: ignore[arg-type]
    assert report.clusters == 42
    assert persistence.graph.rebuild_calls == ["src"]
