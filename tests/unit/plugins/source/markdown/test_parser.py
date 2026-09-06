"""Tests for the Markdown parser (markdown-it-py backed)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.markdown._shared import tokenize
from refweave.plugins.source.markdown.elements import ElementKind
from refweave.plugins.source.markdown.parser import parse_markdown, slugify

if TYPE_CHECKING:
    from refweave.plugins.source.base import StructuralElement


def _parse(body: str) -> tuple[StructuralElement, ...]:
    return parse_markdown(tokenize(body), body)


def test_empty_body_returns_empty_tuple() -> None:
    assert _parse("") == ()


@pytest.mark.parametrize(
    ("prefix", "level"),
    [("#", 1), ("##", 2), ("###", 3), ("####", 4), ("#####", 5), ("######", 6)],
)
def test_heading_captures_level(prefix: str, level: int) -> None:
    result = _parse(f"{prefix} Title")
    assert result[0].kind == SectionKind.HEADING
    assert result[0].heading_level == level


def test_heading_auto_slug_anchor() -> None:
    result = _parse("## Getting Started")
    assert result[0].anchor == "getting-started"


def test_heading_explicit_anchor_wins() -> None:
    result = _parse("## Getting Started {#quickstart}")
    assert result[0].anchor == "quickstart"
    assert result[0].text == "Getting Started"


def test_paragraph_strips_link_markup_from_text() -> None:
    result = _parse("See [the guide](./x.md) for details.")
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].text == "See the guide for details."


def test_bullet_list_captures_list_kind() -> None:
    result = _parse("- one\n- two\n- three")
    assert len(result) == 1
    assert result[0].kind == SectionKind.LIST
    assert result[0].metadata == {"list_kind": "bullet"}
    assert result[0].text == "one\ntwo\nthree"


def test_ordered_list_captures_list_kind() -> None:
    result = _parse("1. one\n2. two")
    assert result[0].kind == SectionKind.LIST
    assert result[0].metadata == {"list_kind": "ordered"}


def test_fenced_code_carries_language() -> None:
    src = "```python\nprint(1)\n```"
    result = _parse(src)
    assert result[0].kind == SectionKind.CODE
    assert result[0].metadata == {"language": "python"}
    assert result[0].text == "print(1)"


def test_fenced_code_language_only_first_token() -> None:
    # ```python arg=val — take just "python" as the language.
    result = _parse("```python arg=val\nprint(1)\n```")
    assert result[0].metadata == {"language": "python"}


def test_fenced_code_no_language_no_metadata() -> None:
    result = _parse("```\nplain\n```")
    assert result[0].kind == SectionKind.CODE
    assert result[0].metadata == {}


def test_indented_code_block_is_code() -> None:
    result = _parse("    print(1)")
    assert result[0].kind == SectionKind.CODE
    assert "print(1)" in result[0].text


def test_blockquote_captures_text() -> None:
    result = _parse("> Note: read this first.")
    assert result[0].kind == SectionKind.QUOTE
    assert "read this first" in result[0].text


def test_hr_from_dashes() -> None:
    result = _parse("---")
    assert result[0].kind == SectionKind.HR
    assert result[0].text == ""


def test_gfm_table_flattens_cells() -> None:
    src = "| A | B |\n|---|---|\n| a | b |"
    result = _parse(src)
    assert result[0].kind == SectionKind.TABLE
    assert "A" in result[0].text
    assert "b" in result[0].text


def test_html_block_recognized() -> None:
    src = '<div class="note">raw html</div>'
    result = _parse(src)
    assert result[0].kind == ElementKind.HTML
    assert "raw html" in result[0].text


def test_seq_is_contiguous_from_zero() -> None:
    src = "# A\n\nparagraph\n\n---"
    result = _parse(src)
    assert [e.seq for e in result] == [0, 1, 2]


def test_raw_field_preserves_original_markdown_fragment() -> None:
    result = _parse("## Section title\n\nBody.")
    # `raw` for the heading should include the `## ` prefix, not just the text.
    assert "## Section title" in result[0].raw


def test_slugify_basic() -> None:
    assert slugify("Getting Started") == "getting-started"
    # Punctuation is stripped and consecutive whitespace collapses to one dash.
    assert slugify("Foo, Bar & Baz!") == "foo-bar-baz"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("under_scores") == "under-scores"
