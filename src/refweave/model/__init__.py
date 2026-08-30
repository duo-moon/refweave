"""Refweave domain model — pure data types.

Every model except `SyncState` has:
    - `kind: str` — string classification label. Vocabulary is not enforced.
    - `metadata: dict[str, Any]` — free-form key-value bag.

`Section.kind`, `Link.kind`, `ChunkLinkRef.kind` are required.
`Chunk.kind` and `Document.kind` default to `"generic"`.

All cross-references are ID strings (see `refweave.ids` for the ID
convention). The models are Pydantic v2 BaseModel — no methods beyond
serialization defaults.
"""

from refweave.model.chunk import Chunk, ChunkLinkRef, ChunkWithGraph
from refweave.model.document import Document, SyncState
from refweave.model.link import Link
from refweave.model.section import Section

__all__ = [
    "Chunk",
    "ChunkLinkRef",
    "ChunkWithGraph",
    "Document",
    "Link",
    "Section",
    "SyncState",
]
