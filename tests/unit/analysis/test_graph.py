"""Tests for document_graph_mermaid."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.analysis import document_graph_mermaid

if TYPE_CHECKING:
    from refweave.pipeline import Persistence
    from refweave.plugins.store import MemoryStore


@pytest.mark.asyncio
async def test_mermaid_output_starts_with_graph_directive(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id)
    assert output.startswith("graph LR\n")


@pytest.mark.asyncio
async def test_mermaid_includes_all_docs_by_default(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id)
    # Titles come through as label text.
    for title in ("Doc A", "Doc B", "Doc C", "Doc D"):
        assert title in output


@pytest.mark.asyncio
async def test_mermaid_includes_resolved_edges(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id)
    # A → B, A → C, B → C should show up as edges (using the slugified
    # node ids). External / unresolved links are excluded.
    assert "-->" in output
    lines = output.splitlines()
    edge_lines = [line.strip() for line in lines if "-->" in line]
    # Exactly the 3 resolved page edges we set up.
    assert len(edge_lines) == 3


@pytest.mark.asyncio
async def test_mermaid_applies_cluster_classdefs(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id)
    # `classDef c0 fill:...` (or similar) should appear at least once
    # because clustering was run in the fixture.
    assert "classDef" in output
    assert ":::" in output  # node → class binding syntax


@pytest.mark.asyncio
async def test_mermaid_max_nodes_collapses_into_others(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id, max_nodes=2)
    # Only top-2 nodes kept + `others` synthetic node.
    assert "others" in output


@pytest.mark.asyncio
async def test_mermaid_max_nodes_none_renders_all(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, source_id, max_nodes=None)
    # No collapse into `others` when the cap is disabled.
    assert "others" not in output
    for title in ("Doc A", "Doc B", "Doc C", "Doc D"):
        assert title in output


@pytest.mark.asyncio
async def test_mermaid_max_nodes_non_positive_raises(
    corpus: tuple[Persistence, MemoryStore],
    source_id: str,
) -> None:
    persistence, _ = corpus
    with pytest.raises(ValueError, match="pass None to disable the cap"):
        await document_graph_mermaid(persistence, source_id, max_nodes=0)
    with pytest.raises(ValueError, match="pass None to disable the cap"):
        await document_graph_mermaid(persistence, source_id, max_nodes=-1)


@pytest.mark.asyncio
async def test_mermaid_empty_source_returns_header_only(
    corpus: tuple[Persistence, MemoryStore],
) -> None:
    persistence, _ = corpus
    output = await document_graph_mermaid(persistence, "unknown-source")
    lines = output.splitlines()
    assert lines[0] == "graph LR"
    # Only header + classDef line for `cnone` — no nodes, no edges.
    assert not any("-->" in line for line in lines)
