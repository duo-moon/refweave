"""Tests for AtomicBlockRule — orphan-heading protection."""

from __future__ import annotations

from refweave.model import Section
from refweave.plugins.chunker import AtomicBlockRule, Decision

from .conftest import make_ctx


def _sec(kind: str, text: str, seq: int = 0) -> Section:
    return Section(
        id=f"sec:s:e:{seq}",
        document="doc:s:e",
        seq=seq,
        kind=kind,
        text=text,
        raw="",
    )


def test_defers_when_curr_is_not_atomic() -> None:
    rule = AtomicBlockRule()
    result = rule.apply(_sec("paragraph", "x" * 5000), [_sec("heading", "H")], make_ctx())
    assert result is Decision.DEFER


def test_merges_when_buffer_is_below_threshold_and_curr_atomic() -> None:
    rule = AtomicBlockRule(min_buffer_chars=200)
    heading = _sec("heading", "Big Section Title")  # 17 chars, well under 200
    code = _sec("code", "print(1)" * 500)  # huge
    assert rule.apply(code, [heading], make_ctx()) is Decision.MERGE


def test_defers_when_buffer_meets_threshold_even_with_atomic_curr() -> None:
    rule = AtomicBlockRule(min_buffer_chars=200)
    buffer = [_sec("paragraph", "x" * 250)]
    code = _sec("code", "print(1)")
    # Buffer already sizable → let SizeLimitRule decide as usual.
    assert rule.apply(code, buffer, make_ctx()) is Decision.DEFER


def test_default_atomic_kinds_cover_code_and_table() -> None:
    rule = AtomicBlockRule(min_buffer_chars=100)
    small_buffer = [_sec("heading", "H")]
    ctx = make_ctx()
    assert rule.apply(_sec("code", "x"), small_buffer, ctx) is Decision.MERGE
    assert rule.apply(_sec("table", "x"), small_buffer, ctx) is Decision.MERGE


def test_custom_atomic_kinds_recognized() -> None:
    rule = AtomicBlockRule(atomic_kinds=("panel",), min_buffer_chars=100)
    small_buffer = [_sec("heading", "H")]
    ctx = make_ctx()
    assert rule.apply(_sec("panel", "x"), small_buffer, ctx) is Decision.MERGE
    # code no longer atomic under this config
    assert rule.apply(_sec("code", "x"), small_buffer, ctx) is Decision.DEFER


def test_empty_buffer_still_triggers_merge() -> None:
    # An atomic block as the very first section — buffer size 0 < threshold,
    # so implementation returns MERGE (0 < min). Emitter treats MERGE on
    # empty buffer as "no-op accumulate", which is fine.
    rule = AtomicBlockRule(min_buffer_chars=200)
    result = rule.apply(_sec("code", "x"), [], make_ctx())
    assert result is Decision.MERGE
