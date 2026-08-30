"""Shared defaults for storage implementations.

These values are consumed by both `MemoryStore` and `SqliteStore` so
that changing the vocabulary in one place stays consistent across
backends. They are not exported from the package — treat as
implementation detail.
"""

from __future__ import annotations

from typing import Final

SAME_TARGET_EXCLUDED_KINDS: Final = frozenset({"navigation"})
"""Chunk kinds whose outgoing links do not source `same_target` edges.

Navigation-style chunks (see-also lists, whatsnext blocks) link at
everything without carrying topical signal; excluding them from
same_target keeps the graph clean.

Default matches `NavigationClassifier`'s default output kind. Consumers
who configure a different chunker vocabulary (e.g.
`NavigationClassifier(kind="toc")`) must mirror the change on the store
side. `anchor_follow` is NOT affected — a navigation chunk can still
participate as either endpoint of an anchor edge.
"""
