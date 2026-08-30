"""Structural metadata vocabulary shared across plugin layers.

Two surfaces per key:

    Constants (`*_KEY`) — write-side vocabulary used by producers
    (source plugins, chunker engine) to populate metadata dicts
    directly.

    Accessor functions — read-side wrappers used by consumers (chunker
    rules, classifiers, store implementations) to fetch a typed value
    with clear absent-vs-invalid semantics. Missing keys return
    None / False / empty; keys present with a wrong value type raise
    TypeError so producer bugs surface immediately.

Two categories of keys, distinguished by the metadata dict they land on:

    Source → chunker (Section.metadata)
        Populated by a source's build/parse pipeline; consumed by the
        chunker to make boundary decisions and classification.

    Chunker → store (Chunk.metadata)
        Populated by the chunker when emitting chunks; consumed by
        store implementations to build secondary indexes.

Source-specific metadata (labels, project, path, ...) lives on typed
`SourceExtra` containers per plugin — see `refweave.plugins.extras`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from refweave.model import Chunk, Section

# --- Source → chunker (Section.metadata) ---
HEADING_LEVEL_KEY: Final = "heading_level"
NAVIGATION_KEY: Final = "navigation"
ANCHOR_KEY: Final = "anchor"

# --- Chunker → store (Chunk.metadata) ---
ANCHORS_KEY: Final = "anchors"


def heading_level(section: Section) -> int | None:
    """Return the section's heading level, or None if absent.

    Raises TypeError when the value is present but not an int — a producer
    bug worth failing fast for.
    """
    value = section.metadata.get(HEADING_LEVEL_KEY)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{HEADING_LEVEL_KEY!r} must be int, got {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    return value


def is_navigation(section: Section) -> bool:
    """Return whether the section is flagged as navigation. False if absent."""
    return bool(section.metadata.get(NAVIGATION_KEY, False))


def anchor(section: Section) -> str | None:
    """Return the section's anchor id, or None if absent.

    Empty strings are treated as absent — anchor IDs must be non-empty
    to be meaningful.
    """
    value = section.metadata.get(ANCHOR_KEY)
    if not value:
        return None
    if not isinstance(value, str):
        msg = f"{ANCHOR_KEY!r} must be str, got {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    return value


def chunk_anchors(chunk: Chunk) -> tuple[str, ...]:
    """Return the chunk's anchor ids. Empty tuple if the key is absent."""
    value = chunk.metadata.get(ANCHORS_KEY, ())
    if not isinstance(value, tuple | list):
        msg = f"{ANCHORS_KEY!r} must be tuple/list, got {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    return tuple(value)
