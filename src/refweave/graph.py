"""Graph algorithms used across the pipeline.

CPU-bound work is offloaded to a ProcessPoolExecutor so the event loop
stays responsive.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Executor, ProcessPoolExecutor
from typing import TYPE_CHECKING

import igraph  # type: ignore[import-untyped]
import leidenalg  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable


async def run_leiden(
    edges: Iterable[tuple[str, str]],
    *,
    seed: int = 42,
    executor: Executor | None = None,
) -> dict[str, int]:
    """Return a node → cluster_id mapping via Leiden community detection.

    Edges are treated as undirected; self-loops and duplicates are dropped.
    Every node must appear as an endpoint in at least one edge — isolated
    nodes are not representable through this API.

    Disconnected components each get their own cluster (or set of clusters);
    the returned mapping covers every node found in `edges`.

    Returns an empty mapping if the edge set is empty.

    `seed` fixes the RNG for reproducible partitioning. Edges are sorted
    before dispatch so vertex numbering inside the worker process is
    deterministic across runs — necessary for `seed` to actually produce
    reproducible output when the executor spins up a fresh process.

    `executor`, when passed, is reused across calls (avoids per-call process
    startup). If omitted, a one-off `ProcessPoolExecutor(max_workers=1)` is
    spun up per call — fine for one-shot rebuilds, wasteful in a loop.
    """
    unique: set[tuple[str, str]] = set()
    for a, b in edges:
        if a == b:
            continue
        lo, hi = sorted((a, b))
        unique.add((lo, hi))

    if not unique:
        return {}

    canonical = sorted(unique)
    loop = asyncio.get_running_loop()
    if executor is not None:
        return await loop.run_in_executor(executor, _leiden_sync, canonical, seed)

    with ProcessPoolExecutor(max_workers=1) as ex:
        return await loop.run_in_executor(ex, _leiden_sync, canonical, seed)


def _leiden_sync(edges: list[tuple[str, str]], seed: int) -> dict[str, int]:
    """Runs inside a worker process."""
    node_index: dict[str, int] = {}
    for a, b in edges:
        node_index.setdefault(a, len(node_index))
        node_index.setdefault(b, len(node_index))

    idx_edges = [(node_index[a], node_index[b]) for a, b in edges]

    graph = igraph.Graph(n=len(node_index), edges=idx_edges, directed=False)
    partition = leidenalg.find_partition(
        graph,
        leidenalg.ModularityVertexPartition,
        seed=seed,
    )
    membership = partition.membership
    return {node: int(membership[i]) for node, i in node_index.items()}
