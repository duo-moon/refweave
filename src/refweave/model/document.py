"""Document — root aggregate of a synced content unit."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from refweave.model.section import Section


class SyncState(BaseModel):
    """Source-side revision and tombstone.

    `version` — monotonic revision number; higher means newer.
    `updated_at` — timestamp when the document was last modified.
    `deleted_at` — timestamp when the document was marked as deleted,
                   or None if the document is currently live.
    """

    version: int
    updated_at: datetime
    deleted_at: datetime | None = None


class Document(BaseModel):
    """Root aggregate of one document.

    `id` — canonical `doc:<source>:<external>` (see `refweave.ids`).
    `title` — human-facing title.
    `kind` — string classification label. Defaults to `"generic"`.
    `sections` — ordered content, indexed by `Section.seq`.
    `sync` — revision + tombstone state (see `SyncState`).
    `graph_version` — monotonic version number for graph-side state.
    `metadata` — free-form key-value bag.
    """

    id: str
    title: str
    kind: str = "generic"
    sections: tuple[Section, ...] = Field(default_factory=tuple)
    sync: SyncState
    graph_version: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
