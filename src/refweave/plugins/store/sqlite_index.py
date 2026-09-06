"""SQLite implementation of DataIndex, GraphIndex, and GraphQuery.

Schema:
    document       — Document snapshot for sync decisions.
    chunk          — Chunk rows (id, source, doc, seq, kind).
    chunk_anchor   — (chunk, anchor) mapping for anchor_follow lookups.
    chunk_target   — Graph edges (chunk → target document).
    cluster        — Leiden cluster mappings (document → cluster_id, per algo_version).
    chunk_relation — Materialized same_target / anchor_follow edges.
    meta           — Per-source bookkeeping (graph_version).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import aiosqlite

from refweave.graph import run_leiden
from refweave.ids import source_of
from refweave.model import Chunk, ChunkWithGraph, Document
from refweave.pipeline import DocumentState
from refweave.plugins.keys import chunk_anchors
from refweave.plugins.store._defaults import SAME_TARGET_EXCLUDED_KINDS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from refweave.pipeline import ChunkStore

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS document (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    version       INTEGER NOT NULL,
    deleted_at    TEXT,
    graph_version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_document_source ON document(source_id);

CREATE TABLE IF NOT EXISTS chunk (
    id             TEXT PRIMARY KEY,
    source_id      TEXT NOT NULL,
    document_id    TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    kind           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_source ON chunk(source_id);
CREATE INDEX IF NOT EXISTS idx_chunk_document ON chunk(document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_kind ON chunk(kind);

CREATE TABLE IF NOT EXISTS chunk_anchor (
    chunk_id    TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    document_id TEXT NOT NULL,
    anchor      TEXT NOT NULL,
    PRIMARY KEY (chunk_id, anchor)
);
CREATE INDEX IF NOT EXISTS idx_chunk_anchor_source ON chunk_anchor(source_id);
CREATE INDEX IF NOT EXISTS idx_chunk_anchor_lookup
    ON chunk_anchor(document_id, anchor);

CREATE TABLE IF NOT EXISTS chunk_target (
    chunk_id        TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    document_id     TEXT NOT NULL,
    target_document TEXT NOT NULL,
    target_anchor   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chunk_id, target_document, target_anchor)
);
CREATE INDEX IF NOT EXISTS idx_chunk_target_source ON chunk_target(source_id);
CREATE INDEX IF NOT EXISTS idx_chunk_target_document ON chunk_target(document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_target_target ON chunk_target(target_document);

CREATE TABLE IF NOT EXISTS cluster (
    source_id   TEXT NOT NULL,
    document_id TEXT NOT NULL,
    cluster_id  INTEGER NOT NULL,
    PRIMARY KEY (source_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_cluster_lookup ON cluster(source_id, cluster_id);

CREATE TABLE IF NOT EXISTS chunk_relation (
    from_chunk_id TEXT NOT NULL,
    to_chunk_id   TEXT NOT NULL,
    channel       TEXT NOT NULL,
    weight        REAL NOT NULL,
    source_id     TEXT NOT NULL,
    PRIMARY KEY (from_chunk_id, to_chunk_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_chunk_relation_from
    ON chunk_relation(from_chunk_id, channel);
CREATE INDEX IF NOT EXISTS idx_chunk_relation_source ON chunk_relation(source_id);

CREATE TABLE IF NOT EXISTS meta (
    source_id TEXT NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    PRIMARY KEY (source_id, key)
);
"""

_META_GRAPH_VERSION: Final = "graph_version"

_JACCARD_MIN: Final = 1e-6
_MIN_TARGETS_FOR_SAME_TARGET: Final = 2
_SAME_TARGET_CHANNEL: Final = "same_target"
_ANCHOR_FOLLOW_CHANNEL: Final = "anchor_follow"


def _to_document_state(row: Any) -> DocumentState:
    deleted_at = datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None
    return DocumentState(
        id=row["id"],
        version=row["version"],
        deleted_at=deleted_at,
    )


