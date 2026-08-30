"""Contract snapshot for the domain model.

Freezes public field names + defaults so unintended shape changes fail
loudly. Pydantic itself validates types — we only touch the surface a
plugin actually depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from refweave.model import (
    Chunk,
    ChunkLinkRef,
    ChunkWithGraph,
    Document,
    Link,
    Section,
    SyncState,
)


def test_section_defaults() -> None:
    s = Section(id="sec:src:1:0", document="doc:src:1", seq=0, kind="paragraph", text="hi")
    assert s.raw == ""
    assert s.metadata == {}


def test_link_defaults() -> None:
    link = Link(
        id="lnk:src:1:0:0",
        document="doc:src:1",
        section="sec:src:1:0",
        seq=0,
        kind="page",
    )
    assert link.target_document is None
    assert link.target_anchor is None
    assert link.resolved is False
    assert link.metadata == {}


def test_chunk_defaults() -> None:
    ch = Chunk(id="chk:src:1:0", document="doc:src:1", seq=0, text="body")
    assert ch.kind == "generic"
    assert ch.sections == ()
    assert ch.outgoing_links == ()
    assert ch.metadata == {}


def test_document_defaults_and_composition() -> None:
    doc = Document(
        id="doc:src:1",
        title="Page",
        sync=SyncState(version=1, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    assert doc.kind == "generic"
    assert doc.sections == ()
    assert doc.metadata == {}
    assert doc.sync.deleted_at is None
    assert doc.graph_version == 0


def test_chunk_with_graph_projection() -> None:
    chunk = Chunk(id="chk:src:1:0", document="doc:src:1", seq=0, text="body")
    enriched = ChunkWithGraph(
        chunk=chunk,
        cluster_id=42,
        incoming_anchor_from=("chk:src:2:0",),
    )
    assert enriched.chunk is chunk
    assert enriched.cluster_id == 42
    assert enriched.incoming_anchor_from == ("chk:src:2:0",)


def test_chunk_link_ref_requires_kind() -> None:
    ref = ChunkLinkRef(kind="page")
    assert ref.target_document is None
    assert ref.target_anchor is None
    assert ref.kind == "page"
