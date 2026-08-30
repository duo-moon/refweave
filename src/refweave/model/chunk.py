"""Chunk — a span of sections within a document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class ChunkLinkRef(BaseModel):
    """One outbound reference from a Chunk.

    `target_document` — target Document.id, or None when no target is set.
    `target_anchor` — target anchor within the target document, or None.
    `kind` — string classification label. Vocabulary is not enforced.
    """

    target_document: str | None = None
    target_anchor: str | None = None
    kind: str


class Chunk(BaseModel):
    """A retrievable span of Sections within a Document.

    `id` — canonical `chk:<source>:<external>:<seq>` (see `refweave.ids`).
    `document` — id of the containing Document.
    `seq` — position among the document's chunks, 0-based, contiguous.
    `kind` — string classification label. Defaults to `"generic"`.
    `text` — plain-text content of the chunk.
    `sections` — ids of Sections spanned by this chunk.
    `outgoing_links` — references derived from the spanned Sections' links.
    `metadata` — free-form key-value bag.
    """

    id: str
    document: str
    seq: int
    kind: str = "generic"
    text: str
    sections: tuple[str, ...] = Field(default_factory=tuple)
    outgoing_links: tuple[ChunkLinkRef, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkWithGraph:
    """A Chunk with post-hoc graph state.

    `chunk` — the underlying Chunk.
    `cluster_id` — cluster assignment, or None when unassigned.
    `incoming_anchor_from` — ids of Chunks whose outgoing anchor-scoped
                              references point at this Chunk.
    """

    chunk: Chunk
    cluster_id: int | None
    incoming_anchor_from: tuple[str, ...] = field(default_factory=tuple)
