"""Tests for ADF parser (Jira Cloud description body)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.atlassian.jira.parser_adf import parse_adf


def _doc(*content: dict[str, Any]) -> str:
    return json.dumps({"type": "doc", "version": 1, "content": list(content)})


def _text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def test_empty_body_returns_empty_tuple() -> None:
    assert parse_adf("") == ()


def test_malformed_json_falls_back_to_paragraph() -> None:
    result = parse_adf("{ not valid json")
    assert len(result) == 1
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].text == "{ not valid json"


def test_heading_captures_level() -> None:
    body = _doc(
        {"type": "heading", "attrs": {"level": 3}, "content": [_text("Title")]},
    )
    result = parse_adf(body)
    assert len(result) == 1
    assert result[0].kind == SectionKind.HEADING
    assert result[0].heading_level == 3
    assert result[0].text == "Title"


def test_heading_out_of_range_drops_level() -> None:
    body = _doc(
        {"type": "heading", "attrs": {"level": 99}, "content": [_text("Title")]},
    )
    result = parse_adf(body)
    assert result[0].heading_level is None


def test_paragraph_collects_inline_text_mention_and_inline_card() -> None:
    body = _doc(
        {
            "type": "paragraph",
            "content": [
                _text("Please review "),
                {"type": "mention", "attrs": {"id": "u1", "text": "@alice"}},
                _text(" — see "),
                {"type": "inlineCard", "attrs": {"url": "https://example/browse/MFS-42"}},
            ],
        },
    )
    result = parse_adf(body)
    assert result[0].kind == SectionKind.PARAGRAPH
    assert "@alice" in result[0].text
    assert "MFS-42" in result[0].text


def test_code_block_carries_language() -> None:
    body = _doc(
        {
            "type": "codeBlock",
            "attrs": {"language": "python"},
            "content": [_text("print(1)")],
        },
    )
    result = parse_adf(body)
    assert result[0].kind == SectionKind.CODE
    assert result[0].metadata == {"language": "python"}
    assert result[0].text == "print(1)"


def test_panel_captures_panel_type() -> None:
    body = _doc(
        {
            "type": "panel",
            "attrs": {"panelType": "warning"},
            "content": [{"type": "paragraph", "content": [_text("Careful")]}],
        },
    )
    result = parse_adf(body)
    assert result[0].kind == ElementKind.PANEL
    assert result[0].metadata == {"panel_type": "warning"}


def test_rule_maps_to_hr_with_empty_text() -> None:
    body = _doc({"type": "rule"})
    result = parse_adf(body)
    assert result[0].kind == SectionKind.HR
    assert result[0].text == ""


@pytest.mark.parametrize("list_type", ["bulletList", "orderedList"])
def test_lists_carry_list_kind(list_type: str) -> None:
    body = _doc(
        {
            "type": list_type,
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [_text("Item")]},
                    ],
                },
            ],
        },
    )
    result = parse_adf(body)
    assert result[0].kind == SectionKind.LIST
    assert result[0].metadata == {"list_kind": list_type}


def test_unknown_block_type_produces_unknown_element() -> None:
    body = _doc({"type": "customThing", "content": [_text("payload")]})
    result = parse_adf(body)
    assert result[0].kind == SectionKind.UNKNOWN
    assert result[0].metadata == {"adf_type": "customThing"}
    assert "payload" in result[0].text


def test_seq_is_contiguous_from_zero() -> None:
    body = _doc(
        {"type": "heading", "attrs": {"level": 1}, "content": [_text("A")]},
        {"type": "paragraph", "content": [_text("body")]},
        {"type": "rule"},
    )
    result = parse_adf(body)
    assert [e.seq for e in result] == [0, 1, 2]
