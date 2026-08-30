"""HeadingRule — SPLIT on heading, optionally restricted to specific levels."""

from __future__ import annotations

from typing import Any

from refweave.model import Section
from refweave.plugins.chunker import Decision, HeadingRule

from .conftest import make_ctx


def _sec(seq: int, kind: str, level: int | None = None) -> Section:
    metadata: dict[str, Any] = {}
    if level is not None:
        metadata["heading_level"] = level
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind=kind,
        text="",
        metadata=metadata,
    )


def test_default_splits_on_any_heading_level() -> None:
    rule = HeadingRule()
    ctx = make_ctx()
    for level in (1, 2, 3, 4, 5, 6):
        result = rule.apply(_sec(1, "heading", level=level), [_sec(0, "paragraph")], ctx)
        assert result is Decision.SPLIT, level


def test_default_splits_on_heading_without_level_metadata() -> None:
    rule = HeadingRule()
    result = rule.apply(_sec(1, "heading"), [_sec(0, "paragraph")], make_ctx())
    assert result is Decision.SPLIT


def test_defers_on_non_heading() -> None:
    rule = HeadingRule()
    ctx = make_ctx()
    for kind in ("paragraph", "code", "list", "table", "quote"):
        result = rule.apply(_sec(1, kind), [_sec(0, "paragraph")], ctx)
        assert result is Decision.DEFER, kind


def test_restricted_levels_splits_only_on_configured() -> None:
    rule = HeadingRule(levels=[1, 2])
    ctx = make_ctx()
    assert rule.apply(_sec(1, "heading", level=1), [_sec(0, "p")], ctx) is Decision.SPLIT
    assert rule.apply(_sec(1, "heading", level=2), [_sec(0, "p")], ctx) is Decision.SPLIT
    assert rule.apply(_sec(1, "heading", level=3), [_sec(0, "p")], ctx) is Decision.DEFER
    assert rule.apply(_sec(1, "heading", level=6), [_sec(0, "p")], ctx) is Decision.DEFER


def test_missing_heading_level_treated_as_split() -> None:
    rule = HeadingRule(levels=[1])
    result = rule.apply(_sec(1, "heading"), [_sec(0, "paragraph")], make_ctx())
    assert result is Decision.SPLIT


def test_empty_levels_defers_on_typed_headings() -> None:
    """levels=[] means no configured level matches, so typed headings DEFER."""
    rule = HeadingRule(levels=[])
    result = rule.apply(_sec(1, "heading", level=1), [_sec(0, "paragraph")], make_ctx())
    assert result is Decision.DEFER


def test_empty_levels_still_splits_untyped_headings() -> None:
    """Documented invariant: unknown-level headings SPLIT defensively even
    when `levels` filters everything out — a heading without metadata is
    still safer to split than to swallow.
    """
    rule = HeadingRule(levels=[])
    result = rule.apply(_sec(1, "heading"), [_sec(0, "paragraph")], make_ctx())
    assert result is Decision.SPLIT
