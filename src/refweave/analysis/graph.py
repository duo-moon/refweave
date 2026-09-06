"""Document-level graph export to Mermaid.

Mermaid is a lightweight graph language rendered client-side by GitHub,
GitLab, most notebook renderers, and a handful of docs tools. Output is
a plain string — paste it into a fenced ```mermaid block and it renders.

Chunk-level graph export lives in a follow-up module; the document view
is the natural first look at a corpus and typically fits under 200
nodes for hand-review.
"""

from __future__ import annotations

import colorsys
import re
from collections import Counter
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from refweave.pipeline import Persistence

_UNCLUSTERED_COLOR: Final = "#cccccc"
_SAFE_ID_RE: Final = re.compile(r"[^A-Za-z0-9_]")

# Golden-angle rotation (137.508°) spreads cluster hues as evenly as
# possible: adjacent cluster_ids get maximally distant hues, so `1` and
# `2` never look alike on the diagram. Saturation and lightness are
# picked to match Mermaid's default pastel theme and stay legible with
# dark node text. We emit hex — Mermaid's `classDef` parser chokes on
# the parentheses in `hsl(...)`.
_HUE_GOLDEN_ANGLE: Final = 137.508
_CLUSTER_HUE_SATURATION: Final = 0.55  # 0..1
_CLUSTER_HUE_LIGHTNESS: Final = 0.72  # 0..1


def _cluster_color(cluster_id: int) -> str:
    """Deterministic pastel hex colour for a cluster id (golden-angle rotation)."""
    hue = ((cluster_id * _HUE_GOLDEN_ANGLE) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(
        hue,
        _CLUSTER_HUE_LIGHTNESS,
        _CLUSTER_HUE_SATURATION,
    )
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


async def document_graph_mermaid(
    persistence: Persistence,
    source_id: str,
    *,
    max_nodes: int | None = 50,
) -> str:
    """Render the document-level graph as a Mermaid `graph LR` string.

    Nodes are documents (labelled by title, coloured by cluster). Edges
    are `link.target_document`-resolved links between docs — kind is
    dropped to keep the diagram legible; expand `chunk_graph_export`
    (planned) if you need per-channel colouring.

    `max_nodes` — cap on rendered nodes. When the corpus is bigger, the
    top-`max_nodes` documents by degree (in + out) are kept and the rest
    are collapsed into a synthetic `others` node. `None` renders every
    document without a cap; note that Mermaid's own tooling slows down
    past ~500 nodes. Non-positive ints are rejected — use `None` when
    you want everything.
    """
    if max_nodes is not None and max_nodes <= 0:
        msg = (
            f"max_nodes must be a positive int or None (got {max_nodes}); "
            "pass None to disable the cap."
        )
        raise ValueError(msg)
    doc_titles: dict[str, str] = {}
    doc_clusters: dict[str, int | None] = {}
    async for doc in persistence.documents.iter(source_id):
        doc_titles[doc.id] = doc.title or doc.id
        cluster_id: int | None = None
        async for cwg in persistence.query.get_chunks(source_id, doc.id):
            cluster_id = cwg.cluster_id
            break  # first chunk carries the doc's cluster
        doc_clusters[doc.id] = cluster_id

    edges: list[tuple[str, str]] = []
    for doc_id in doc_titles:
        async for link in persistence.links.get(source_id, doc_id):
            target = link.target_document
            if not link.resolved or target is None or target == doc_id:
                continue
            edges.append((doc_id, target))

    if max_nodes is not None and len(doc_titles) > max_nodes:
        kept, others_edges, has_others = _select_top_nodes(
            doc_titles,
            edges,
            max_nodes,
        )
    else:
        kept = set(doc_titles)
        others_edges = edges
        has_others = False

    return _render_mermaid(
        doc_titles=doc_titles,
        doc_clusters=doc_clusters,
        kept=kept,
        edges=others_edges,
        include_others=has_others,
    )


def _select_top_nodes(
    doc_titles: dict[str, str],
    edges: list[tuple[str, str]],
    max_nodes: int,
) -> tuple[set[str], list[tuple[str, str]], bool]:
    """Keep top-`max_nodes` by degree, collapse the rest into `_others`."""
    degree: Counter[str] = Counter()
    for src, dst in edges:
        degree[src] += 1
        degree[dst] += 1
    for doc_id in doc_titles:
        degree.setdefault(doc_id, 0)
    kept_ids = {doc_id for doc_id, _ in degree.most_common(max_nodes)}
    projected: list[tuple[str, str]] = []
    has_others = False
    for src, dst in edges:
        src_in = src in kept_ids
        dst_in = dst in kept_ids
        if src_in and dst_in:
            projected.append((src, dst))
        elif src_in and not dst_in:
            projected.append((src, "_others"))
            has_others = True
        elif dst_in and not src_in:
            projected.append(("_others", dst))
            has_others = True
        # neither → dropped (edge is within the collapsed set)
    return kept_ids, projected, has_others


def _render_mermaid(
    *,
    doc_titles: dict[str, str],
    doc_clusters: dict[str, int | None],
    kept: Iterable[str],
    edges: Iterable[tuple[str, str]],
    include_others: bool,
) -> str:
    lines = ["graph LR"]
    node_ids: dict[str, str] = {}
    clusters_seen: set[int] = set()
    for doc_id in kept:
        safe = _safe_id(doc_id)
        node_ids[doc_id] = safe
        title = _escape_label(doc_titles.get(doc_id, doc_id))
        cluster_id = doc_clusters.get(doc_id)
        class_suffix = f":::c{cluster_id}" if cluster_id is not None else ":::cnone"
        lines.append(f'    {safe}["{title}"]{class_suffix}')
        if cluster_id is not None:
            clusters_seen.add(cluster_id)
    if include_others:
        node_ids["_others"] = "others"
        lines.append('    others[["… others"]]:::cnone')
    for src, dst in edges:
        src_safe = node_ids.get(src)
        dst_safe = node_ids.get(dst)
        if src_safe is None or dst_safe is None:
            continue
        lines.append(f"    {src_safe} --> {dst_safe}")
    # `color:#111` pins node text to near-black on every cluster fill —
    # otherwise Mermaid's dark theme uses white text and washes out on
    # pastel backgrounds.
    lines.append(
        f"    classDef cnone fill:{_UNCLUSTERED_COLOR},stroke:#888,color:#111",
    )
    lines.extend(
        f"    classDef c{cluster_id} " f"fill:{_cluster_color(cluster_id)},stroke:#333,color:#111"
        for cluster_id in sorted(clusters_seen)
    )
    return "\n".join(lines) + "\n"


def _safe_id(doc_id: str) -> str:
    """Mermaid node ids must match `[A-Za-z0-9_]`. Slugify the doc id."""
    return _SAFE_ID_RE.sub("_", doc_id) or "n"


def _escape_label(text: str) -> str:
    """Escape characters that break Mermaid's `["…"]` node label syntax."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
