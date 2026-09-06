"""Tests for cluster_summary + cluster_label."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.analysis import cluster_label, cluster_summary, corpus_report

if TYPE_CHECKING:
    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_cluster_summary_populates_docs_and_chunks(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    # Discover an actual cluster id via the report.
    report = await corpus_report(persistence, source_id)
    assert report.top_clusters
    top = report.top_clusters[0]
    summary = await cluster_summary(persistence, source_id, top.cluster_id)
    assert summary.cluster_id == top.cluster_id
    assert summary.chunk_count == top.chunk_count
    assert len(summary.doc_ids) == top.doc_count
    assert summary.doc_ids  # not empty


@pytest.mark.asyncio
async def test_cluster_summary_respects_sample_size(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    top = report.top_clusters[0]
    summary = await cluster_summary(persistence, source_id, top.cluster_id, sample_size=2)
    assert len(summary.sample_chunks) <= 2


@pytest.mark.asyncio
async def test_cluster_summary_str_renders_markdown(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    report = await corpus_report(persistence, source_id)
    top = report.top_clusters[0]
    summary = await cluster_summary(persistence, source_id, top.cluster_id)
    md = str(summary)
    assert md.startswith(f"# Cluster {top.cluster_id}")
    assert "docs:" in md
    assert "chunks:" in md


@pytest.mark.asyncio
async def test_cluster_summary_unknown_cluster_returns_empty(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    summary = await cluster_summary(persistence, source_id, cluster_id=9_999)
    assert summary.chunk_count == 0
    assert summary.doc_ids == ()
    assert summary.sample_chunks == ()
    assert summary.related_clusters == ()
    assert summary.label == "(unlabelled)"


def test_cluster_label_from_repeating_first_lines() -> None:
    """Chunks whose first line repeats produce that line as the label."""
    from refweave.model import Chunk, ChunkWithGraph

    def _cwg(text: str) -> ChunkWithGraph:
        chunk = Chunk(
            id="chk:s:x:0",
            document="doc:s:x",
            seq=0,
            text=text,
            sections=(),
        )
        return ChunkWithGraph(chunk=chunk, cluster_id=1, incoming_anchor_from=())

    label = cluster_label(
        [
            _cwg("Setup Guide\nBody 1"),
            _cwg("Setup Guide\nBody 2"),
            _cwg("Advanced Topics\nBody 3"),
        ]
    )
    # Top 2 distinct → both surface. Order preserved by Counter.most_common.
    assert "Setup Guide" in label
    assert "Advanced Topics" in label


def test_cluster_label_empty_chunks_returns_placeholder() -> None:
    assert cluster_label([]) == "(unlabelled)"
