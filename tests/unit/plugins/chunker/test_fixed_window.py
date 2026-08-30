"""Tests for FixedWindowChunker — baseline chunker semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from refweave.model import Document, Link, Section, SyncState
from refweave.plugins.chunker import FixedWindowChunker

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _sec(seq: int, text: str, kind: str = "paragraph") -> Section:
    return Section(
        id=f"sec:s:doc:{seq}",
        document="doc:s:doc",
        seq=seq,
        kind=kind,
        text=text,
        raw="",
    )


def _doc(*sections: Section) -> Document:
    return Document(
        id="doc:s:doc",
        title="Doc",
        sections=sections,
        sync=SyncState(version=1, updated_at=_NOW),
    )


def test_empty_document_yields_no_chunks() -> None:
    chunks = list(FixedWindowChunker().chunk(_doc(), ()))
    assert chunks == []


def test_document_with_only_empty_sections_yields_no_chunks() -> None:
    chunks = list(FixedWindowChunker().chunk(_doc(_sec(0, "")), ()))
    assert chunks == []


def test_single_short_section_yields_one_chunk() -> None:
    doc = _doc(_sec(0, "Hello world."))
    chunks = list(FixedWindowChunker(chunk_size=100).chunk(doc, ()))
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].sections == ("sec:s:doc:0",)


def test_long_text_split_across_multiple_chunks() -> None:
    text = "x" * 250
    doc = _doc(_sec(0, text))
    chunks = list(FixedWindowChunker(chunk_size=100).chunk(doc, ()))
    assert len(chunks) == 3
    assert "".join(c.text for c in chunks) == text
    assert [c.seq for c in chunks] == [0, 1, 2]


def test_overlap_reproduces_end_of_previous_chunk() -> None:
    text = "abcdefghij" * 30  # 300 chars
    doc = _doc(_sec(0, text))
    chunks = list(FixedWindowChunker(chunk_size=100, overlap=20).chunk(doc, ()))
    # Verify overlap: second chunk should start where first chunk (partially) ended.
    assert chunks[1].text.startswith(chunks[0].text[-20:])


def test_window_step_size_accounts_for_overlap() -> None:
    text = "x" * 250
    doc = _doc(_sec(0, text))
    chunks = list(FixedWindowChunker(chunk_size=100, overlap=25).chunk(doc, ()))
    # Step = chunk_size - overlap = 75. Windows: [0,100), [75,175), [150,250)
    # — 3 chunks; the third one lands on end-of-text and we break.
    assert len(chunks) == 3


def test_invalid_overlap_raises() -> None:
    with pytest.raises(ValueError, match="overlap must satisfy"):
        FixedWindowChunker(chunk_size=100, overlap=100)
    with pytest.raises(ValueError, match="overlap must satisfy"):
        FixedWindowChunker(chunk_size=100, overlap=-1)


def test_chunk_reports_all_sections_it_overlapped() -> None:
    doc = _doc(_sec(0, "AAAA"), _sec(1, "BBBB"), _sec(2, "CCCC"))
    # Full text: "AAAA\n\nBBBB\n\nCCCC" = 16 chars.
    chunks = list(FixedWindowChunker(chunk_size=8).chunk(doc, ()))
    # First 8 chars = "AAAA\n\nBB" — covers sections 0 and 1.
    assert chunks[0].sections == ("sec:s:doc:0", "sec:s:doc:1")


def test_outgoing_links_inherited_from_covered_sections() -> None:
    doc = _doc(_sec(0, "AAAA"), _sec(1, "BBBB"))
    links = [
        Link(
            id="lnk:s:doc:0:0",
            document="doc:s:doc",
            section="sec:s:doc:0",
            seq=0,
            kind="page",
            target_document="doc:s:target",
            target_anchor=None,
            resolved=True,
            metadata={},
        ),
    ]
    chunks = list(FixedWindowChunker(chunk_size=100).chunk(doc, links))
    assert len(chunks[0].outgoing_links) == 1
    assert chunks[0].outgoing_links[0].target_document == "doc:s:target"


def test_chunk_ids_use_document_external() -> None:
    doc = _doc(_sec(0, "Body."))
    chunks = list(FixedWindowChunker().chunk(doc, ()))
    assert chunks[0].id == "chk:s:doc:0"
