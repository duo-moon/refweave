"""Typed view over Confluence-specific `Document.metadata`."""

from __future__ import annotations

from typing import ClassVar

from refweave.plugins.extras import SourceExtra


class ConfluenceExtra(SourceExtra):
    """Confluence page attributes surfaced on `Document.metadata`.

    `parent` — when present, the *doc id* of the parent page (already
    namespaced by source), not the raw Confluence page id.
    """

    NAMESPACE: ClassVar[str] = "_confluence"

    space: str
    labels: tuple[str, ...] = ()
    parent: str | None = None
