"""Tests for LinkExtractor (Markdown inline links)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refweave.plugins.source.markdown import MarkdownLinkKind
from refweave.plugins.source.markdown._shared import tokenize
from refweave.plugins.source.markdown.keys import (
    HREF_KEY,
    TARGET_PATH_KEY,
    TITLE_KEY,
)
from refweave.plugins.source.markdown.links import LinkExtractor

if TYPE_CHECKING:
    from refweave.model import Link


def _links(body: str) -> list[Link]:
    tokens = tokenize(body)
    return list(LinkExtractor().extract(tokens, source_id="s", external="a.md"))


def test_no_links_yields_no_edges() -> None:
    assert _links("Just plain text.") == []


def test_external_https_link_marked_resolved() -> None:
    links = _links("[home](https://example.com)")
    assert len(links) == 1
    assert links[0].kind == MarkdownLinkKind.EXTERNAL
    assert links[0].resolved is True
    assert links[0].target_document is None
    assert links[0].metadata[HREF_KEY] == "https://example.com"
    assert links[0].metadata[TITLE_KEY] == "home"


def test_external_mailto_recognized() -> None:
    links = _links("[email me](mailto:x@y)")
    assert links[0].kind == MarkdownLinkKind.EXTERNAL


def test_internal_relative_path_link_unresolved() -> None:
    links = _links("[install](./setup.md)")
    assert links[0].kind == MarkdownLinkKind.INTERNAL
    assert links[0].resolved is False
    assert links[0].target_document is None
    assert links[0].target_anchor is None
    assert links[0].metadata[TARGET_PATH_KEY] == "./setup.md"


def test_internal_with_anchor_splits_path_and_anchor() -> None:
    links = _links("[section](./setup.md#config)")
    assert links[0].metadata[TARGET_PATH_KEY] == "./setup.md"
    assert links[0].target_anchor == "config"


def test_anchor_only_link_has_empty_target_path() -> None:
    links = _links("[top](#top)")
    assert links[0].kind == MarkdownLinkKind.INTERNAL
    assert links[0].metadata[TARGET_PATH_KEY] == ""
    assert links[0].target_anchor == "top"


def test_absolute_root_path_kept_verbatim_in_href() -> None:
    links = _links("[a](/docs/x.md)")
    assert links[0].kind == MarkdownLinkKind.INTERNAL
    assert links[0].metadata[TARGET_PATH_KEY] == "/docs/x.md"


def test_multiple_links_in_paragraph_get_sequential_seqs() -> None:
    links = _links("[a](./a.md) [b](./b.md) [c](./c.md)")
    assert [link.seq for link in links] == [0, 1, 2]


def test_link_section_seq_matches_block_position() -> None:
    body = (
        "# Title\n"
        "\n"
        "Intro with [first](./one.md).\n"
        "\n"
        "## Second\n"
        "\n"
        "Body with [second](./two.md) here.\n"
    )
    links = _links(body)
    # Section 0 is the H1, section 1 is intro paragraph, section 2 is H2,
    # section 3 is the body paragraph. Links land on their owning block.
    assert len(links) == 2
    assert links[0].section == "sec:s:a.md:1"
    assert links[1].section == "sec:s:a.md:3"


def test_links_reset_seq_per_section() -> None:
    body = "P1 [a](./a.md) [b](./b.md).\n\nP2 [c](./c.md)."
    links = _links(body)
    assert [link.seq for link in links] == [0, 1, 0]


def test_link_ids_use_source_and_external() -> None:
    links = _links("[a](./x.md)")
    assert links[0].id == "lnk:s:a.md:0:0"
    assert links[0].document == "doc:s:a.md"
