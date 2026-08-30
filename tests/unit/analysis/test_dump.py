"""Tests for dump_analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.analysis import dump_analysis

if TYPE_CHECKING:
    from pathlib import Path

    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_dump_writes_all_top_level_files(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    result = await dump_analysis(persistence, source_id, tmp_path / "out")
    assert result.report_path.exists()
    assert result.graph_path.exists()
    assert result.chunks_path.exists()
    assert (tmp_path / "out" / "README.md").exists()


@pytest.mark.asyncio
async def test_dump_writes_one_file_per_top_cluster(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    result = await dump_analysis(persistence, source_id, tmp_path / "out")
    for path in result.cluster_paths:
        assert path.exists()
        assert path.name.startswith("cluster-")
        assert path.parent.name == "clusters"


@pytest.mark.asyncio
async def test_dump_index_lists_cluster_files(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    result = await dump_analysis(persistence, source_id, tmp_path / "out")
    index = (tmp_path / "out" / "README.md").read_text()
    assert "report.md" in index
    assert "graph.mmd" in index
    assert "chunks.jsonl" in index
    for path in result.cluster_paths:
        assert path.name in index


@pytest.mark.asyncio
async def test_dump_creates_directory(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    out = tmp_path / "brand-new-dir"
    assert not out.exists()
    await dump_analysis(persistence, source_id, out)
    assert out.is_dir()
    assert (out / "clusters").is_dir()