class _SqliteDataIndex:
    """SQLite-backed DataIndex — document snapshot + graph_version metadata."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def bump_graph_version(self, source_id: str) -> int:
        async with self._conn.execute(
            "SELECT value FROM meta WHERE source_id=? AND key=?",
            (source_id, _META_GRAPH_VERSION),
        ) as cur:
            row = await cur.fetchone()
        current = int(row["value"]) if row else 0
        new_version = current + 1
        await self._conn.execute(
            """
            INSERT INTO meta (source_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(source_id, key) DO UPDATE SET value=excluded.value
            """,
            (source_id, _META_GRAPH_VERSION, str(new_version)),
        )
        await self._conn.commit()
        return new_version

    async def put(self, document: Document) -> None:
        await self._conn.execute(
            """
            INSERT INTO document
                (id, source_id, version, deleted_at, graph_version)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_id     = excluded.source_id,
                version       = excluded.version,
                deleted_at    = excluded.deleted_at,
                graph_version = excluded.graph_version
            """,
            (
                document.id,
                source_of(document.id),
                document.sync.version,
                document.sync.deleted_at.isoformat() if document.sync.deleted_at else None,
                document.graph_version,
            ),
        )
        await self._conn.commit()

    async def iter(self, source_id: str) -> AsyncIterator[DocumentState]:
        async with self._conn.execute(
            """
            SELECT id, version, deleted_at
            FROM document WHERE source_id=?
            """,
            (source_id,),
        ) as cur:
            async for row in cur:
                yield _to_document_state(row)

    async def replace_chunks(self, document: Document, chunks: Sequence[Chunk]) -> None:
        source_id = source_of(document.id)
        await self._conn.execute(
            "DELETE FROM chunk WHERE source_id=? AND document_id=?",
            (source_id, document.id),
        )
        await self._conn.execute(
            "DELETE FROM chunk_anchor WHERE source_id=? AND document_id=?",
            (source_id, document.id),
        )
        if chunks:
            await self._conn.executemany(
                """
                INSERT INTO chunk (id, source_id, document_id, seq, kind)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        source_id,
                        chunk.document,
                        chunk.seq,
                        chunk.kind,
                    )
                    for chunk in chunks
                ],
            )
            anchor_rows = [
                (chunk.id, source_id, chunk.document, anchor)
                for chunk in chunks
                for anchor in chunk_anchors(chunk)
            ]
            if anchor_rows:
                await self._conn.executemany(
                    """
                    INSERT INTO chunk_anchor (chunk_id, source_id, document_id, anchor)
                    VALUES (?, ?, ?, ?)
                    """,
                    anchor_rows,
                )
        await self._conn.commit()


