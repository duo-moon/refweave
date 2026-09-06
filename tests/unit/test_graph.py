"""Tests for run_leiden — edge canonicalization + reproducibility."""

from __future__ import annotations

import pytest

from refweave.graph import run_leiden


@pytest.mark.asyncio
async def test_empty_edges_returns_empty_mapping() -> None:
    result = await run_leiden([])
    assert result == {}


@pytest.mark.asyncio
async def test_self_loops_are_dropped() -> None:
    # Only self-loops → the set of unique undirected edges is empty →
    # empty mapping, no crash.
    result = await run_leiden([("a", "a"), ("b", "b")])
    assert result == {}


@pytest.mark.asyncio
async def test_duplicate_and_reversed_edges_collapse() -> None:
    # (a,b), (b,a), (a,b) are the same undirected edge; leiden sees one.
    result = await run_leiden([("a", "b"), ("b", "a"), ("a", "b")])
    # Both endpoints assigned to some cluster.
    assert set(result.keys()) == {"a", "b"}


@pytest.mark.asyncio
async def test_covers_every_endpoint_in_input() -> None:
    edges = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
    result = await run_leiden(edges)
    assert set(result.keys()) == {"a", "b", "c", "d", "e"}


@pytest.mark.asyncio
async def test_disconnected_components_get_distinct_clusters() -> None:
    # Two triangles, no bridge between them → at least two clusters.
    edges = [
        ("a", "b"),
        ("b", "c"),
        ("a", "c"),
        ("x", "y"),
        ("y", "z"),
        ("x", "z"),
    ]
    result = await run_leiden(edges)
    # Nodes from different components must not share a cluster.
    left = {result["a"], result["b"], result["c"]}
    right = {result["x"], result["y"], result["z"]}
    assert left.isdisjoint(right)


@pytest.mark.asyncio
async def test_same_seed_produces_reproducible_partition() -> None:
    # Two triangles disconnected — the same seed must yield the same
    # cluster assignments up to relabeling. We check membership-partition
    # equality (structural), not cluster_id equality.
    edges = [
        ("a", "b"),
        ("b", "c"),
        ("a", "c"),
        ("x", "y"),
        ("y", "z"),
        ("x", "z"),
    ]
    r1 = await run_leiden(edges, seed=42)
    r2 = await run_leiden(edges, seed=42)
    partition_1 = frozenset(
        frozenset(k for k, v in r1.items() if v == cid) for cid in set(r1.values())
    )
    partition_2 = frozenset(
        frozenset(k for k, v in r2.items() if v == cid) for cid in set(r2.values())
    )
    assert partition_1 == partition_2


@pytest.mark.asyncio
async def test_cluster_ids_are_python_ints() -> None:
    # Guards against numpy int leakage from leidenalg internals.
    result = await run_leiden([("a", "b"), ("c", "d")])
    for cid in result.values():
        assert isinstance(cid, int)
        assert type(cid) is int
