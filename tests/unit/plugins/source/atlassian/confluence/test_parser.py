"""ConfluenceParser — XHTML storage format → StructuralElement list.

Focuses on the shapes the parser encounters in real Confluence output:
headings + anchors, paragraphs, code/table/list/quote/hr, macros (drop/
handle/unknown), entity substitution, malformed input.
"""

from __future__ import annotations

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.confluence.elements import (
    ElementKind,
    StructuralElement,
)
from refweave.plugins.source.atlassian.confluence.parser import ConfluenceParser


def _parse(xhtml: str) -> list[StructuralElement]:
    return ConfluenceParser().parse(xhtml)


def test_empty_input_returns_empty_list() -> None:
    assert _parse("") == []


def test_heading_with_id_becomes_heading_with_anchor() -> None:
    result = _parse('<h2 id="setup">Setup</h2>')
    assert len(result) == 1
    assert result[0].kind == SectionKind.HEADING
    assert result[0].text == "Setup"
    assert result[0].heading_level == 2
    assert result[0].anchor == "setup"


def test_heading_without_id_has_no_anchor() -> None:
    result = _parse("<h1>Intro</h1>")
    assert result[0].anchor is None


def test_all_heading_levels_produce_correct_heading_level_field() -> None:
    xhtml = "".join(f"<h{i}>Title {i}</h{i}>" for i in range(1, 7))
    result = _parse(xhtml)
    assert [elt.heading_level for elt in result] == [1, 2, 3, 4, 5, 6]


def test_paragraph_becomes_paragraph_element() -> None:
    result = _parse("<p>Hello world</p>")
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].text == "Hello world"


def test_table_becomes_table_element() -> None:
    result = _parse("<table><tr><td>x</td></tr></table>")
    assert result[0].kind == SectionKind.TABLE


def test_pre_becomes_code_element() -> None:
    result = _parse("<pre>code</pre>")
    assert result[0].kind == SectionKind.CODE


def test_blockquote_becomes_quote_element() -> None:
    result = _parse("<blockquote>quoted</blockquote>")
    assert result[0].kind == SectionKind.QUOTE


def test_hr_becomes_hr_with_empty_text() -> None:
    result = _parse("<hr/>")
    assert result[0].kind == SectionKind.HR
    assert result[0].text == ""


def test_ul_becomes_list_with_list_kind_metadata() -> None:
    result = _parse("<ul><li>a</li><li>b</li></ul>")
    assert result[0].kind == SectionKind.LIST
    assert result[0].metadata["list_kind"] == "ul"


def test_ol_becomes_list_with_list_kind_metadata() -> None:
    result = _parse("<ol><li>a</li><li>b</li></ol>")
    assert result[0].metadata["list_kind"] == "ol"


def test_unknown_top_level_tag_becomes_unknown_with_tag_hint() -> None:
    result = _parse("<div>content</div>")
    assert result[0].kind == SectionKind.UNKNOWN
    assert result[0].metadata["tag"] == "div"


def test_multiple_top_level_blocks_are_yielded_in_order_with_seq() -> None:
    result = _parse("<h1>Title</h1><p>Body</p><hr/>")
    assert [elt.seq for elt in result] == [0, 1, 2]
    assert [elt.kind for elt in result] == [
        SectionKind.HEADING,
        SectionKind.PARAGRAPH,
        SectionKind.HR,
    ]


def test_named_entities_are_substituted_before_parse() -> None:
    """`&nbsp;`, `&mdash;` etc. would otherwise crash the XML parser or
    truncate the fragment.
    """
    result = _parse("<p>foo&nbsp;bar&mdash;baz</p>")
    # Substituted to numeric refs; lxml then decodes to real chars.
    assert "foo" in result[0].text
    assert "bar" in result[0].text
    assert "baz" in result[0].text


def test_toc_macro_is_dropped() -> None:
    """`toc` is in _DROP_MACROS — no element emitted."""
    result = _parse(
        '<ac:structured-macro xmlns:ac="http://atlassian.com/content" ' 'ac:name="toc"/>',
    )
    assert result == []


def test_code_macro_becomes_code_element() -> None:
    """CodeMacro handler routes `<ac:structured-macro ac:name="code">`
    to a code section with body text.
    """
    xhtml = (
        '<ac:structured-macro xmlns:ac="http://atlassian.com/content" '
        'ac:name="code">'
        '<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body>'
        "</ac:structured-macro>"
    )
    result = _parse(xhtml)
    assert len(result) == 1
    assert result[0].kind == SectionKind.CODE
    assert 'print("hi")' in result[0].text


def test_info_panel_macro_becomes_callout_element() -> None:
    """CalloutMacro handles info/warning/note/tip panels."""
    xhtml = (
        '<ac:structured-macro xmlns:ac="http://atlassian.com/content" '
        'ac:name="info">'
        "<ac:rich-text-body><p>Heads up</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    result = _parse(xhtml)
    assert result[0].kind == ElementKind.CALLOUT


def test_anchor_macro_attaches_to_next_element() -> None:
    """`<ac:structured-macro ac:name="anchor">` marks the following
    element as an anchor target.
    """
    xhtml = (
        '<ac:structured-macro xmlns:ac="http://atlassian.com/content" '
        'ac:name="anchor">'
        '<ac:parameter ac:name="">bookmark</ac:parameter>'
        "</ac:structured-macro>"
        "<p>Anchored paragraph</p>"
    )
    result = _parse(xhtml)
    # One element (the anchor macro folded into the following paragraph).
    assert len(result) == 1
    assert result[0].kind == SectionKind.PARAGRAPH
    assert result[0].anchor == "bookmark"


def test_trailing_anchor_without_next_element_stays_standalone() -> None:
    xhtml = (
        '<ac:structured-macro xmlns:ac="http://atlassian.com/content" '
        'ac:name="anchor">'
        '<ac:parameter ac:name="">stub</ac:parameter>'
        "</ac:structured-macro>"
    )
    result = _parse(xhtml)
    assert len(result) == 1
    assert result[0].kind == ElementKind.ANCHOR
    assert result[0].anchor == "stub"


def test_comments_are_skipped() -> None:
    result = _parse("<p>a</p><!-- comment --><p>b</p>")
    assert len(result) == 2
    assert [elt.text for elt in result] == ["a", "b"]


def test_recover_mode_absorbs_malformed_fragments() -> None:
    """`recover=True` — parser makes best effort on broken XHTML. We
    just want no crash and that valid siblings still come through.
    """
    result = _parse("<p>valid</p><p>unclosed<p>next</p>")
    # At minimum the first paragraph survives; recover-mode may split
    # the unclosed one.
    assert any(elt.text == "valid" for elt in result)