class _SqliteGraphIndex:
    """SQLite-backed GraphIndex — chunk_target edges, cluster mapping, and
    chunk_relation materialization (same_target + anchor_follow channels).

    `exclude_from_same_target` — chunk kinds that must not source
    `same_target` edges. Only the same_target channel is filtered;
    `anchor_follow` ignores this parameter. See `plugins.store._defaults`
    for the shared default.
    """

    def __init__(
        self,
        conn: aiosqlite.Connection,
        *,
        exclude_from_same_target: Iterable[str] = SAME_TARGET_EXCLUDED_KINDS,
    ) -> None:
        self._conn = conn
        self._excluded = tuple(exclude_from_same_target)

    async def replace_chunk_targets(
        self,
        document: Document,
        rows: Sequence[tuple[str, str, str | None]],
    ) -> None:
        source_id = source_of(document.id)
        await self._conn.execute(
            "DELETE FROM chunk_target WHERE source_id=? AND document_id=?",
            (source_id, document.id),
        )
        if rows:
            await self._conn.executemany(
                """
                INSERT INTO chunk_target
                    (chunk_id, source_id, document_id, target_document, target_anchor)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (chunk_id, source_id, document.id, target_document, target_anchor or "")
                    for chunk_id, target_document, target_anchor in rows
                ],
            )
        await self._conn.commit()

    async def rebuild_clusters(self, source_id: str) -> int:
        async with self._conn.execute(
            """
            SELECT DISTINCT document_id, target_document
            FROM chunk_target WHERE source_id=?
            """,
            (source_id,),
        ) as cur:
            edges: list[tuple[str, str]] = [
                (row["document_id"], row["target_document"]) async for row in cur
            ]

        await self._conn.execute("DELETE FROM cluster WHERE source_id=?", (source_id,))

        mapping = await run_leiden(edges)
        if not mapping:
            await self._conn.commit()
            return 0

        await self._conn.executemany(
            """
            INSERT INTO cluster (source_id, document_id, cluster_id)
            VALUES (?, ?, ?)
            """,
            [(source_id, doc_id, cluster_id) for doc_id, cluster_id in mapping.items()],
        )
        await self._conn.commit()
        return len(set(mapping.values()))

    async def materialize_relations(self, source_id: str) -> int:
        rows: list[tuple[str, str, str, float]] = []
        rows.extend(await self._compute_same_target(source_id))
        rows.extend(await self._compute_anchor_follow(source_id))

        await self._conn.execute(
            "DELETE FROM chunk_relation WHERE source_id=?",
            (source_id,),
        )
        if rows:
            await self._conn.executemany(
                """
                INSERT INTO chunk_relation
                    (from_chunk_id, to_chunk_id, channel, weight, source_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(from_id, to_id, ch, w, source_id) for from_id, to_id, ch, w in rows],
            )
        await self._conn.commit()
        return len(rows)

    async def _compute_same_target(
        self,
        source_id: str,
    ) -> list[tuple[str, str, str, float]]:
        """Jaccard on chunks' outgoing target sets. Chunks whose `kind` is in
        `self._excluded` are not used as sources — see class docstring.
        """
        chunk_targets: dict[str, set[str]] = {}
        reverse: dict[str, set[str]] = {}
        exclude_placeholders = ",".join("?" * len(self._excluded))
        where_kind = f"AND c.kind NOT IN ({exclude_placeholders})" if self._excluded else ""
        # `where_kind` is either "" or a fixed-shape `NOT IN (?,?,...)` — the
        # only thing interpolated is the placeholder count. Values are bound
        # positionally below, so this is not an SQL-injection surface.
        async with self._conn.execute(
            f"""
            SELECT ct.chunk_id, ct.target_document
            FROM chunk_target ct
            JOIN chunk c ON c.id = ct.chunk_id
            WHERE ct.source_id = ? {where_kind}
            """,  # noqa: S608
            (source_id, *self._excluded),
        ) as cur:
            async for row in cur:
                chunk_id = row["chunk_id"]
                target_doc = row["target_document"]
                chunk_targets.setdefault(chunk_id, set()).add(target_doc)
                reverse.setdefault(target_doc, set()).add(chunk_id)

        rows: list[tuple[str, str, str, float]] = []
        for chunk_id, targets in chunk_targets.items():
            if len(targets) < _MIN_TARGETS_FOR_SAME_TARGET:
                continue
            candidates: set[str] = set()
            for target in targets:
                candidates.update(reverse.get(target, ()))
            candidates.discard(chunk_id)
            for other in candidates:
                other_targets = chunk_targets.get(other, set())
                union = targets | other_targets
                if not union:
                    continue
                jaccard = len(targets & other_targets) / len(union)
                if jaccard < _JACCARD_MIN:
                    continue
                rows.append((chunk_id, other, _SAME_TARGET_CHANNEL, jaccard))
        return rows

    async def _compute_anchor_follow(
        self,
        source_id: str,
    ) -> list[tuple[str, str, str, float]]:
        """Single JOIN chunk_target → chunk_anchor gives every (from, to) pair
        where a chunk's anchor-scoped outgoing link matches a target chunk's anchor.
        """
        async with self._conn.execute(
            """
            SELECT ct.chunk_id AS from_id, ca.chunk_id AS to_id
            FROM chunk_target ct
            JOIN chunk_anchor ca
              ON ca.document_id = ct.target_document AND ca.anchor = ct.target_anchor
            WHERE ct.source_id = ?
              AND ct.target_anchor != ''
              AND ct.chunk_id != ca.chunk_id
            """,
            (source_id,),
        ) as cur:
            return [
                (row["from_id"], row["to_id"], _ANCHOR_FOLLOW_CHANNEL, 1.0) async for row in cur
            ]


