from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine, Sequence
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Refweave:
    """Public entry point for the refweave library.

    Contract: refweave-plan.md §4. M0 skeleton exposes the shape only;
    concrete behavior lands across M1-M8.
    """

    def __init__(
        self,
        storage: str | Path,
        sources: Sequence[Any] | None = None,
    ) -> None:
        self.storage = Path(storage)
        self.sources = list(sources or [])
        logger.debug(
            "Refweave initialized: storage=%s sources=%d",
            self.storage,
            len(self.sources),
        )

    # ---- Async API -----------------------------------------------------------

    async def sync(self, source_id: str) -> None:
        raise NotImplementedError(f"sync(source_id={source_id!r}) lands in M1")

    async def recompute_clusters(self) -> None:
        raise NotImplementedError("recompute_clusters lands in M5")

    async def rechunk(self, source_id: str) -> None:
        raise NotImplementedError(f"rechunk(source_id={source_id!r}) lands in M3")

    def chunks(self, document_id: str) -> AsyncIterator[Any]:
        raise NotImplementedError(f"chunks(document_id={document_id!r}) lands in M3")

    async def related(
        self,
        chunk_id: str,
        channels: Sequence[str],
        limit: int = 10,
    ) -> list[Any]:
        raise NotImplementedError(
            f"related(chunk_id={chunk_id!r}, channels={list(channels)!r}, "
            f"limit={limit}) lands in M6",
        )

    # ---- Sync wrappers -------------------------------------------------------

    def sync_sync(self, source_id: str) -> None:
        _run(self.sync(source_id))

    def recompute_clusters_sync(self) -> None:
        _run(self.recompute_clusters())

    def rechunk_sync(self, source_id: str) -> None:
        _run(self.rechunk(source_id))

    def chunks_sync(self, document_id: str) -> list[Any]:
        raise NotImplementedError(
            f"chunks_sync(document_id={document_id!r}) lands in M3",
        )

    def related_sync(
        self,
        chunk_id: str,
        channels: Sequence[str],
        limit: int = 10,
    ) -> list[Any]:
        return _run(self.related(chunk_id, channels, limit))


def _run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)
