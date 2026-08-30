"""LinkOverlapRule — Jaccard over buffer-union vs curr targets."""

from __future__ import annotations

import pytest

from refweave.model import Section
from refweave.plugins.chunker import ChunkContext, Decision, LinkOverlapRule

from .conftest import make_ctx


def _sec(seq: int) -> Section:
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind="paragraph",
        text=f"section {seq}",
    )


def _ctx(**per_section_targets: tuple[str, ...]) -> ChunkContext:
    return make_ctx({f"sec:s:1:{seq}": targets for seq, targets in per_section_targets.items()})


def test_merges_when_jaccard_at_or_above_threshold() -> None:
    rule = LinkOverlapRule(threshold=0.5)
    # union {a,b}, curr {a,b} → J=1.0
    ctx = make_ctx({"sec:s:1:0": ("a", "b"), "sec:s:1:1": ("a", "b")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.MERGE


def test_defers_when_jaccard_below_threshold() -> None:
    rule = LinkOverlapRule(threshold=0.5)
    ctx = make_ctx({"sec:s:1:0": ("a", "b", "c"), "sec:s:1:1": ("c", "d", "e")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_defers_when_no_intersection() -> None:
    rule = LinkOverlapRule(threshold=0.1)
    ctx = make_ctx({"sec:s:1:0": ("a", "b"), "sec:s:1:1": ("c", "d")})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_defers_when_buffer_has_no_targets() -> None:
    rule = LinkOverlapRule(threshold=0.1)
    ctx = make_ctx({"sec:s:1:1": ("a",)})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


def test_defers_when_curr_has_no_targets() -> None:
    rule = LinkOverlapRule(threshold=0.1)
    ctx = make_ctx({"sec:s:1:0": ("a",)})
    result = rule.apply(_sec(1), [_sec(0)], ctx)
    assert result is Decision.DEFER


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
def test_threshold_out_of_range_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match=r"threshold must be in \[0.0, 1.0\]"):
        LinkOverlapRule(threshold=bad)


def test_uses_union_across_all_buffer_sections() -> None:
    rule = LinkOverlapRule(threshold=0.5)
    ctx = make_ctx(
        {
            "sec:s:1:0": ("a",),
            "sec:s:1:1": ("b",),
            "sec:s:1:2": ("c",),
            "sec:s:1:3": ("a", "b"),
        },
    )
    buffer = [_sec(0), _sec(1), _sec(2)]
    result = rule.apply(_sec(3), buffer, ctx)
    assert result is Decision.MERGE
