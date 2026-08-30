"""Tests for MemoryStore — semantic parity with SqliteStore+FsStore."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from refweave.model import Chunk, ChunkLinkRef, Document, Link, Section, SyncState
from refweave.pipeline import Persistence
from refweave.plugins.keys import ANCHORS_KEY
from refweave.plugins.store import MemoryStore

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _doc(source: str, external: str) -> Document:
    doc_id = f"doc:{source}:{external}"
    return Document(
        id=doc_id,
        title=external,
        sections=(
            Section(
                id=f"sec:{source}:{external}:0",
                document=doc_id,
                seq=0,
                kind="paragraph",
                text="body",
                raw="",
            ),
        ),
        sync=SyncState(version=1, updated_at=_NOW),
    )


def _link(source: str, external: str, target: str) -> Link:
    return Link(
        id=f"lnk:{source}:{external}:0:0",
        document=f"doc:{source}:{external}",
        section=f"sec:{source}:{external}:0",
        seq=0,
        kind="page",
        target_document=target,
        target_anchor=None,
        resolved=True,
        metadata={},
    )


def _chunk(source: str, external: str, seq: int, *, targets: tuple[str, ...] = ()) -> Chunk:
    return Chunk(
        id=f"chk:{source}:{external}:{seq}",
        document=f"doc:{source}:{external}",
        seq=seq,
        text=f"chunk {seq}",
        sections=(f"sec:{source}:{external}:0",),
        outgoing_links=tuple(
            ChunkLinkRef(target_document=t, target_anchor=None, kind="page")
            for t in targets
        ),
    )


@pytest.mark.asyncio
async def test_init_close_are_noops() -> None:
    store = MemoryStore()
    await store.init()
    await store.close()


@pytest.mark.asyncio
async def test_document_roundtrip() -> None:
    store = MemoryStore()
    await store.init()
    doc = _doc("s", "a")
    await store.documents.put(doc)
    fetched = await store.documents.get("s", doc.id)
    assert fetched is not None
    assert fetched.id == doc.id


@pytest.mark.asyncio
async def test_document_iter_isolates_source() -> None:
    store = MemoryStore()
    await store.init()
    await store.documents.put(_doc("s1", "a"))
    await store.documents.put(_doc("s2", "b"))
    got = [d async for d in store.documents.iter("s1")]
    assert len(got) == 1
    assert got[0].id == "doc:s1:a"


@pytest.mark.asyncio
async def test_links_roundtrip() -> None:
    store = MemoryStore()
    await store.init()
    doc = _doc("s", "a")
    links = [_link("s", "a", "doc:s:b")]
    await store.links.put(doc, links)
    got = [link async for link in store.links.get("s", doc.id)]
    assert len(got) == 1
    assert got[0].target_document == "doc:s:b"


@pytest.mark.asyncio
async def test_data_index_bump_and_iter() -> None:
    store = MemoryStore()
    await store.init()
    v1 = await store.data.bump_graph_version("s")
    v2 = await store.data.bump_graph_version("s")
    assert v2 == v1 + 1
    doc = _doc("s", "a")
    await store.data.put(doc)
    states = [state async for state in store.data.iter("s")]
    assert len(states) == 1
    assert states[0].id == doc.id
    assert states[0].version == 1


@pytest.mark.asyncio
async def test_replace_chunk_targets_and_materialize_same_target() -> None:
    store = MemoryStore()
    await store.init()
    # Two docs, each with a chunk pointing at the same two target docs.
    doc_a = _doc("s", "a")
    doc_b = _doc("s", "b")
    await store.documents.put(doc_a)
    await store.documents.put(doc_b)
    chunk_a = _chunk("s", "a", 0, targets=("doc:s:x", "doc:s:y"))
    chunk_b = _chunk("s", "b", 0, targets=("doc:s:x", "doc:s:y"))
    await store.data.replace_chunks(doc_a, [chunk_a])
    await store.data.replace_chunks(doc_b, [chunk_b])
    await store.graph.replace_chunk_targets(
        doc_a,
        [(chunk_a.id, "doc:s:x", None), (chunk_a.id, "doc:s:y", None)],
    )
    await store.graph.replace_chunk_targets(
        doc_b,
        [(chunk_b.id, "doc:s:x", None), (chunk_b.id, "doc:s:y", None)],
    )
    count = await store.graph.materialize_relations("s")
    # Two chunks with identical target sets → 2 edges (a→b and b→a), Jaccard=1.
    assert count == 2


@pytest.mark.asyncio
async def test_materialize_excludes_navigation_chunks() -> None:
    store = MemoryStore()
    await store.init()
    doc_a = _doc("s", "a")
    doc_b = _doc("s", "b")
    await store.documents.put(doc_a)
    await store.documents.put(doc_b)
    # a's chunk is NAVIGATION — it should not source same_target edges.
    chunk_a = Chunk(
        id="chk:s:a:0",
        document="doc:s:a",
        seq=0,
        kind="navigation",
        text="see also",
        sections=("sec:s:a:0",),
        outgoing_links=(
            ChunkLinkRef(target_document="doc:s:x", target_anchor=None, kind="page"),
            ChunkLinkRef(target_document="doc:s:y", target_anchor=None, kind="page"),
        ),
    )
    chunk_b = _chunk("s", "b", 0, targets=("doc:s:x", "doc:s:y"))
    await store.data.replace_chunks(doc_a, [chunk_a])
    await store.data.replace_chunks(doc_b, [chunk_b])
    await store.graph.replace_chunk_targets(
        doc_a,
        [(chunk_a.id, "doc:s:x", None), (chunk_a.id, "doc:s:y", None)],
    )
    await store.graph.replace_chunk_targets(
        doc_b,
        [(chunk_b.id, "doc:s:x", None), (chunk_b.id, "doc:s:y", None)],
    )
    count = await store.graph.materialize_relations("s")
    assert count == 0  # navigation excluded → b has no same-target peers


@pytest.mark.asyncio
async def test_anchor_follow_via_materialize() -> None:
    store = MemoryStore()
    await store.init()
    # doc_a chunk points at doc_b#top; doc_b has a chunk carrying anchor "top".
    doc_a = _doc("s", "a")
    doc_b = _doc("s", "b")
    await store.documents.put(doc_a)
    await store.documents.put(doc_b)
    chunk_a = _chunk("s", "a", 0)
    chunk_b = Chunk(
        id="chk:s:b:0",
        document="doc:s:b",
        seq=0,
        text="target",
        sections=("sec:s:b:0",),
        metadata={ANCHORS_KEY: ("top",)},
    )
    await store.data.replace_chunks(doc_a, [chunk_a])
    await store.data.replace_chunks(doc_b, [chunk_b])
    await store.graph.replace_chunk_targets(
        doc_a,
        [(chunk_a.id, "doc:s:b", "top")],
    )
    count = await store.graph.materialize_relations("s")
    assert count == 1  # single anchor_follow edge


@pytest.mark.asyncio
async def test_rebuild_clusters_produces_a_mapping() -> None:
    store = MemoryStore()
    await store.init()
    # Fully-connected 3-doc graph: leiden should return at least 1 cluster.
    for name in ("a", "b", "c"):
        doc = _doc("s", name)
        await store.documents.put(doc)
        await store.graph.replace_chunk_targets(
            doc,
            [
                (f"chk:s:{name}:0", f"doc:s:{other}", None)
                for other in ("a", "b", "c")
                if other != name
            ],
        )
    n_clusters = await store.graph.rebuild_clusters("s")
    assert n_clusters >= 1


@pytest.mark.asyncio
async def test_graphquery_get_chunks_returns_cluster_and_content() -> None:
    store = MemoryStore()
    await store.init()
    doc = _doc("s", "a")
    await store.documents.put(doc)
    chunks = [_chunk("s", "a", 0), _chunk("s", "a", 1)]
    await store.chunks.put(doc, chunks)
    await store.data.replace_chunks(doc, chunks)
    query = store.query()
    got = [cw async for cw in query.get_chunks("s", doc.id)]
    assert len(got) == 2
    assert got[0].chunk.id == "chk:s:a:0"
    assert got[0].cluster_id is None  # no rebuild_clusters yet


@pytest.mark.asyncio
async def test_persistence_bundle_wires_memory_store_transparently() -> None:
    store = MemoryStore()
    await store.init()
    persistence = Persistence(
        documents=store.documents,
        links=store.links,
        chunks=store.chunks,
        data=store.data,
        graph=store.graph,
        query=store.query(),
    )
    doc = _doc("s", "a")
    await persistence.save_document(doc)
    await persistence.save_links(doc, [_link("s", "a", "doc:s:b")])
    await persistence.save_chunks(doc, [_chunk("s", "a", 0)])
    # Round-trip: read back via the same bundle.
    fetched = await persistence.documents.get("s", doc.id)
    assert fetched is not None
    links = [link async for link in persistence.links.get("s", doc.id)]
    assert len(links) == 1
    got_chunks = [c async for c in persistence.chunks.get("s", doc.id)]
    assert len(got_chunks) == 1


@pytest.mark.asyncio
async def test_replace_chunks_purges_side_maps_by_document_id() -> None:
    """Rechunking with fewer chunks must not leak old chunk_ids into
    chunk_document / chunk_kind / chunk_anchors. Prior implementation
    walked the current blob store, which — if `chunks.put(new_chunks)`
    ran before `data.replace_chunks(new_chunks)` — would only see the
    new chunk_ids and miss any removed ones. This test enforces the
    order-independent invariant.
    """
    store = MemoryStore()
    await store.init()
    doc = _doc("s", "a")

    old_chunks = [_chunk("s", "a", 0), _chunk("s", "a", 1), _chunk("s", "a", 2)]
    await store.chunks.put(doc, old_chunks)
    await store.data.replace_chunks(doc, old_chunks)

    new_chunks = [_chunk("s", "a", 0), _chunk("s", "a", 1)]
    # Simulate orchestrator's order: blob put first, then index update.
    await store.chunks.put(doc, new_chunks)
    await store.data.replace_chunks(doc, new_chunks)

    # The now-orphaned "chk:s:a:2" must be gone from every side map.
    assert "chk:s:a:2" not in store._state.chunk_document
    assert "chk:s:a:2" not in store._state.chunk_kind
    assert "chk:s:a:2" not in store._state.chunk_anchors
    # And the survivors are correctly registered.
    assert store._state.chunk_document["chk:s:a:0"] == doc.id
    assert store._state.chunk_document["chk:s:a:1"] == doc.id


@pytest.mark.asyncio
async def test_replace_chunks_does_not_touch_other_documents() -> None:
    store = MemoryStore()
    await store.init()
    doc_a = _doc("s", "a")
    doc_b = _doc("s", "b")
    await store.data.replace_chunks(doc_a, [_chunk("s", "a", 0)])
    await store.data.replace_chunks(doc_b, [_chunk("s", "b", 0)])
    # Rechunk doc_a with an empty set — must not disturb doc_b's mappings.
    await store.data.replace_chunks(doc_a, [])
    assert "chk:s:a:0" not in store._state.chunk_document
    assert store._state.chunk_document["chk:s:b:0"] == doc_b.id
