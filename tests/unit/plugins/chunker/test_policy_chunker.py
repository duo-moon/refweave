"""PolicyChunker: buffer-driven chunk emission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Chunk, Document, Link, Section, SyncState
from refweave.plugins.chunker import (
    ChunkContext,
    Decision,
    HeadingRule,
    Policy,
    PolicyChunker,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _sec(seq: int, kind: str = "paragraph", text: str = "") -> Section:
    return Section(
        id=f"sec:src:1:{seq}",
        document="doc:src:1",
        seq=seq,
        kind=kind,
        text=text or f"section {seq}",
    )


def _doc(sections: Sequence[Section]) -> Document:
    return Document(
        id="doc:src:1",
        title="Test",
        sections=tuple(sections),
        sync=SyncState(version=1, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
    )


class _AlwaysMerge:
    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del curr, buffer, ctx
        return Decision.MERGE


def _collect(
    chunker: PolicyChunker,
    doc: Document,
    links: Sequence[Link] = (),
) -> list[Chunk]:
    return list(chunker.chunk(doc, links))


def test_empty_document_yields_no_chunks() -> None:
    chunker = PolicyChunker(policy=Policy([HeadingRule()]))
    chunks = _collect(chunker, _doc([]))
    assert chunks == []


def test_single_section_yields_one_chunk() -> None:
    chunker = PolicyChunker(policy=Policy([HeadingRule()]))
    chunks = _collect(chunker, _doc([_sec(0, text="only")]))
    assert len(chunks) == 1
    assert chunks[0].sections == ("sec:src:1:0",)
    assert chunks[0].text == "only"


def test_always_merge_produces_one_chunk() -> None:
    chunker = PolicyChunker(policy=Policy([_AlwaysMerge()]))
    doc = _doc([_sec(0, text="a"), _sec(1, text="b"), _sec(2, text="c")])
    chunks = _collect(chunker, doc)
    assert len(chunks) == 1
    assert chunks[0].sections == ("sec:src:1:0", "sec:src:1:1", "sec:src:1:2")
    assert chunks[0].text == "a\n\nb\n\nc"


def test_heading_split() -> None:
    chunker = PolicyChunker(policy=Policy([HeadingRule()]))
    doc = _doc(
        [
            _sec(0, kind="heading", text="H1"),
            _sec(1, text="para1"),
            _sec(2, kind="heading", text="H2"),
            _sec(3, text="para2"),
        ],
    )
    chunks = _collect(chunker, doc)
    assert [c.sections for c in chunks] == [
        ("sec:src:1:0", "sec:src:1:1"),
        ("sec:src:1:2", "sec:src:1:3"),
    ]
    assert [c.seq for c in chunks] == [0, 1]


def test_chunk_ids_follow_convention() -> None:
    chunker = PolicyChunker(policy=Policy([HeadingRule()]))
    doc = _doc([_sec(0, kind="heading", text="H"), _sec(1, text="p")])
    chunks = _collect(chunker, doc)
    assert chunks[0].id == "chk:src:1:0"


def test_outgoing_links_from_matching_sections() -> None:
    chunker = PolicyChunker(policy=Policy([HeadingRule()]))
    doc = _doc(
        [
            _sec(0, kind="heading", text="H"),
            _sec(1, text="p"),
            _sec(2, kind="heading", text="H2"),
        ],
    )
    links = [
        Link(
            id="lnk:src:1:1:0",
            document="doc:src:1",
            section="sec:src:1:1",
            seq=0,
            kind="page",
            target_document="doc:src:99",
        ),
        Link(
            id="lnk:src:1:0:0",
            document="doc:src:1",
            section="sec:src:1:0",
            seq=0,
            kind="external",
            target_document=None,
            metadata={"url": "https://example.com"},
        ),
    ]
    chunks = _collect(chunker, doc, links)
    # first chunk = sections 0+1, second chunk = section 2
    first_refs = [r.target_document for r in chunks[0].outgoing_links]
    assert set(first_refs) == {"doc:src:99", None}
    assert chunks[1].outgoing_links == ()


def test_classifier_sets_chunk_kind() -> None:
    def classify(sections: Sequence[Section], ctx: ChunkContext) -> str | None:
        del sections, ctx
        return "custom"

    chunker = PolicyChunker(policy=Policy([_AlwaysMerge()]), classifier=classify)
    chunks = _collect(chunker, _doc([_sec(0), _sec(1)]))
    assert chunks[0].kind == "custom"


def test_classifier_returning_none_keeps_default_kind() -> None:
    def classify(sections: Sequence[Section], ctx: ChunkContext) -> str | None:
        del sections, ctx
        return None

    chunker = PolicyChunker(policy=Policy([_AlwaysMerge()]), classifier=classify)
    chunks = _collect(chunker, _doc([_sec(0)]))
    assert chunks[0].kind == "generic"


def test_classifier_receives_document_via_ctx() -> None:
    captured: list[str] = []

    def classify(sections: Sequence[Section], ctx: ChunkContext) -> str | None:
        del sections
        captured.append(ctx.document.id)
        return None

    chunker = PolicyChunker(policy=Policy([_AlwaysMerge()]), classifier=classify)
    _collect(chunker, _doc([_sec(0), _sec(1)]))
    assert captured == ["doc:src:1"]


def test_text_separator_configurable() -> None:
    chunker = PolicyChunker(policy=Policy([_AlwaysMerge()]), text_separator=" | ")
    chunks = _collect(chunker, _doc([_sec(0, text="a"), _sec(1, text="b")]))
    assert chunks[0].text == "a | b"


@pytest.mark.parametrize("bad_id", ["not-a-doc-id", "sec:src:1", "doc"])
def test_invalid_document_id_raises(bad_id: str) -> None:
    chunker = PolicyChunker(policy=Policy([]))
    doc = Document(
        id=bad_id,
        title="x",
        sections=(Section(id="sec:x:x:0", document=bad_id, seq=0, kind="paragraph", text="a"),),
        sync=SyncState(version=1, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="invalid document id"):
        _collect(chunker, doc)
