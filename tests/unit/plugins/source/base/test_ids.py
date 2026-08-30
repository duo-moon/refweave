"""ID convention helpers: format and parseability."""

from __future__ import annotations

import pytest

from refweave.plugins.source.base import (
    chunk_id,
    document_id,
    link_id,
    parse_document_id,
    section_id,
)


def test_document_id_format() -> None:
    assert document_id("acme", "12345") == "doc:acme:12345"


def test_section_id_format() -> None:
    assert section_id("acme", "12345", 3) == "sec:acme:12345:3"


def test_chunk_id_format() -> None:
    assert chunk_id("acme", "12345", 0) == "chk:acme:12345:0"


def test_link_id_format() -> None:
    assert link_id("acme", "12345", 2, 5) == "lnk:acme:12345:2:5"


def test_parse_document_id_roundtrip() -> None:
    assert parse_document_id("doc:acme:12345") == ("acme", "12345")


def test_parse_document_id_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError, match="invalid document id"):
        parse_document_id("sec:acme:12345")


def test_parse_document_id_rejects_missing_parts() -> None:
    with pytest.raises(ValueError, match="invalid document id"):
        parse_document_id("doc:acme")


def test_parse_document_id_allows_colons_in_external() -> None:
    # Contract only forbids `:` in source. `external` after the second colon
    # is captured verbatim — split with maxsplit=2 protects against
    # accidental over-splitting on characters that shouldn't appear per
    # the plugin contract, but doesn't reject them here.
    assert parse_document_id("doc:acme:page:with:colons") == ("acme", "page:with:colons")
