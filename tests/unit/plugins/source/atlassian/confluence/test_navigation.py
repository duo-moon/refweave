"""NavigationHeadingDetector — regex-based heading text matching."""

from __future__ import annotations

import pytest

from refweave.plugins.source.atlassian.confluence.navigation import NavigationHeadingDetector


def test_matches_default_english_headings() -> None:
    detector = NavigationHeadingDetector()
    for text in ("What's next", "See also", "Related", "Further reading"):
        assert detector.is_navigation(text), text


def test_matches_default_russian_headings() -> None:
    detector = NavigationHeadingDetector()
    for text in ("Дальше", "См. также", "По теме"):
        assert detector.is_navigation(text), text


def test_matches_with_trailing_punctuation() -> None:
    detector = NavigationHeadingDetector()
    assert detector.is_navigation("See also:")
    assert detector.is_navigation("What's next?")


def test_does_not_match_normal_headings() -> None:
    detector = NavigationHeadingDetector()
    assert not detector.is_navigation("Introduction")
    assert not detector.is_navigation("Configuration")


def test_custom_patterns_override_defaults() -> None:
    detector = NavigationHeadingDetector(patterns=[r"appendix"])
    assert detector.is_navigation("Appendix")
    assert not detector.is_navigation("See also")


def test_empty_patterns_rejected() -> None:
    # Empty alternation would silently match every heading — the opposite
    # of what a consumer clearing the list intends. Guard against it.
    with pytest.raises(ValueError, match="requires at least one pattern"):
        NavigationHeadingDetector(patterns=[])
    with pytest.raises(ValueError, match="requires at least one pattern"):
        NavigationHeadingDetector(patterns=())
