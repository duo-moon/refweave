"""SizeLimitRule — SPLIT when buffer + curr exceeds max_chars."""

from __future__ import annotations

from refweave.model import Section
from refweave.plugins.chunker import Decision, SizeLimitRule

from .conftest import make_ctx


def _sec(seq: int, text: str) -> Section:
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind="paragraph",
        text=text,
    )


def test_defers_when_under_limit() -> None:
    rule = SizeLimitRule(max_chars=100)
    result = rule.apply(_sec(1, "b" * 30), [_sec(0, "a" * 30)], make_ctx())
    assert result is Decision.DEFER


def test_splits_when_addition_exceeds_limit() -> None:
    rule = SizeLimitRule(max_chars=100)
    result = rule.apply(_sec(1, "b" * 71), [_sec(0, "a" * 30)], make_ctx())
    assert result is Decision.SPLIT


def test_splits_when_curr_alone_exceeds_limit() -> None:
    rule = SizeLimitRule(max_chars=100)
    result = rule.apply(_sec(1, "b" * 200), [_sec(0, "a" * 30)], make_ctx())
    assert result is Decision.SPLIT


def test_defers_at_exact_limit() -> None:
    rule = SizeLimitRule(max_chars=100)
    result = rule.apply(_sec(1, "b" * 70), [_sec(0, "a" * 30)], make_ctx())
    assert result is Decision.DEFER
