"""_SqliteGraphQuery: get_chunks + cluster_peers + get_chunk + by_cluster."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Chunk, Document, SyncState
from refweave.plugins.store.fs import FsStore
from refweave.plugins.store.sqlite_index import SqliteStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def stores(tmp_path: Path) -> AsyncIterator[tuple[FsStore, SqliteStore]]:
    fs = FsStore(tmp_path / "fs")
    await fs.init()
    sqlite = SqliteStore(tmp_path / "index.db")
    await sqlite.init()
    yield fs, sqlite
    await sqlite.close()
    await fs.close()


def _doc(source: str, external: str, *, version: int = 1) -> Document:
    return Document(
        id=f"doc:{source}:{external}",
        title=f"Doc {external}",
        sync=SyncState(version=version, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        graph_version=7,
    )


def _chunk(source: str, external: str, seq: int, text: str) -> Chunk:
    return Chunk(
        id=f"chk:{source}:{external}:{seq}",
        document=f"doc:{source}:{external}",
        seq=seq,
        text=text,
    )


async def test_get_chunks_returns_content_with_graph_version(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    doc = _doc("acme", "1")
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    chunks = [_chunk("acme", "1", 0, "hello"), _chunk("acme", "1", 1, "world")]
    await fs.chunks.put(doc, chunks)
    await sqlite.data.replace_chunks(doc, chunks)

    query = sqlite.query(fs.chunks)
    result = [c async for c in query.get_chunks("acme", "doc:acme:1")]

    assert len(result) == 2
    assert [c.chunk.text for c in result] == ["hello", "world"]
    assert all(c.cluster_id is None for c in result)
    assert all(c.incoming_anchor_from == () for c in result)


async def test_get_chunks_fills_cluster_id(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    doc = _doc("acme", "1")
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    chunk = _chunk("acme", "1", 0, "hi")
    await fs.chunks.put(doc, [chunk])
    await sqlite.data.replace_chunks(doc, [chunk])

    conn = sqlite._conn
    assert conn is not None
    await conn.execute(
        "INSERT INTO cluster VALUES (?, ?, ?)",
        ("acme", "doc:acme:1", 5),
    )
    await conn.commit()

    query = sqlite.query(fs.chunks)
    result = [c async for c in query.get_chunks("acme", "doc:acme:1")]
    assert result[0].cluster_id == 5


async def test_get_chunks_populates_incoming_anchor_from(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    doc = _doc("acme", "1")
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    chunks = [_chunk("acme", "1", 0, "target")]
    await fs.chunks.put(doc, chunks)
    await sqlite.data.replace_chunks(doc, chunks)

    conn = sqlite._conn
    assert conn is not None
    await conn.execute(
        "INSERT INTO chunk_relation VALUES (?, ?, ?, ?, ?)",
        ("chk:acme:9:0", "chk:acme:1:0", "anchor_follow", 1.0, "acme"),
    )
    await conn.execute(
        "INSERT INTO chunk_relation VALUES (?, ?, ?, ?, ?)",
        ("chk:acme:8:2", "chk:acme:1:0", "anchor_follow", 1.0, "acme"),
    )
    await conn.commit()

    query = sqlite.query(fs.chunks)
    result = [c async for c in query.get_chunks("acme", "doc:acme:1")]
    assert set(result[0].incoming_anchor_from) == {"chk:acme:9:0", "chk:acme:8:2"}


async def test_cluster_peers_yields_chunks_of_other_docs_in_cluster(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    for external, cluster in [("1", 10), ("2", 10), ("3", 20)]:
        doc = _doc("acme", external)
        await sqlite.data.put(doc)
        await fs.documents.put(doc)
        chunks = [_chunk("acme", external, 0, f"body-{external}")]
        await fs.chunks.put(doc, chunks)
        await sqlite.data.replace_chunks(doc, chunks)
        conn = sqlite._conn
        assert conn is not None
        await conn.execute(
            "INSERT INTO cluster VALUES (?, ?, ?)",
            ("acme", f"doc:acme:{external}", cluster),
        )
    conn = sqlite._conn
    assert conn is not None
    await conn.commit()

    query = sqlite.query(fs.chunks)
    peers = [c async for c in query.cluster_peers("acme", "chk:acme:1:0")]
    peer_docs = {c.chunk.document for c in peers}
    assert peer_docs == {"doc:acme:2"}


async def test_cluster_peers_respects_limit(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    for external in ("1", "2", "3", "4"):
        doc = _doc("acme", external)
        await sqlite.data.put(doc)
        await fs.documents.put(doc)
        chunks = [_chunk("acme", external, 0, f"body-{external}")]
        await fs.chunks.put(doc, chunks)
        await sqlite.data.replace_chunks(doc, chunks)
        conn = sqlite._conn
        assert conn is not None
        await conn.execute(
            "INSERT INTO cluster VALUES (?, ?, ?)",
            ("acme", f"doc:acme:{external}", 10),
        )
    conn = sqlite._conn
    assert conn is not None
    await conn.commit()

    query = sqlite.query(fs.chunks)
    peers = [c async for c in query.cluster_peers("acme", "chk:acme:1:0", limit=2)]
    assert len(peers) == 2


async def test_cluster_peers_returns_empty_when_no_cluster(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    doc = _doc("acme", "1")
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    chunk = _chunk("acme", "1", 0, "hi")
    await fs.chunks.put(doc, [chunk])
    await sqlite.data.replace_chunks(doc, [chunk])

    query = sqlite.query(fs.chunks)
    peers = [c async for c in query.cluster_peers("acme", "chk:acme:1:0")]
    assert peers == []


async def test_get_chunk_returns_enriched(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    doc = _doc("acme", "1")
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    chunks = [_chunk("acme", "1", 0, "a"), _chunk("acme", "1", 1, "b")]
    await fs.chunks.put(doc, chunks)
    await sqlite.data.replace_chunks(doc, chunks)

    query = sqlite.query(fs.chunks)
    result = await query.get_chunk("acme", "chk:acme:1:1")
    assert result is not None
    assert result.chunk.text == "b"


async def test_get_chunk_unknown_returns_none(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    _, sqlite = stores
    query = sqlite.query(_FakeEmptyChunkStore())
    assert await query.get_chunk("acme", "chk:acme:missing:0") is None


async def test_by_cluster_yields_all_chunks_of_cluster(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    for external in ("1", "2"):
        doc = _doc("acme", external)
        await sqlite.data.put(doc)
        await fs.documents.put(doc)
        chunks = [_chunk("acme", external, 0, f"body-{external}")]
        await fs.chunks.put(doc, chunks)
        await sqlite.data.replace_chunks(doc, chunks)
        conn = sqlite._conn
        assert conn is not None
        await conn.execute(
            "INSERT INTO cluster VALUES (?, ?, ?)",
            ("acme", f"doc:acme:{external}", 10),
        )
    conn = sqlite._conn
    assert conn is not None
    await conn.commit()

    query = sqlite.query(fs.chunks)
    result = [c async for c in query.by_cluster("acme", 10)]
    assert {c.chunk.document for c in result} == {"doc:acme:1", "doc:acme:2"}


async def test_by_cluster_respects_limit(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    for external in ("1", "2", "3"):
        doc = _doc("acme", external)
        await sqlite.data.put(doc)
        await fs.documents.put(doc)
        chunks = [_chunk("acme", external, 0, f"body-{external}")]
        await fs.chunks.put(doc, chunks)
        await sqlite.data.replace_chunks(doc, chunks)
        conn = sqlite._conn
        assert conn is not None
        await conn.execute(
            "INSERT INTO cluster VALUES (?, ?, ?)",
            ("acme", f"doc:acme:{external}", 10),
        )
    conn = sqlite._conn
    assert conn is not None
    await conn.commit()

    query = sqlite.query(fs.chunks)
    result = [c async for c in query.by_cluster("acme", 10, limit=2)]
    assert len(result) == 2


async def test_by_cluster_unknown_yields_nothing(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    query = sqlite.query(fs.chunks)
    result = [c async for c in query.by_cluster("acme", 999)]
    assert result == []


class _FakeEmptyChunkStore:
    async def put(self, document: object, chunks: object) -> None:
        del document, chunks

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[Chunk]:
        del source_id, document_id
        if False:
            yield  # type: ignore[unreachable]


async def test_query_factory_before_init_raises(tmp_path: Path) -> None:
    sqlite = SqliteStore(tmp_path / "db.sqlite")
    fs = FsStore(tmp_path / "fs")
    await fs.init()
    try:
        with pytest.raises(RuntimeError, match="must be awaited"):
            sqlite.query(fs.chunks)
    finally:
        await fs.close()
