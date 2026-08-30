"""_SqliteGraphIndex.materialize_relations — anchor_follow + same_target."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Chunk, ChunkLinkRef, Document, SyncState
from refweave.plugins.keys import ANCHORS_KEY
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


def _doc(external: str) -> Document:
    return Document(
        id=f"doc:acme:{external}",
        title=f"Doc {external}",
        sync=SyncState(version=1, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
    )


def _chunk(
    external: str,
    seq: int,
    *,
    anchors: tuple[str, ...] = (),
    outgoing: tuple[ChunkLinkRef, ...] = (),
) -> Chunk:
    metadata = {ANCHORS_KEY: anchors} if anchors else {}
    return Chunk(
        id=f"chk:acme:{external}:{seq}",
        document=f"doc:acme:{external}",
        seq=seq,
        text=f"chunk {external}/{seq}",
        outgoing_links=outgoing,
        metadata=metadata,
    )


async def _seed(fs: FsStore, sqlite: SqliteStore, doc: Document, chunks: list[Chunk]) -> None:
    await sqlite.data.put(doc)
    await fs.documents.put(doc)
    await fs.chunks.put(doc, chunks)
    await sqlite.data.replace_chunks(doc, chunks)


async def test_anchor_follow_links_source_chunk_to_target_anchor_chunk(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    # Target doc with a chunk carrying anchor "setup".
    target_doc = _doc("target")
    target_chunk = _chunk("target", 0, anchors=("setup",))
    await _seed(fs, sqlite, target_doc, [target_chunk])

    # Source doc: chunk links to doc:acme:target#setup.
    source_doc = _doc("source")
    source_chunk = _chunk(
        "source",
        0,
        outgoing=(
            ChunkLinkRef(
                target_document="doc:acme:target",
                target_anchor="setup",
                kind="page",
            ),
        ),
    )
    await _seed(fs, sqlite, source_doc, [source_chunk])
    await sqlite.graph.replace_chunk_targets(
        source_doc,
        [(source_chunk.id, "doc:acme:target", "setup")],
    )

    inserted = await sqlite.graph.materialize_relations("acme")
    assert inserted >= 1

    # Verify anchor_follow row exists.
    conn = sqlite._conn
    assert conn is not None
    async with conn.execute(
        """
        SELECT from_chunk_id, to_chunk_id, channel FROM chunk_relation
        WHERE source_id = ? AND channel = 'anchor_follow'
        """,
        ("acme",),
    ) as cur:
        rows = [(r["from_chunk_id"], r["to_chunk_id"], r["channel"]) async for r in cur]
    assert (source_chunk.id, target_chunk.id, "anchor_follow") in rows


async def test_anchor_follow_ignores_when_anchor_missing_on_target(
    stores: tuple[FsStore, SqliteStore],
) -> None:
    fs, sqlite = stores
    # Target chunks WITHOUT anchor metadata.
    target_doc = _doc("target")
    target_chunk = _chunk("target", 0)  # no anchors
    await _seed(fs, sqlite, target_doc, [target_chunk])

    source_doc = _doc("source")
    source_chunk = _chunk(
        "source",
        0,
        outgoing=(
            ChunkLinkRef(
                target_document="doc:acme:target",
                target_anchor="nonexistent",
                kind="page",
            ),
        ),
    )
    await _seed(fs, sqlite, source_doc, [source_chunk])
    await sqlite.graph.replace_chunk_targets(
        source_doc,
        [(source_chunk.id, "doc:acme:target", "nonexistent")],
    )

    inserted = await sqlite.graph.materialize_relations("acme")
    # No anchor_follow row (target has no matching anchor); may have same_target if applicable.
    conn = sqlite._conn
    assert conn is not None
    async with conn.execute(
        "SELECT channel FROM chunk_relation WHERE source_id = ?",
        ("acme",),
    ) as cur:
        channels = [r["channel"] async for r in cur]
    assert "anchor_follow" not in channels
    del inserted  # count may be 0
