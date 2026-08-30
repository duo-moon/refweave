"""Tests for wiki-markup parser (Jira DC description body)."""

from __future__ import annotations

import pytest

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.atlassian.jira.parser_wiki import parse_wiki


def test_empty_body_returns_empty_tuple() -> None:
    assert parse_wiki("") == ()


@pytest.mark.parametrize(
    ("marker", "level"),
    [("h1.", 1), ("h2.", 2), ("h3.", 3), ("h4.", 4), ("h5.", 5), ("h6.", 6)],
)
def test_heading_captures_level(marker: str, level: int) -> None:
    result = parse_wiki(f"{marker} Title")
    assert result[0].kind == SectionKind.HEADING
    assert result[0].heading_level == level
    assert result[0].text == "Title"


def test_hr_from_dashes() -> None:
    result = parse_wiki("----")
    assert result[0].kind == SectionKind.HR
    assert result[0].text == ""


def test_bq_single_line_quote() -> None:
    result = parse_wiki("bq. legacy quirk")
    assert result[0].kind == SectionKind.QUOTE
    assert result[0].text == "legacy quirk"


def test_code_macro_captures_language() -> None:
    body = "{code:python}\nprint(1)\n{code}"
    result = parse_wiki(body)
    assert result[0].kind == SectionKind.CODE
    assert result[0].metadata == {"language": "python"}
    assert "print(1)" in result[0].text


def test_noformat_macro_maps_to_code_text() -> None:
    body = "{noformat}\nraw stuff\n{noformat}"
    result = parse_wiki(body)
    assert result[0].kind == SectionKind.CODE
    assert result[0].metadata == {"language": "text"}


def test_quote_block_macro() -> None:
    body = "{quote}\nsome context\n{quote}"
    result = parse_wiki(body)
    assert result[0].kind == SectionKind.QUOTE
    assert result[0].text == "some context"


@pytest.mark.parametrize("panel", ["info", "warning", "note", "tip"])
def test_typed_panels_capture_panel_type(panel: str) -> None:
    body = f"{{{panel}}}\nBody\n{{{panel}}}"
    result = parse_wiki(body)
    assert result[0].kind == ElementKind.PANEL
    assert result[0].metadata == {"panel_type": panel}


def test_panel_macro_with_title() -> None:
    body = "{panel:title=Header}\nBody\n{panel}"
    result = parse_wiki(body)
    assert result[0].kind == ElementKind.PANEL
    assert result[0].metadata == {"title": "Header"}


def test_list_merges_consecutive_lines() -> None:
    body = "* one\n* two\n* three"
    result = parse_wiki(body)
    assert len(result) == 1
    assert result[0].kind == SectionKind.LIST
    assert result[0].text == "one\ntwo\nthree"


def test_table_flattens_cells_and_merges_rows() -> None:
    body = "||h1||h2||\n|a|b|\n|c|d|"
    result = parse_wiki(body)
    assert len(result) == 1
    assert result[0].kind == SectionKind.TABLE
    assert "a" in result[0].text
    assert "d" in result[0].text


def test_paragraph_collects_multiple_lines_and_strips_inline() -> None:
    body = "See [MFS-42] and *important* text.\nSecond line."
    result = parse_wiki(body)
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].text == "See MFS-42 and important text. Second line."


def test_labeled_link_keeps_label_only() -> None:
    body = "See [click here|https://x]."
    result = parse_wiki(body)
    assert result[0].text == "See click here."


def test_blank_lines_do_not_produce_empty_elements() -> None:
    body = "First.\n\n\nSecond."
    result = parse_wiki(body)
    assert len(result) == 2
    assert result[0].text == "First."
    assert result[1].text == "Second."


def test_unclosed_macro_consumes_to_end_without_crash() -> None:
    body = "{code}\nnever closed"
    result = parse_wiki(body)
    assert result[0].kind == SectionKind.CODE
    assert "never closed" in result[0].text


def test_paragraph_stops_at_next_block_marker() -> None:
    body = "Line one.\nh2. New Heading"
    result = parse_wiki(body)
    assert len(result) == 2
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].text == "Line one."
    assert result[1].kind == SectionKind.HEADING


def test_seq_is_contiguous_from_zero() -> None:
    body = "h1. A\n\nParagraph\n\n----"
    result = parse_wiki(body)
    assert [e.seq for e in result] == [0, 1, 2]
