"""ClusterBoundaryRule — SPLIT when target clusters diverge above threshold."""

from __future__ import annotations

import pytest

from refweave.model import Section
from refweave.plugins.chunker import ClusterBoundaryRule, Decision

from .conftest import make_ctx

# Synthetic corpus: target doc id → cluster id. Rule looks up clusters
# for each section's outgoing targets and Jaccard-compares the resulting
# cluster sets between buffer and curr.
_CLUSTERS = {f"t{i}": i for i in range(1, 10)}


def _sec(seq: int) -> Section:
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind="paragraph",
        text=f"section {seq}",
    )


def test_splits_when_clusters_disjoint() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    ctx = make_ctx({"sec:s:1:0": ("t1", "t2"), "sec:s:1:1": ("t3", "t4")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.SPLIT


def test_defers_when_clusters_fully_overlap() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    ctx = make_ctx({"sec:s:1:0": ("t1", "t2"), "sec:s:1:1": ("t1", "t2")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_defers_when_divergence_below_threshold() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.7)
    # buffer {1,2,3}; curr {2,3,4} → div = 1 - 2/4 = 0.5
    ctx = make_ctx({"sec:s:1:0": ("t1", "t2", "t3"), "sec:s:1:1": ("t2", "t3", "t4")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_splits_at_or_above_threshold() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.7)
    ctx = make_ctx(
        {"sec:s:1:0": ("t1", "t2", "t3", "t4"), "sec:s:1:1": ("t5",)},
    )
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.SPLIT


def test_defers_when_buffer_has_no_clusters() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    ctx = make_ctx({"sec:s:1:1": ("t1",)})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_defers_when_curr_has_no_clusters() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    ctx = make_ctx({"sec:s:1:0": ("t1",)})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_targets_missing_from_cluster_map_are_skipped() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    # buffer only sees unknown target → empty cluster set → DEFER
    ctx = make_ctx({"sec:s:1:0": ("unknown",), "sec:s:1:1": ("t1",)})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
def test_threshold_out_of_range_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match=r"threshold must be in \[0.0, 1.0\]"):
        ClusterBoundaryRule(_CLUSTERS, threshold=bad)


def test_uses_union_across_all_buffer_sections() -> None:
    rule = ClusterBoundaryRule(_CLUSTERS, threshold=0.5)
    ctx = make_ctx(
        {
            "sec:s:1:0": ("t1",),
            "sec:s:1:1": ("t2",),
            "sec:s:1:2": ("t3",),
            "sec:s:1:3": ("t4",),
        },
    )
    buffer = [_sec(0), _sec(1), _sec(2)]
    result = rule.apply(_sec(3), buffer, ctx)
    assert result is Decision.SPLIT
