"""Contract tests for the canonical ID convention."""

from __future__ import annotations

import pytest

from refweave.ids import (
    chunk_id,
    document_id,
    link_id,
    parse_document_id,
    section_id,
    source_of,
)


def test_document_id_format() -> None:
    assert document_id("acme", "12345") == "doc:acme:12345"


def test_section_id_includes_seq() -> None:
    assert section_id("acme", "12345", 3) == "sec:acme:12345:3"


def test_chunk_id_includes_seq() -> None:
    assert chunk_id("acme", "12345", 0) == "chk:acme:12345:0"


def test_link_id_has_section_and_link_seq() -> None:
    assert link_id("acme", "12345", 2, 4) == "lnk:acme:12345:2:4"


def test_parse_document_id_roundtrip() -> None:
    source, external = parse_document_id(document_id("acme", "MFS-99"))
    assert (source, external) == ("acme", "MFS-99")


def test_parse_document_id_preserves_external_with_dashes_and_slashes() -> None:
    # Path-like external ids (Markdown source) must round-trip intact.
    source, external = parse_document_id("doc:docs:setup/getting-started.md")
    assert source == "docs"
    assert external == "setup/getting-started.md"


def test_source_of_returns_source_component() -> None:
    assert source_of("doc:acme:MFS-1") == "acme"


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "garbage",
        "doc",
        "doc:onlyonepart",
        "sec:acme:12345:0",  # section id — wrong prefix
        "chk:acme:12345:0",  # chunk id — wrong prefix
    ],
)
def test_parse_document_id_rejects_malformed(malformed: str) -> None:
    with pytest.raises(ValueError, match="invalid document id"):
        parse_document_id(malformed)


def test_parse_document_id_error_names_the_bad_input() -> None:
    with pytest.raises(ValueError, match="bogus"):
        parse_document_id("bogus")
