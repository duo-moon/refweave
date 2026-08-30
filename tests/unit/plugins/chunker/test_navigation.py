"""NavigationClassifier — reads `navigation` flag on the first section."""

from __future__ import annotations

from refweave.model import Section
from refweave.plugins.chunker import NavigationClassifier

from .conftest import make_ctx


def _sec(seq: int, kind: str, *, navigation: bool = False) -> Section:
    return Section(
        id=f"sec:s:1:{seq}",
        document="doc:s:1",
        seq=seq,
        kind=kind,
        text=f"section {seq}",
        metadata={"navigation": True} if navigation else {},
    )


def test_marks_when_first_section_flagged() -> None:
    classify = NavigationClassifier()
    result = classify(
        [_sec(0, "heading", navigation=True), _sec(1, "paragraph")],
        make_ctx(),
    )
    assert result == "navigation"


def test_returns_none_when_first_section_not_flagged() -> None:
    classify = NavigationClassifier()
    result = classify(
        [_sec(0, "heading"), _sec(1, "paragraph", navigation=True)],
        make_ctx(),
    )
    assert result is None


def test_empty_sections_returns_none() -> None:
    classify = NavigationClassifier()
    assert classify([], make_ctx()) is None


def test_custom_kind_flows_through() -> None:
    classify = NavigationClassifier(kind="toc")
    result = classify([_sec(0, "heading", navigation=True)], make_ctx())
    assert result == "toc"
