"""Tests for export_jsonl."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from refweave.analysis import export_jsonl

if TYPE_CHECKING:
    from pathlib import Path

    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_export_writes_one_line_per_chunk(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    path = tmp_path / "chunks.jsonl"
    count = await export_jsonl(persistence, source_id, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == count == 7  # 2+2+2+1 chunks


@pytest.mark.asyncio
async def test_export_record_shape(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    path = tmp_path / "chunks.jsonl"
    await export_jsonl(persistence, source_id, path)
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    for key in (
        "id",
        "document",
        "document_title",
        "seq",
        "kind",
        "text",
        "sections",
        "outgoing_links",
        "metadata",
        "cluster_id",
        "incoming_anchor_from",
    ):
        assert key in first, key


@pytest.mark.asyncio
async def test_export_creates_parent_dir(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    path = tmp_path / "nested" / "deeper" / "chunks.jsonl"
    await export_jsonl(persistence, source_id, path)
    assert path.exists()


@pytest.mark.asyncio
async def test_export_empty_source_writes_empty_file(
    corpus: tuple[Persistence, MemoryStore],
    tmp_path: Path,
) -> None:
    persistence, _ = corpus
    path = tmp_path / "chunks.jsonl"
    count = await export_jsonl(persistence, "unknown", path)
    assert count == 0
    assert path.read_text() == ""
