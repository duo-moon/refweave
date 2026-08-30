"""Post-processing tools for a synced refweave corpus.

Six entry points:

- `corpus_report` — one-call summary of docs, chunks, clusters, links.
- `cluster_summary` / `cluster_label` — inspect a single Leiden community.
- `document_graph_mermaid` — export the resolved-link graph as Mermaid.
- `chunk_with_context` — expand a chunk with same-document neighbours
  (standard RAG "context window" pattern).
- `export_jsonl` — stream all chunks + graph state as JSONL.
- `dump_analysis` — batch-write every artefact to a browsable directory.

All functions consume a `Persistence` bundle; they do not touch the
underlying stores directly, so they work identically on `FsStore +
SqliteStore` or `MemoryStore`.
"""

from refweave.analysis.cluster import (
    ClusterSummary,
    RelatedCluster,
    build_doc_cluster_map,
    cluster_label,
    cluster_summary,
)
from refweave.analysis.context import ChunkContext, chunk_with_context
from refweave.analysis.dump import DumpResult, dump_analysis
from refweave.analysis.export import export_jsonl
from refweave.analysis.graph import document_graph_mermaid
from refweave.analysis.report import (
    ChunksPerDoc,
    CorpusReport,
    TopCluster,
    corpus_report,
)

__all__ = [
    "ChunkContext",
    "ChunksPerDoc",
    "ClusterSummary",
    "CorpusReport",
    "DumpResult",
    "RelatedCluster",
    "TopCluster",
    "build_doc_cluster_map",
    "chunk_with_context",
    "cluster_label",
    "cluster_summary",
    "corpus_report",
    "document_graph_mermaid",
    "dump_analysis",
    "export_jsonl",
]
