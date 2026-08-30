"""Orchestration pipelines: sync, rechunk, recompute_clusters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from refweave.model import Document
    from refweave.pipeline.chunker import Chunker
    from refweave.pipeline.persistence import DocumentState, Persistence
    from refweave.pipeline.resolver import Resolver
    from refweave.pipeline.source import Source


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Per-document outcome counts for one `sync` invocation.

    `created` — docs whose id was not present in the store before this run.
    `updated` — docs whose `sync.version` changed vs. the stored snapshot.
    `skipped` — docs whose `sync.version` matched — nothing re-fetched or
                re-chunked.
    `deleted` — previously-live docs the source no longer yields; a
                tombstone is written and links/chunks are wiped.
    `resurrected` — docs the store had tombstoned but the source now yields
                    again; `deleted_at` is cleared and the doc is re-chunked.

    Sanity check: `created + updated + skipped + resurrected` equals the
    number of docs source produced this run.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    resurrected: int = 0


@dataclass(frozen=True, slots=True)
class RechunkReport:
    """Result of one `rechunk` invocation.

    `rechunked` — number of live (non-deleted) docs whose chunks were
    rebuilt. `rechunk` does not touch docs, links, or graph relations —
    just chunks — so this is the only counter needed.
    """

    rechunked: int = 0


@dataclass(frozen=True, slots=True)
class ClusterReport:
    """Result of one `recompute_clusters` invocation.

    `clusters` — number of distinct Leiden communities produced. Zero
    means the corpus had no chunk-to-chunk edges (empty graph); the
    clustering pass is a no-op in that case.
    """

    clusters: int = 0


async def sync(
    source: Source,
    chunker: Chunker,
    persistence: Persistence,
    resolver: Resolver | None = None,
) -> SyncReport:
    """Full sync: pull from source, resolve, chunk, tombstone, materialize.

    Phases:
        1. Pull  — iterate source, persist docs and unresolved links.
                   Docs whose stored `sync.version` matches are skipped.
        2. Resolve (optional) — resolver fills `target_document` on
                   cross-doc links.
        3. Chunk — re-chunk only docs touched in phase 1. Skipped docs
                   keep their previously stored chunks. Trigger a full
                   `rechunk(source_id, ...)` to refresh chunks whose
                   resolutions changed while the doc itself did not.
        4. Tombstone — mark existing docs that source no longer yields
                   with `deleted_at=now` and wipe their links/chunks.
        5. Materialize — rebuild chunk-to-chunk graph relations.

    Returns counters: created / updated / skipped / deleted / resurrected.
    """
    graph_version = await persistence.data.bump_graph_version(source.source_id)

    existing: dict[str, DocumentState] = {}
    async for row in persistence.data.iter(source.source_id):
        existing[row.id] = row
    seen: set[str] = set()
    touched: set[str] = set()
    created = updated = skipped = resurrected = 0

    # Phase 1: pull + persist docs and unresolved links.
    async for item in source.iter():
        doc = item.document
        seen.add(doc.id)
        stored = existing.get(doc.id)

        if stored is not None and stored.version == doc.sync.version and stored.deleted_at is None:
            skipped += 1
            continue

        doc = _stamp_graph_version(doc, graph_version)
        await persistence.save_document(doc)
        await persistence.save_links(doc, item.links)
        touched.add(doc.id)

        if stored is None:
            created += 1
        elif stored.deleted_at is not None:
            resurrected += 1
        else:
            updated += 1

    # Phase 2: resolve links (fills target_document for cross-doc refs).
    if resolver is not None:
        await _resolve_all(persistence, source.source_id, resolver)

    # Phase 3: chunk touched docs with resolved links.
    for doc_id in touched:
        stored_doc = await persistence.documents.get(source.source_id, doc_id)
        if stored_doc is None:
            continue
        links = [link async for link in persistence.links.get(source.source_id, doc_id)]
        chunks = list(chunker.chunk(stored_doc, links))
        await persistence.save_chunks(stored_doc, chunks)

    # Phase 4: tombstone missing.
    deleted = await _tombstone_missing(persistence, source.source_id, existing, seen)

    # Phase 5: materialize chunk-to-chunk relations.
    await persistence.graph.materialize_relations(source.source_id)

    return SyncReport(
        created=created,
        updated=updated,
        skipped=skipped,
        deleted=deleted,
        resurrected=resurrected,
    )


async def rechunk(
    source_id: str,
    chunker: Chunker,
    persistence: Persistence,
) -> RechunkReport:
    """Re-chunk every live document from persisted docs+links.

    Uses persisted links as-is — no resolver re-run. Call after changing
    chunker policy, or to refresh chunks whose resolutions changed since
    the last `sync`. Bumps `graph_version` and materializes relations at
    the end.
    """
    graph_version = await persistence.data.bump_graph_version(source_id)
    count = 0
    async for stored in persistence.documents.iter(source_id):
        if stored.sync.deleted_at is not None:
            continue
        doc = _stamp_graph_version(stored, graph_version)
        links = [link async for link in persistence.links.get(source_id, doc.id)]
        chunks = list(chunker.chunk(doc, links))
        await persistence.save_chunks(doc, chunks)
        count += 1
    await persistence.graph.materialize_relations(source_id)
    return RechunkReport(rechunked=count)


async def recompute_clusters(source_id: str, persistence: Persistence) -> ClusterReport:
    """Recompute chunk-to-cluster assignments for one source.

    Runs the graph clustering algorithm over the currently persisted
    chunk-target edges. Prior cluster assignments are replaced (no history).
    """
    clusters = await persistence.graph.rebuild_clusters(source_id)
    return ClusterReport(clusters=clusters)


def _stamp_graph_version(doc: Document, graph_version: int) -> Document:
    return doc.model_copy(update={"graph_version": graph_version})


async def _resolve_all(
    persistence: Persistence,
    source_id: str,
    resolver: Resolver,
) -> None:
    """Drive the resolver: prepare with all docs, then resolve per doc.

    Iterates docs twice — once for prepare (context build), once for
    per-doc resolution. Skips tombstoned docs.
    """
    await resolver.prepare(persistence.documents.iter(source_id))
    async for doc in persistence.documents.iter(source_id):
        if doc.sync.deleted_at is not None:
            continue
        links = [link async for link in persistence.links.get(source_id, doc.id)]
        updated = resolver.resolve(doc, links)
        if updated is not links:
            await persistence.save_links(doc, updated)


async def _tombstone_missing(
    persistence: Persistence,
    source_id: str,
    existing: dict[str, DocumentState],
    seen: set[str],
) -> int:
    """Mark docs that were in the index but not yielded this sync.

    Sets `deleted_at=now` and wipes links/chunks so the graph pipeline
    doesn't see ghost data.
    """
    now = datetime.now(tz=UTC)
    deleted = 0
    for doc_id, row in existing.items():
        if doc_id in seen or row.deleted_at is not None:
            continue
        stored = await persistence.documents.get(source_id, doc_id)
        if stored is None:
            continue
        tombstoned = stored.model_copy(
            update={"sync": stored.sync.model_copy(update={"deleted_at": now})},
        )
        await persistence.save_document(tombstoned)
        await persistence.save_links(tombstoned, [])
        await persistence.save_chunks(tombstoned, [])
        deleted += 1
    return deleted