class _SqliteGraphQuery:
    """Assembles ChunkWithGraph by joining SQL graph state with blob content."""

    def __init__(self, conn: aiosqlite.Connection, chunks: ChunkStore) -> None:
        self._conn = conn
        self._chunks = chunks

    async def get_chunk(
        self,
        source_id: str,
        chunk_id: str,
    ) -> ChunkWithGraph | None:
        document_id = await self._chunk_document(source_id, chunk_id)
        if document_id is None:
            return None
        async for enriched in self.get_chunks(source_id, document_id):
            if enriched.chunk.id == chunk_id:
                return enriched
        return None

    async def get_chunks(
        self,
        source_id: str,
        document_id: str,
    ) -> AsyncIterator[ChunkWithGraph]:
        cluster_id = await self._doc_cluster(source_id, document_id)
        backlinks = await self._backlinks_for_doc(source_id, document_id)
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
        doc_id = await self._chunk_document(source_id, chunk_id)
        if doc_id is None:
            return
        cluster_id = await self._doc_cluster(source_id, doc_id)
        if cluster_id is None:
            return
        peers = await self._docs_in_cluster(source_id, cluster_id, exclude=doc_id)
        yielded = 0
        for peer_doc in peers:
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
        docs = await self._docs_in_cluster(source_id, cluster_id)
        yielded = 0
        for doc_id in docs:
            async for enriched in self.get_chunks(source_id, doc_id):
                if limit is not None and yielded >= limit:
                    return
                yield enriched
                yielded += 1

    async def _doc_cluster(self, source_id: str, document_id: str) -> int | None:
        async with self._conn.execute(
            "SELECT cluster_id FROM cluster WHERE source_id = ? AND document_id = ?",
            (source_id, document_id),
        ) as cur:
            row = await cur.fetchone()
        return row["cluster_id"] if row else None

    async def _backlinks_for_doc(
        self,
        source_id: str,
        document_id: str,
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        async with self._conn.execute(
            """
            SELECT r.from_chunk_id, r.to_chunk_id
            FROM chunk_relation r
            JOIN chunk c ON c.id = r.to_chunk_id
            WHERE r.source_id = ? AND r.channel = ? AND c.document_id = ?
            """,
            (source_id, _ANCHOR_FOLLOW_CHANNEL, document_id),
        ) as cur:
            async for row in cur:
                result.setdefault(row["to_chunk_id"], []).append(row["from_chunk_id"])
        return result

    async def _chunk_document(self, source_id: str, chunk_id: str) -> str | None:
        async with self._conn.execute(
            "SELECT document_id FROM chunk WHERE source_id = ? AND id = ?",
            (source_id, chunk_id),
        ) as cur:
            row = await cur.fetchone()
        return row["document_id"] if row else None

    async def _docs_in_cluster(
        self,
        source_id: str,
        cluster_id: int,
        *,
        exclude: str | None = None,
    ) -> list[str]:
        if exclude is None:
            query = "SELECT document_id FROM cluster WHERE source_id = ? AND cluster_id = ?"
            params: tuple[str | int, ...] = (source_id, cluster_id)
        else:
            query = """
                SELECT document_id FROM cluster
                WHERE source_id = ? AND cluster_id = ? AND document_id != ?
                """
            params = (source_id, cluster_id, exclude)
        async with self._conn.execute(query, params) as cur:
            return [row["document_id"] async for row in cur]


class SqliteStore:
    """SQLite-backed implementation of DataIndex, GraphIndex, and GraphQuery.

    `exclude_from_same_target` — chunk kinds that must not source
    `same_target` edges. Only the same_target channel is filtered;
    `anchor_follow` ignores this parameter. Default matches
    `NavigationClassifier`'s default output — see
    `plugins.store._defaults` for the shared constant.
    """

    data: _SqliteDataIndex
    graph: _SqliteGraphIndex

    def __init__(
        self,
        path: Path | str,
        *,
        exclude_from_same_target: Iterable[str] = SAME_TARGET_EXCLUDED_KINDS,
    ) -> None:
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._exclude_from_same_target = tuple(exclude_from_same_target)

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self._path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(_SCHEMA)
        await conn.commit()
        self._conn = conn
        self.data = _SqliteDataIndex(conn)
        self.graph = _SqliteGraphIndex(
            conn,
            exclude_from_same_target=self._exclude_from_same_target,
        )

    def query(self, chunks: ChunkStore) -> _SqliteGraphQuery:
        """Build a GraphQuery bound to the given ChunkStore (usually FsStore.chunks)."""
        if self._conn is None:
            msg = "SqliteStore.init() must be awaited before .query()"
            raise RuntimeError(msg)
        return _SqliteGraphQuery(self._conn, chunks)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
