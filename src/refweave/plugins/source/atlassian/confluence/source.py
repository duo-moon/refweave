"""Confluence source — yields SyncedDocuments to the orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal

from refweave.pipeline import SyncedDocument
from refweave.plugins.source.atlassian.confluence.build import build_document
from refweave.plugins.source.atlassian.confluence.cloud import CloudApi
from refweave.plugins.source.atlassian.confluence.dc import DcApi
from refweave.plugins.source.atlassian.confluence.links import LinkExtractor
from refweave.plugins.source.atlassian.confluence.navigation import (
    NavigationHeadingDetector,
)
from refweave.plugins.source.atlassian.confluence.parser import ConfluenceParser
from refweave.plugins.source.base import AuthProvider, HttpClient, document_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from refweave.model import Link
    from refweave.plugins.source.atlassian.confluence.api import ConfluenceApi
    from refweave.plugins.source.atlassian.confluence.types import RawPage

logger = logging.getLogger(__name__)

Tier = Literal["cloud", "dc"]
"""Which Confluence deployment `ConfluenceSource` talks to.

`"cloud"` — Atlassian-hosted Confluence (`*.atlassian.net`, REST v2).
`"dc"` — self-hosted Data Center / Server (REST v1). Endpoint URLs,
auth flavour, and pagination style branch on this.
"""

__all__ = ["ConfluenceSource", "Tier"]


class ConfluenceSource:
    """Iterates all pages of the configured spaces as `SyncedDocument`s.

    Owns the HTTP client and its lifecycle. Wraps a Cloud v2 or DC v1
    endpoint layer (chosen by `tier`) and produces documents with
    already-extracted but unresolved links; the orchestrator's resolver
    phase fills `target_document` for cross-page references.
    """

    def __init__(
        self,
        *,
        source_id: str,
        url: str,
        auth: AuthProvider,
        spaces: Sequence[str],
        tier: Tier = "cloud",
        rate_limit: float = 10.0,
        concurrency: int = 20,
        max_retries: int = 3,
        parser: ConfluenceParser | None = None,
        link_extractor: LinkExtractor | None = None,
        navigation_headings: Iterable[str] | None = None,
    ) -> None:
        self.source_id = source_id
        self._spaces = tuple(spaces)
        self._parser = parser or ConfluenceParser()
        self._link_extractor = link_extractor or LinkExtractor()
        self._nav_detector = NavigationHeadingDetector(navigation_headings)
        self._http = HttpClient(
            base_url=url,
            auth=auth,
            rate_limit=rate_limit,
            concurrency=concurrency,
            max_retries=max_retries,
        )
        self._api: ConfluenceApi = CloudApi(self._http) if tier == "cloud" else DcApi(self._http)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> ConfluenceSource:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        seen: set[str] = set()
        for space_key in self._spaces:
            async for raw in self._api.iter_pages(space_key):
                doc_id = document_id(self.source_id, raw.id)
                if doc_id in seen:
                    # Expected on overlapping-space configurations —
                    # same page visible from two queried spaces.
                    logger.debug(
                        "confluence page seen twice: doc_id=%s space=%s external=%s",
                        doc_id,
                        space_key,
                        raw.id,
                    )
                    continue
                seen.add(doc_id)
                # `_synced` runs the CPU-heavy pipeline (lxml storage-format
                # parse per page + per-section link extraction) which can
                # take tens of ms on large Confluence pages. Offload to a
                # worker thread so the event loop stays responsive to other
                # tasks (parallel Sources, HTTP fan-out) between yields.
                yield await asyncio.to_thread(self._synced, raw)

    def _synced(self, raw: RawPage) -> SyncedDocument:
        elements = self._parser.parse(raw.body)
        document = build_document(
            raw,
            elements,
            source_id=self.source_id,
            nav_detector=self._nav_detector,
        )
        links: list[Link] = []
        for section in document.sections:
            links.extend(
                self._link_extractor.extract(section, default_space=raw.space_key),
            )
        return SyncedDocument(document=document, links=tuple(links))
