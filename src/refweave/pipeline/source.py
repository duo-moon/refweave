"""Source — a plugin that yields SyncedDocuments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from refweave.model import Document, Link


@dataclass(frozen=True, slots=True)
class SyncedDocument:
    """One document from a source with its outgoing links."""

    document: Document
    links: tuple[Link, ...]


@runtime_checkable
class Source(Protocol):
    """Data source that yields SyncedDocuments.

    Links are returned as extracted, with `target_document` set only when
    the source itself knows the target at fetch time. Otherwise
    `target_document` is None; downstream code may fill it later.
    """

    source_id: str

    def iter(self) -> AsyncIterator[SyncedDocument]:
        """Yield all documents currently visible in the source. Order not guaranteed."""
        ...

    async def aclose(self) -> None:
        """Release any resources held by the source."""
        ...
