"""Canonical ID convention for documents, sections, chunks, links.

Single source of truth: both core (Store) and plugins format and parse IDs
through these helpers.

Contract: `source` and `external` must not contain `:`.
"""

from __future__ import annotations

from typing import Final

_DOC_ID_PARTS: Final = 3


def document_id(source: str, external: str) -> str:
    """`doc:<source>:<external>`"""
    return f"doc:{source}:{external}"


def section_id(source: str, external: str, seq: int) -> str:
    """`sec:<source>:<external>:<seq>`"""
    return f"sec:{source}:{external}:{seq}"


def chunk_id(source: str, external: str, seq: int) -> str:
    """`chk:<source>:<external>:<seq>`"""
    return f"chk:{source}:{external}:{seq}"


def link_id(source: str, external: str, section_seq: int, link_seq: int) -> str:
    """`lnk:<source>:<external>:<section_seq>:<link_seq>`"""
    return f"lnk:{source}:{external}:{section_seq}:{link_seq}"


def parse_document_id(doc_id: str) -> tuple[str, str]:
    """Split `doc:<source>:<external>` into (source, external)."""
    parts = doc_id.split(":", 2)
    if len(parts) != _DOC_ID_PARTS or parts[0] != "doc":
        msg = f"invalid document id: {doc_id!r} (expected doc:<source>:<external>)"
        raise ValueError(msg)
    return parts[1], parts[2]


def source_of(doc_id: str) -> str:
    """Extract source from a canonical document id."""
    return parse_document_id(doc_id)[0]
