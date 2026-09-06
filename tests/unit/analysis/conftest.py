"""Shared fixtures for analysis tests — a mini synced corpus in MemoryStore.

Layout:
    Docs A, B, C, D
    A → B (resolved, page)
    A → C (resolved, page)
    B → C (resolved, page)
    D →   (external)
    Chunks: 2 per doc
    Clusters: A/B → cluster 0, C/D → cluster 1 (assigned manually via
    replace_chunk_targets + rebuild_clusters, exact ids depend on Leiden
    but the mini graph is symmetric enough for stability).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio

from refweave.model import Chunk, ChunkLinkRef, Document, Link, Section, SyncState
from refweave.pipeline import Persistence
from refweave.plugins.store import MemoryStore

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_doc(external: str, title: str) -> Document:
    doc_id = f"doc:s:{external}"
    return Document(
        id=doc_id,
        title=title,
        sections=(
            Section(
                id=f"sec:s:{external}:0",
                document=doc_id,
                seq=0,
                kind="heading",
                text=title,
                raw="",
            ),
        ),
        sync=SyncState(version=1, updated_at=_NOW),
    )


def _make_link(
    src_external: str,
    seq: int,
    kind: str,
    target: str | None,
    resolved: bool,
) -> Link:
    return Link(
        id=f"lnk:s:{src_external}:0:{seq}",
        document=f"doc:s:{src_external}",
        section=f"sec:s:{src_external}:0",
        seq=seq,
        kind=kind,
        target_document=target,
        target_anchor=None,
        resolved=resolved,
        metadata={},
    )


def _make_chunk(
    external: str,
    seq: int,
    text: str,
    targets: tuple[str, ...] = (),
) -> Chunk:
    return Chunk(
        id=f"chk:s:{external}:{seq}",
        document=f"doc:s:{external}",
        seq=seq,
        text=text,
        sections=(f"sec:s:{external}:0",),
        outgoing_links=tuple(
            ChunkLinkRef(target_document=t, target_anchor=None, kind="page") for t in targets
        ),
    )


@pytest_asyncio.fixture
async def corpus() -> tuple[Persistence, MemoryStore]:
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

    docs = {
        "a": _make_doc("a", "Doc A"),
        "b": _make_doc("b", "Doc B"),
        "c": _make_doc("c", "Doc C"),
        "d": _make_doc("d", "Doc D"),
    }
    for doc in docs.values():
        await persistence.documents.put(doc)

    links = {
        "a": [
            _make_link("a", 0, "page", "doc:s:b", True),
            _make_link("a", 1, "page", "doc:s:c", True),
            _make_link("a", 2, "external", None, True),
        ],
        "b": [_make_link("b", 0, "page", "doc:s:c", True)],
        "c": [],
        "d": [_make_link("d", 0, "external", None, True)],
    }
    for external, doc_links in links.items():
        await persistence.links.put(docs[external], doc_links)

    chunks = {
        "a": [
            _make_chunk(
                "a",
                0,
                "Setup Guide\nInstall the package.",
                targets=("doc:s:b", "doc:s:c"),
            ),
            _make_chunk("a", 1, "Configuration\nEdit the file."),
        ],
        "b": [
            _make_chunk("b", 0, "Setup Guide\nMore setup steps.", targets=("doc:s:c",)),
            _make_chunk("b", 1, "Configuration\nMore config details."),
        ],
        "c": [
            _make_chunk("c", 0, "Advanced Topics\nDeep dive.", targets=()),
            _make_chunk("c", 1, "Advanced Topics\nMore depth."),
        ],
        "d": [
            _make_chunk("d", 0, "External docs reference.", targets=()),
        ],
    }
    for external, doc_chunks in chunks.items():
        await persistence.chunks.put(docs[external], doc_chunks)
        await persistence.data.replace_chunks(docs[external], doc_chunks)

    # Graph edges: chunk → target doc, so cluster grouping sees the link fabric.
    for external, doc_chunks in chunks.items():
        rows: list[tuple[str, str, str | None]] = [
            (chunk.id, link_ref.target_document, None)
            for chunk in doc_chunks
            for link_ref in chunk.outgoing_links
            if link_ref.target_document is not None
        ]
        await persistence.graph.replace_chunk_targets(docs[external], rows)

    await persistence.graph.rebuild_clusters("s")
    await persistence.graph.materialize_relations("s")

    return persistence, store


@pytest.fixture
def source_id() -> str:
    return "s"
