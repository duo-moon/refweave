"""Tests for corpus_report."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.analysis import corpus_report

if TYPE_CHECKING:
    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_report_counts_docs_chunks(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    assert report.docs_total == 4
    # Doc D has 1 chunk, others have 2 → 7 total.
    assert report.chunks_total == 7


@pytest.mark.asyncio
async def test_report_link_kinds(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    # A: 2 page + 1 external, B: 1 page, D: 1 external.
    assert report.links_by_kind == {"page": 3, "external": 2}
    assert report.resolved_links == 3  # a→b, a→c, b→c
    # External links carry resolved=True + target_document=None — same
    # signature as dead-internal, both counted here.
    assert report.resolved_no_target == 2
    assert report.unresolved_links == 0


@pytest.mark.asyncio
async def test_report_chunks_per_doc_stats(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    assert report.chunks_per_doc.min == 1  # Doc D
    assert report.chunks_per_doc.max == 2
    assert report.chunks_per_doc.mean == pytest.approx(7 / 4)


@pytest.mark.asyncio
async def test_report_clusters_detected(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    # Leiden on this mini graph produces at least one cluster.
    assert report.clusters_total >= 1
    assert report.top_clusters  # non-empty


@pytest.mark.asyncio
async def test_report_str_renders_markdown(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    md = str(report)
    assert md.startswith("# Corpus report — `s`")
    assert "chunks:" in md
    assert "Chunks per document" in md


@pytest.mark.asyncio
async def test_report_empty_source_returns_zero_counts(
    corpus: tuple[Persistence, MemoryStore],
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, "unknown-source")
    assert report.docs_total == 0
    assert report.chunks_total == 0
    assert report.top_clusters == ()
    assert report.chunks_per_doc.min == 0
