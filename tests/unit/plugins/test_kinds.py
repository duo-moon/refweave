"""Contract tests for the cross-source section-kind vocabulary."""

from __future__ import annotations

from refweave.plugins.kinds import ATOMIC_KINDS, SectionKind


def test_section_kind_values_are_strings() -> None:
    # Namespace, not enum — values are plain str literals.
    assert isinstance(SectionKind.HEADING, str)
    assert isinstance(SectionKind.PARAGRAPH, str)


def test_section_kind_string_stability() -> None:
    # These string values are persisted on Chunk/Section.kind — treat
    # them as a semver-load-bearing surface. Renaming any of these is a
    # breaking change across the corpus.
    assert SectionKind.HEADING == "heading"
    assert SectionKind.PARAGRAPH == "paragraph"
    assert SectionKind.LIST == "list"
    assert SectionKind.TABLE == "table"
    assert SectionKind.CODE == "code"
    assert SectionKind.QUOTE == "quote"
    assert SectionKind.HR == "hr"
    assert SectionKind.UNKNOWN == "unknown"


def test_atomic_kinds_membership() -> None:
    assert SectionKind.CODE in ATOMIC_KINDS
    assert SectionKind.TABLE in ATOMIC_KINDS


def test_atomic_kinds_excludes_flowing_content() -> None:
    # Only truly indivisible blocks are atomic by default.
    for kind in (
        SectionKind.HEADING,
        SectionKind.PARAGRAPH,
        SectionKind.LIST,
        SectionKind.QUOTE,
        SectionKind.HR,
        SectionKind.UNKNOWN,
    ):
        assert kind not in ATOMIC_KINDS


def test_atomic_kinds_is_frozen() -> None:
    # Consumers can rely on it being hashable / immutable.
    assert isinstance(ATOMIC_KINDS, frozenset)
