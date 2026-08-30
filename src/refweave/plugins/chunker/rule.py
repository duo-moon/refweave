"""Chunking rule interface and built-in Rule / Classifier implementations.

A rule looks at the current buffer, a candidate section, and the
per-document `ChunkContext`, and returns MERGE, SPLIT, or DEFER. The
engine composes rules through a `Policy`.

This module bundles:
    - the `Decision` enum, `Rule` protocol, and `ChunkContext` dataclass
    - built-in Rule implementations (size, structural, graph-signal)
    - the `NavigationClassifier` (a `ChunkClassifier`, not a `Rule`)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from refweave.plugins.keys import heading_level, is_navigation
from refweave.plugins.kinds import ATOMIC_KINDS, SectionKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from refweave.model import Document, Section


@dataclass(frozen=True, slots=True)
class ChunkContext:
    """Per-document context passed to every rule and classifier.

    Built once at the start of chunking a document; rules read the
    fields they need. Rules requiring chunker-run priors (e.g. cluster
    assignments) receive them through their own constructor — the
    context carries only per-document derivations.

    `outgoing_by_section` — for each section id in the document, the
    ordered tuple of resolved target document ids reached by that
    section's outgoing links. Sections with no resolved outgoing links
    are absent from the mapping.
    """

    document: Document
    outgoing_by_section: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class Decision(Enum):
    """Boundary decision returned by a Rule."""

    MERGE = "merge"
    SPLIT = "split"
    DEFER = "defer"


@runtime_checkable
class Rule(Protocol):
    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        """Judge whether `curr` belongs in `buffer`.

        `buffer` is the non-empty current chunk; `buffer[-1]` is the
        last section already accepted, earlier entries are available
        for rules that consider broader context.

        `ctx` gives access to per-document indices (outgoing targets,
        etc.). Rules that don't need it may ignore the argument.

        Rules that need external state receive it through their
        constructor, not through this call.
        """
        ...


class MinSizeRule:
    """MERGE when `buffer + curr` is still under `min_chars`, else DEFER.

    Placed before other rules in a Policy, it prevents structural
    boundaries from emitting under-sized chunks — pattern:
    `[MinSizeRule, StructuralRule, SizeLimitRule]`. Only overrides
    when adding `curr` keeps the total below the minimum; larger
    `curr` lets later rules decide the boundary.
    """

    def __init__(self, min_chars: int = 500) -> None:
        self._min_chars = min_chars

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del ctx
        buffer_size = sum(len(s.text) for s in buffer)
        if buffer_size + len(curr.text) < self._min_chars:
            return Decision.MERGE
        return Decision.DEFER


class SizeLimitRule:
    """SPLIT when appending `curr` would push the buffer past `max_chars`.

    A single section longer than `max_chars` triggers a SPLIT before
    it, so the oversized section starts its own chunk instead of
    merging with prior context. The resulting chunk still exceeds the
    limit — rules do not split sections.
    """

    def __init__(self, max_chars: int = 4000) -> None:
        self._max_chars = max_chars

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del ctx
        buffer_size = sum(len(s.text) for s in buffer)
        if buffer_size + len(curr.text) > self._max_chars:
            return Decision.SPLIT
        return Decision.DEFER


class HeadingRule:
    """SPLIT when a heading starts a new section.

    `levels=None` (default) SPLITs on any heading. Pass a specific set
    to restrict — e.g. `HeadingRule(levels=[1, 2])` splits only on
    H1/H2 and lets H3-H6 stay inside the same chunk. `levels=[]` still
    SPLITs untyped headings (see below) — to disable heading-based
    splitting entirely, omit the rule from the Policy.

    `kind` — the `Section.kind` string that identifies a heading.
    Default `SectionKind.HEADING` matches every built-in source's
    ElementKind namespace; override when a custom source uses a
    different vocabulary.

    A heading section without `heading_level` in metadata is treated
    as a boundary — a heading is a heading regardless of whether the
    source told us its level. This defensive SPLIT fires even when
    `levels` filters everything out, on the principle that unknown-
    level headings are safer to split than to swallow.
    """

    def __init__(
        self,
        levels: Iterable[int] | None = None,
        *,
        kind: str = SectionKind.HEADING,
    ) -> None:
        self._levels = frozenset(levels) if levels is not None else None
        self._kind = kind

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del buffer, ctx
        if curr.kind != self._kind:
            return Decision.DEFER
        if self._levels is None:
            return Decision.SPLIT
        level = heading_level(curr)
        if level is None:
            return Decision.SPLIT
        if level in self._levels:
            return Decision.SPLIT
        return Decision.DEFER


class AtomicBlockRule:
    """MERGE a small buffer with an incoming atomic block instead of orphaning.

    Prevents the pattern where a lone heading (buffer size well below
    the interesting content threshold) gets emitted as its own chunk
    right before a large code/table section that would then trigger
    `SizeLimitRule`. The alternative is a tiny heading-only chunk
    followed by an atomic-only chunk — the heading loses its
    adjacency signal.

    Trade-off: this rule permits one *over-size* chunk (buffer + large
    atomic) in exchange for keeping structural context intact. Place
    it before `SizeLimitRule` so its MERGE decision short-circuits the
    size check. Default `atomic_kinds` — `plugins.kinds.ATOMIC_KINDS`,
    the cross-source vocabulary for indivisible content.

    Fine-tune `min_buffer_chars` per corpus. 200 is a reasonable
    default for docs where headings run 10-80 chars; raise it if
    paragraphs before code samples should also stick.
    """

    def __init__(
        self,
        *,
        atomic_kinds: Iterable[str] = ATOMIC_KINDS,
        min_buffer_chars: int = 200,
    ) -> None:
        self._atomic = frozenset(atomic_kinds)
        self._min_buffer = min_buffer_chars

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del ctx
        if curr.kind not in self._atomic:
            return Decision.DEFER
        buffer_size = sum(len(s.text) for s in buffer)
        if buffer_size < self._min_buffer:
            return Decision.MERGE
        return Decision.DEFER


# ---- Graph-signal rules ---------------------------------------------------


class LinkOverlapRule:
    """MERGE when Jaccard(buffer targets, curr targets) >= `threshold`.

    Reads outgoing target doc ids from `ctx.outgoing_by_section`.
    Sections with no outgoing targets are skipped (rule DEFERs — the
    similarity is undefined).
    """

    def __init__(self, *, threshold: float = 0.3) -> None:
        if not 0.0 <= threshold <= 1.0:
            msg = f"threshold must be in [0.0, 1.0], got {threshold}"
            raise ValueError(msg)
        self._threshold = threshold

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        buffer_targets: set[str] = set()
        for section in buffer:
            buffer_targets.update(ctx.outgoing_by_section.get(section.id, ()))
        curr_targets = set(ctx.outgoing_by_section.get(curr.id, ()))
        if not buffer_targets or not curr_targets:
            return Decision.DEFER
        intersection = buffer_targets & curr_targets
        union = buffer_targets | curr_targets
        jaccard = len(intersection) / len(union)
        if jaccard >= self._threshold:
            return Decision.MERGE
        return Decision.DEFER


class ClusterBoundaryRule:
    """SPLIT when (1 - Jaccard(buffer clusters, curr clusters)) >= `threshold`.

    Owns its `clusters` mapping (doc_id → cluster_id). Sections'
    outgoing target ids come from `ctx.outgoing_by_section`; the rule
    projects them through `clusters` to get cluster ids per section.
    Sections whose targets miss the cluster map contribute nothing —
    if both buffer and curr end up empty, the rule DEFERs.
    """

    def __init__(
        self,
        clusters: Mapping[str, int],
        *,
        threshold: float = 0.7,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            msg = f"threshold must be in [0.0, 1.0], got {threshold}"
            raise ValueError(msg)
        self._clusters = clusters
        self._threshold = threshold

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        buffer_clusters = self._clusters_for(buffer, ctx)
        curr_clusters = self._clusters_for((curr,), ctx)
        if not buffer_clusters or not curr_clusters:
            return Decision.DEFER
        intersection = buffer_clusters & curr_clusters
        union = buffer_clusters | curr_clusters
        divergence = 1 - len(intersection) / len(union)
        if divergence >= self._threshold:
            return Decision.SPLIT
        return Decision.DEFER

    def _clusters_for(
        self,
        sections: Sequence[Section],
        ctx: ChunkContext,
    ) -> set[int]:
        result: set[int] = set()
        for section in sections:
            for target in ctx.outgoing_by_section.get(section.id, ()):
                cluster = self._clusters.get(target)
                if cluster is not None:
                    result.add(cluster)
        return result


class NavigationClassifier:
    """Marks a chunk as `kind` if its first section carries the navigation flag.

    Trusts the `is_navigation(section)` accessor over the first
    section — the source that produced the Section is responsible for
    setting the flag on the appropriate structural element (typically
    the heading that introduces a table-of-contents block).

    Only the chunk's first section is inspected. To keep detection
    reliable, the surrounding Policy must SPLIT on the flagged section
    so it lands at the start of its chunk (default `HeadingRule` does
    this for heading-flagged navigation).

    Default output kind is `"navigation"`. Callers preferring a
    different vocabulary pass their own: `NavigationClassifier(kind="toc")`.
    """

    def __init__(self, *, kind: str = "navigation") -> None:
        self._kind = kind

    def __call__(
        self,
        sections: Sequence[Section],
        ctx: ChunkContext,
    ) -> str | None:
        del ctx
        if not sections:
            return None
        if is_navigation(sections[0]):
            return self._kind
        return None
