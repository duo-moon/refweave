"""One-call corpus summary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from refweave.pipeline import Persistence


@dataclass(frozen=True, slots=True)
class ChunksPerDoc:
    """Distribution of chunk count per document."""

    min: int
    max: int
    mean: float


@dataclass(frozen=True, slots=True)
class TopCluster:
    """One entry in `CorpusReport.top_clusters`."""

    cluster_id: int
    doc_count: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class CorpusReport:
    """Summary counts + histograms for a synced source.

    Rendered via `str(report)` as Markdown suitable for stdout, notebooks,
    or copying into an issue.
    """

    source_id: str
    docs_total: int
    chunks_total: int
    clusters_total: int  # excludes unclustered docs
    unclustered_docs: int
    links_by_kind: dict[str, int]
    resolved_links: int  # resolved=True, target_document is not None
    resolved_no_target: int  # resolved=True, target_document=None (externals + dead-internal)
    unresolved_links: int
    chunks_per_doc: ChunksPerDoc
    top_clusters: tuple[TopCluster, ...]

    def __str__(self) -> str:
        header = f"# Corpus report — `{self.source_id}`\n"
        counts = (
            f"- docs: **{self.docs_total}**\n"
            f"- chunks: **{self.chunks_total}**\n"
            f"- clusters: **{self.clusters_total}** "
            f"(unclustered docs: {self.unclustered_docs})\n"
        )
        chunks_hist = (
            f"\n## Chunks per document\n"
            f"- min: {self.chunks_per_doc.min}\n"
            f"- max: {self.chunks_per_doc.max}\n"
            f"- mean: {self.chunks_per_doc.mean:.1f}\n"
        )
        link_lines = "".join(
            f"- {kind}: {count}\n"
            for kind, count in sorted(self.links_by_kind.items(), key=lambda kv: -kv[1])
        )
        link_stats = (
            f"\n## Links\n"
            f"{link_lines}"
            f"- resolved to doc: **{self.resolved_links}**\n"
            f"- resolved without target (external + dead-internal): **{self.resolved_no_target}**\n"
            f"- unresolved (no resolver pass): {self.unresolved_links}\n"
        )
        if self.top_clusters:
            top_lines = "".join(
                f"- cluster {c.cluster_id}: {c.doc_count} docs, {c.chunk_count} chunks\n"
                for c in self.top_clusters
            )
            clusters_section = f"\n## Top clusters (by chunk count)\n{top_lines}"
        else:
            clusters_section = (
                "\n## Top clusters\n"
                "_no clusters — run `recompute_clusters` after sync._\n"
            )
        return header + counts + chunks_hist + link_stats + clusters_section


async def corpus_report(
    persistence: Persistence,
    source_id: str,
    *,
    top_n: int = 10,
) -> CorpusReport:
    """Walk the corpus once and return a summary snapshot.

    Iterates all documents, chunks, and links for `source_id` — cost is
    O(docs + chunks + links) async ops. On a 1000-doc / 5000-chunk /
    10000-link corpus that's ~30K roundtrips against MemoryStore
    (fractional seconds) or ~a few seconds against SQLite. Meant to be
    called once per sync, not per request.

    `top_n` — how many clusters to include in `top_clusters` (by chunk
    count, descending).
    """
    docs_total = 0
    chunks_total = 0
    chunks_per_doc: list[int] = []
    cluster_by_doc: dict[str, int | None] = {}
    chunks_by_cluster: Counter[int] = Counter()
    docs_by_cluster: Counter[int] = Counter()
    links_by_kind: Counter[str] = Counter()
    resolved_links = 0
    resolved_no_target = 0
    unresolved_links = 0

    async for doc in persistence.documents.iter(source_id):
        docs_total += 1
        chunk_count = 0
        cluster_for_doc: int | None = None
        async for cwg in persistence.query.get_chunks(source_id, doc.id):
            chunk_count += 1
            if cluster_for_doc is None and cwg.cluster_id is not None:
                cluster_for_doc = cwg.cluster_id
            if cwg.cluster_id is not None:
                chunks_by_cluster[cwg.cluster_id] += 1
        chunks_total += chunk_count
        chunks_per_doc.append(chunk_count)
        cluster_by_doc[doc.id] = cluster_for_doc
        if cluster_for_doc is not None:
            docs_by_cluster[cluster_for_doc] += 1
        async for link in persistence.links.get(source_id, doc.id):
            links_by_kind[link.kind] += 1
            if not link.resolved:
                unresolved_links += 1
            elif link.target_document is not None:
                resolved_links += 1
            else:
                resolved_no_target += 1

    unclustered_docs = sum(1 for cid in cluster_by_doc.values() if cid is None)
    top_clusters = tuple(
        TopCluster(
            cluster_id=cid,
            doc_count=docs_by_cluster[cid],
            chunk_count=chunks_by_cluster[cid],
        )
        for cid, _ in chunks_by_cluster.most_common(top_n)
    )

    if chunks_per_doc:
        min_chunks = min(chunks_per_doc)
        max_chunks = max(chunks_per_doc)
        mean_chunks = sum(chunks_per_doc) / len(chunks_per_doc)
    else:
        min_chunks = max_chunks = 0
        mean_chunks = 0.0

    return CorpusReport(
        source_id=source_id,
        docs_total=docs_total,
        chunks_total=chunks_total,
        clusters_total=len(chunks_by_cluster),
        unclustered_docs=unclustered_docs,
        links_by_kind=dict(links_by_kind),
        resolved_links=resolved_links,
        resolved_no_target=resolved_no_target,
        unresolved_links=unresolved_links,
        chunks_per_doc=ChunksPerDoc(
            min=min_chunks,
            max=max_chunks,
            mean=mean_chunks,
        ),
        top_clusters=top_clusters,
    )
