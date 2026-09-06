"""Batch-write every analysis artefact for a source into one directory.

Convenience wrapper: given a `Persistence` and a `source_id`, run every
tool in the module and drop the outputs as browseable files.

Layout:

    out_dir/
        README.md            index page with links to the rest
        report.md            corpus_report output
        graph.mmd            document_graph_mermaid output
        clusters/
            cluster-{id}.md  one file per cluster (via cluster_summary)
        chunks.jsonl         export_jsonl output

Meant for exploration and CI-style diff artefacts, not high-frequency
runs — cost is one full corpus scan plus one per-cluster scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from refweave.analysis.cluster import build_doc_cluster_map, cluster_summary
from refweave.analysis.export import export_jsonl
from refweave.analysis.graph import document_graph_mermaid
from refweave.analysis.report import corpus_report

if TYPE_CHECKING:
    from refweave.analysis.report import CorpusReport
    from refweave.pipeline import Persistence


@dataclass(frozen=True, slots=True)
class DumpResult:
    """Paths written by `dump_analysis` — handy for follow-up automation."""

    out_dir: Path
    report_path: Path
    graph_path: Path
    chunks_path: Path
    cluster_paths: tuple[Path, ...]


async def dump_analysis(
    persistence: Persistence,
    source_id: str,
    out_dir: Path | str,
    *,
    graph_max_nodes: int | None = 50,
    cluster_sample_size: int = 5,
) -> DumpResult:
    """Write the full analysis pack to `out_dir`. Creates the directory if needed.

    `graph_max_nodes` — cap for `document_graph_mermaid` (see its docstring).
    Pass `None` to include every document without a cap.
    `cluster_sample_size` — sample chunks per cluster in the per-cluster files.

    Overwrites any files with the same names — reruns produce a fresh
    snapshot every time.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "clusters").mkdir(exist_ok=True)

    report = await corpus_report(persistence, source_id)
    report_path = out / "report.md"
    await _write_text(report_path, str(report))

    graph_path = out / "graph.mmd"
    graph = await document_graph_mermaid(
        persistence,
        source_id,
        max_nodes=graph_max_nodes,
    )
    await _write_text(graph_path, graph)

    doc_cluster_map = await build_doc_cluster_map(persistence, source_id)
    cluster_paths: list[Path] = []
    for top in report.top_clusters:
        summary = await cluster_summary(
            persistence,
            source_id,
            top.cluster_id,
            sample_size=cluster_sample_size,
            doc_cluster_map=doc_cluster_map,
        )
        cluster_path = out / "clusters" / f"cluster-{top.cluster_id}.md"
        await _write_text(cluster_path, str(summary))
        cluster_paths.append(cluster_path)

    chunks_path = out / "chunks.jsonl"
    await export_jsonl(persistence, source_id, chunks_path)

    await _write_text(out / "README.md", _index(report, cluster_paths))

    return DumpResult(
        out_dir=out,
        report_path=report_path,
        graph_path=graph_path,
        chunks_path=chunks_path,
        cluster_paths=tuple(cluster_paths),
    )


async def _write_text(path: Path, content: str) -> None:
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
        if not content.endswith("\n"):
            await f.write("\n")


def _index(report: CorpusReport, cluster_paths: list[Path]) -> str:
    lines = [
        f"# Analysis snapshot — `{report.source_id}`",
        "",
        "- [`report.md`](report.md) — corpus summary (counts, top clusters).",
        "- [`graph.mmd`](graph.mmd) — Mermaid document graph.",
        "- [`chunks.jsonl`](chunks.jsonl) — all chunks + cluster/backlink info.",
        "- `clusters/` — one file per top cluster:",
    ]
    lines.extend(f"    - [`{path.name}`](clusters/{path.name})" for path in cluster_paths)
    return "\n".join(lines) + "\n"
