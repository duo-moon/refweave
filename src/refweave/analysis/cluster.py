"""Cluster inspection — labels, member docs, samples, cross-cluster edges."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from refweave.model import ChunkWithGraph
    from refweave.pipeline import Persistence

_LABEL_CANDIDATES_PER_CLUSTER: Final = 3
_MAX_LABEL_LINE: Final = 60


@dataclass(frozen=True, slots=True)
class RelatedCluster:
    """Neighbour cluster with the number of document-level edges linking it."""

    cluster_id: int
    edge_count: int


@dataclass(frozen=True, slots=True)
class ClusterSummary:
    """A single Leiden community, ready to display or feed into retrieval."""

    cluster_id: int
    label: str
    doc_ids: tuple[str, ...]
    chunk_count: int
    sample_chunks: tuple[ChunkWithGraph, ...]
    related_clusters: tuple[RelatedCluster, ...]

    def __str__(self) -> str:
        header = f"# Cluster {self.cluster_id} — {self.label}\n"
        stats = (
            f"- docs: **{len(self.doc_ids)}**\n"
            f"- chunks: **{self.chunk_count}**\n"
        )
        if self.related_clusters:
            related_lines = "".join(
                f"- cluster {r.cluster_id}: {r.edge_count} edge(s)\n"
                for r in self.related_clusters
            )
            related = f"\n## Related clusters\n{related_lines}"
        else:
            related = ""
        if self.sample_chunks:
            sample_lines = "".join(
                f"- `{cwg.chunk.id}`: {cwg.chunk.text[:120].strip()}…\n"
                for cwg in self.sample_chunks
            )
            samples = f"\n## Sample chunks\n{sample_lines}"
        else:
            samples = ""
        return header + stats + related + samples


def cluster_label(chunks: Iterable[ChunkWithGraph]) -> str:
    """Derive a human-readable label from chunk first lines.

    Heuristic: take the first non-empty line of each chunk (up to
    `_MAX_LABEL_LINE` chars), count occurrences, and join the top three
    with `·`. Result is best-effort — clusters with heterogeneous
    content produce noisy labels; that is a signal to tune chunker
    rules, not to iterate label heuristics.
    """
    firsts: list[str] = []
    for cwg in chunks:
        for line in cwg.chunk.text.splitlines():
            snippet = line.strip()
            if snippet:
                firsts.append(snippet[:_MAX_LABEL_LINE])
                break
    if not firsts:
        return "(unlabelled)"
    counter = Counter(firsts)
    top = [text for text, _ in counter.most_common(_LABEL_CANDIDATES_PER_CLUSTER)]
    return " · ".join(top)


async def build_doc_cluster_map(
    persistence: Persistence,
    source_id: str,
) -> dict[str, int | None]:
    """Return a `{doc_id: cluster_id}` map for the whole source.

    Each document's cluster is taken from its first chunk. Deleted
    documents are included (with whatever cluster their remaining chunks
    carry) — filter upstream if that matters. Meant to be built once and
    reused across many `cluster_summary` calls to avoid re-scanning the
    same docs O(clusters) times.
    """
    doc_cluster: dict[str, int | None] = {}
    async for doc in persistence.documents.iter(source_id):
        cluster_for_doc: int | None = None
        async for cwg in persistence.query.get_chunks(source_id, doc.id):
            cluster_for_doc = cwg.cluster_id
            break
        doc_cluster[doc.id] = cluster_for_doc
    return doc_cluster


async def cluster_summary(
    persistence: Persistence,
    source_id: str,
    cluster_id: int,
    *,
    sample_size: int = 5,
    related_top_n: int = 5,
    doc_cluster_map: dict[str, int | None] | None = None,
) -> ClusterSummary:
    """Build a `ClusterSummary` for one cluster.

    Iterates the cluster's chunks (via `query.by_cluster`) plus each
    member doc's outgoing links (to compute `related_clusters`). O(chunks
    + doc_links) async ops.

    `sample_size` — how many chunks to include in `sample_chunks` (in
    iteration order, whatever the store returns).
    `related_top_n` — how many neighbour clusters to include (by
    edge count, descending).
    `doc_cluster_map` — precomputed `{doc_id: cluster_id}` map. When
    building many summaries in a row (e.g. `dump_analysis`), share one
    map via `build_doc_cluster_map` instead of paying O(docs) per call.
    """
    doc_ids_ordered: list[str] = []
    doc_set: set[str] = set()
    chunks_in_cluster: list[ChunkWithGraph] = []
    sample_chunks: list[ChunkWithGraph] = []
    async for cwg in persistence.query.by_cluster(source_id, cluster_id):
        chunks_in_cluster.append(cwg)
        if len(sample_chunks) < sample_size:
            sample_chunks.append(cwg)
        doc_id = cwg.chunk.document
        if doc_id not in doc_set:
            doc_set.add(doc_id)
            doc_ids_ordered.append(doc_id)

    if doc_cluster_map is None:
        doc_cluster_map = await build_doc_cluster_map(persistence, source_id)

    label = cluster_label(chunks_in_cluster)
    related = await _related_clusters(
        persistence, source_id, doc_ids_ordered, cluster_id,
        related_top_n, doc_cluster_map,
    )

    return ClusterSummary(
        cluster_id=cluster_id,
        label=label,
        doc_ids=tuple(doc_ids_ordered),
        chunk_count=len(chunks_in_cluster),
        sample_chunks=tuple(sample_chunks),
        related_clusters=related,
    )


async def _related_clusters(
    persistence: Persistence,
    source_id: str,
    member_docs: list[str],
    home_cluster: int,
    top_n: int,
    doc_cluster_map: dict[str, int | None],
) -> tuple[RelatedCluster, ...]:
    """Count outgoing resolved links from `member_docs` to docs in other clusters.

    Simple document-level projection: for each link with a resolved
    `target_document`, look up the target's cluster via `doc_cluster_map`
    and increment the (source_cluster, target_cluster) edge.
    """
    counts: Counter[int] = Counter()
    for doc_id in member_docs:
        async for link in persistence.links.get(source_id, doc_id):
            if not link.resolved or link.target_document is None:
                continue
            target_cluster = doc_cluster_map.get(link.target_document)
            if target_cluster is None or target_cluster == home_cluster:
                continue
            counts[target_cluster] += 1

    return tuple(
        RelatedCluster(cluster_id=cid, edge_count=n)
        for cid, n in counts.most_common(top_n)
    )
