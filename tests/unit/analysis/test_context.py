"""Tests for chunk_with_context."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.analysis import chunk_with_context

if TYPE_CHECKING:
    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_context_returns_center_before_after(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    # Doc A has chunks with seq 0 and 1; ask for chunk 0 with after=1.
    ctx = await chunk_with_context(
        persistence, source_id, "chk:s:a:0", before=1, after=1,
    )
    assert ctx is not None
    assert ctx.center.id == "chk:s:a:0"
    assert ctx.before == ()  # no prior sibling
    assert len(ctx.after) == 1
    assert ctx.after[0].id == "chk:s:a:1"


@pytest.mark.asyncio
async def test_context_clips_at_document_boundary(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    ctx = await chunk_with_context(
        persistence, source_id, "chk:s:d:0", before=5, after=5,
    )
    assert ctx is not None
    assert ctx.before == ()
    assert ctx.after == ()  # Doc D has only one chunk


@pytest.mark.asyncio
async def test_context_concatenated_joins_texts(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    ctx = await chunk_with_context(
        persistence, source_id, "chk:s:a:1", before=1, after=0,
    )
    assert ctx is not None
    text = ctx.concatenated(sep="\n---\n")
    # Prior chunk text + separator + center text.
    assert "Setup Guide" in text
    assert "Configuration" in text
    assert "\n---\n" in text


@pytest.mark.asyncio
async def test_context_missing_chunk_returns_none(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    ctx = await chunk_with_context(persistence, source_id, "chk:s:x:99")
    assert ctx is None


@pytest.mark.asyncio
async def test_context_rejects_negative_bounds(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    with pytest.raises(ValueError, match="non-negative"):
        await chunk_with_context(
            persistence, source_id, "chk:s:a:0", before=-1,
        )
