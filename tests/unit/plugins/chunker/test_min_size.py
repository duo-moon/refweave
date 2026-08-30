"""MinSizeRule — MERGE when buffer + curr is still under min_chars."""

from __future__ import annotations

from refweave.model import Section
from refweave.plugins.chunker import Decision, MinSizeRule

from .conftest import make_ctx


def _sec(seq: int, text: str) -> Section:
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind="paragraph",
        text=text,
    )


def test_merges_when_total_still_under_min() -> None:
    rule = MinSizeRule(min_chars=500)
    result = rule.apply(_sec(1, "b" * 100), [_sec(0, "a" * 100)], make_ctx())
    assert result is Decision.MERGE


def test_defers_when_total_reaches_min() -> None:
    rule = MinSizeRule(min_chars=500)
    result = rule.apply(_sec(1, "b" * 300), [_sec(0, "a" * 200)], make_ctx())
    assert result is Decision.DEFER


def test_defers_when_curr_alone_is_large() -> None:
    """If curr is big enough, MinSize doesn't hold up structural boundaries."""
    rule = MinSizeRule(min_chars=500)
    result = rule.apply(_sec(1, "b" * 1000), [_sec(0, "a" * 10)], make_ctx())
    assert result is Decision.DEFER


def test_defers_at_exact_min() -> None:
    rule = MinSizeRule(min_chars=100)
    result = rule.apply(_sec(1, "b" * 50), [_sec(0, "a" * 50)], make_ctx())
    assert result is Decision.DEFER
