"""Expand a single chunk with its textual neighbours from the same document.

Standard RAG pattern: retrieval returns one chunk, but a language model
usually needs surrounding context to answer well. `chunk_with_context`
pulls `before` and `after` chunks (by `Chunk.seq`) from the same
document and packages them together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from refweave.model import Chunk
    from refweave.pipeline import Persistence


@dataclass(frozen=True, slots=True)
class ChunkContext:
    """A retrieved chunk plus textual neighbours from the same document.

    `before` and `after` are ordered by `Chunk.seq` (oldest first in
    each). The center chunk sits between them; `concatenated()` returns
    the joined text ready to feed into a prompt.
    """

    center: Chunk
    before: tuple[Chunk, ...]
    after: tuple[Chunk, ...]

    def concatenated(self, sep: str = "\n\n") -> str:
        """Join before + center + after texts with `sep`."""
        parts = [chunk.text for chunk in self.before]
        parts.append(self.center.text)
        parts.extend(chunk.text for chunk in self.after)
        return sep.join(parts)


async def chunk_with_context(
    persistence: Persistence,
    source_id: str,
    chunk_id: str,
    *,
    before: int = 1,
    after: int = 1,
) -> ChunkContext | None:
    """Return the chunk + `before` prior + `after` following chunks of the same doc.

    Returns None if `chunk_id` is unknown. Neighbours are clipped at the
    document boundary — asking for `before=5` on a chunk that only has
    two prior siblings yields those two.

    `before` and `after` must be non-negative.
    """
    if before < 0 or after < 0:
        msg = f"before/after must be non-negative, got before={before}, after={after}"
        raise ValueError(msg)
    center = await persistence.query.get_chunk(source_id, chunk_id)
    if center is None:
        return None
    doc_id = center.chunk.document
    siblings: list[Chunk] = [
        cwg.chunk async for cwg in persistence.query.get_chunks(source_id, doc_id)
    ]

    center_idx: int | None = None
    for i, chunk in enumerate(siblings):
        if chunk.id == chunk_id:
            center_idx = i
            break
    if center_idx is None:
        # Center exists in blob store but not enumerated by get_chunks —
        # backend inconsistency; treat as missing.
        return None

    start = max(0, center_idx - before)
    end = min(len(siblings), center_idx + after + 1)
    return ChunkContext(
        center=center.chunk,
        before=tuple(siblings[start:center_idx]),
        after=tuple(siblings[center_idx + 1 : end]),
    )
