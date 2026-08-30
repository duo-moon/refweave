"""Tests for PolicyChunker overlap_chars — prepending prev-chunk tail."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from refweave.model import Document, Section, SyncState
from refweave.plugins.chunker import Policy, PolicyChunker, SizeLimitRule

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


def test_negative_overlap_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        PolicyChunker(policy=Policy([]), overlap_chars=-1)


def test_zero_overlap_leaves_text_unchanged() -> None:
    doc = _doc(_sec(0, "AAA" * 100), _sec(1, "BBB" * 100))
    chunker = PolicyChunker(
        policy=Policy([SizeLimitRule(max_chars=200)]),
        overlap_chars=0,
    )
    chunks = list(chunker.chunk(doc, ()))
    assert len(chunks) == 2
    assert chunks[0].text.startswith("AAA")
    # No prefix from prev chunk when overlap is off.
    assert chunks[1].text.startswith("BBB")


def test_positive_overlap_prepends_prev_tail_to_next_chunk() -> None:
    doc = _doc(_sec(0, "AAA" * 100), _sec(1, "BBB" * 100))
    chunker = PolicyChunker(
        policy=Policy([SizeLimitRule(max_chars=200)]),
        overlap_chars=20,
    )
    chunks = list(chunker.chunk(doc, ()))
    assert len(chunks) == 2
    # Second chunk should carry the last 20 chars of the first chunk's text
    # as its own prefix (separated by "\n\n").
    prev_tail = chunks[0].text[-20:]
    assert chunks[1].text.startswith(prev_tail)


def test_overlap_does_not_appear_in_first_chunk() -> None:
    doc = _doc(_sec(0, "AAA" * 100), _sec(1, "BBB" * 100))
    chunker = PolicyChunker(
        policy=Policy([SizeLimitRule(max_chars=200)]),
        overlap_chars=20,
    )
    chunks = list(chunker.chunk(doc, ()))
    # First chunk has no prior tail, so nothing prepended.
    assert not chunks[0].text.startswith("\n\n")
    assert chunks[0].text.startswith("AAA")


def test_sections_tuple_unaffected_by_overlap() -> None:
    doc = _doc(_sec(0, "AAA" * 100), _sec(1, "BBB" * 100))
    chunker = PolicyChunker(
        policy=Policy([SizeLimitRule(max_chars=200)]),
        overlap_chars=20,
    )
    chunks = list(chunker.chunk(doc, ()))
    # Overlap only affects `text`; `sections` still reflects buffered content.
    assert chunks[0].sections == ("sec:s:doc:0",)
    assert chunks[1].sections == ("sec:s:doc:1",)


def test_single_chunk_document_has_no_overlap() -> None:
    doc = _doc(_sec(0, "Small body."))
    chunker = PolicyChunker(
        policy=Policy([SizeLimitRule(max_chars=4000)]),
        overlap_chars=50,
    )
    chunks = list(chunker.chunk(doc, ()))
    assert len(chunks) == 1
    assert chunks[0].text == "Small body."
