"""Jira source — yields SyncedDocuments to the orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal

from refweave.pipeline import SyncedDocument
from refweave.plugins.source.atlassian.jira.build import build_document
from refweave.plugins.source.atlassian.jira.cloud import CloudApi
from refweave.plugins.source.atlassian.jira.dc import DcApi
from refweave.plugins.source.atlassian.jira.links import LinkExtractor
from refweave.plugins.source.atlassian.jira.parser_adf import parse_adf
from refweave.plugins.source.atlassian.jira.parser_wiki import parse_wiki
from refweave.plugins.source.base import AuthProvider, HttpClient, document_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from refweave.model import Link
    from refweave.plugins.source.atlassian.jira.api import JiraApi
    from refweave.plugins.source.atlassian.jira.types import BodyFormat, RawIssue
    from refweave.plugins.source.base.elements import StructuralElement

logger = logging.getLogger(__name__)

Tier = Literal["cloud", "dc"]
"""Which Jira deployment `JiraSource` talks to.

`"cloud"` — Atlassian-hosted Jira (`*.atlassian.net`, REST v3).
`"dc"` — self-hosted Data Center / Server (REST v2 + `/rest/api/2` prefix).
Endpoint URLs, auth flavour, and body-format defaults branch on this.
"""

__all__ = ["JiraSource", "Tier"]


class JiraSource:
    """Iterates all issues of the configured projects as `SyncedDocument`s.

    Owns the HTTP client and its lifecycle. Wraps a Cloud v3 or DC v2
    endpoint layer (chosen by `tier`) and produces documents with
    already-extracted but unresolved links; the orchestrator's resolver
    phase fills `target_document` for cross-issue references.
    """

    def __init__(
        self,
        *,
        source_id: str,
        url: str,
        auth: AuthProvider,
        projects: Sequence[str],
        tier: Tier = "cloud",
        path_prefix: str = "",
        rate_limit: float = 10.0,
        concurrency: int = 20,
        max_retries: int = 3,
        link_extractor: LinkExtractor | None = None,
    ) -> None:
        """`path_prefix` — used when the tenant lives under a subpath, e.g.
        Apache's `https://issues.apache.org/jira`. Pass `path_prefix="/jira"`
        and set `url="https://issues.apache.org"` (base_url must be the host
        root so httpx's absolute-path resolution behaves correctly).
        """
        self.source_id = source_id
        self._projects = tuple(projects)
        self._link_extractor = link_extractor or LinkExtractor()
        self._http = HttpClient(
            base_url=url,
            auth=auth,
            rate_limit=rate_limit,
            concurrency=concurrency,
            max_retries=max_retries,
        )
        self._api: JiraApi = (
            CloudApi(self._http, path_prefix=path_prefix)
            if tier == "cloud"
            else DcApi(self._http, path_prefix=path_prefix)
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> JiraSource:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def iter(self) -> AsyncIterator[SyncedDocument]:
        seen: set[str] = set()
        for project_key in self._projects:
            async for issue in self._api.iter_issues(project_key):
                doc_id = document_id(self.source_id, issue.key)
                if doc_id in seen:
                    logger.debug(
                        "jira issue seen twice: doc_id=%s project=%s key=%s",
                        doc_id,
                        project_key,
                        issue.key,
                    )
                    continue
                seen.add(doc_id)
                # `_synced` runs the CPU-heavy pipeline (ADF JSON / wiki
                # markup parse + build_document + link extraction). Offload
                # to a worker thread so the event loop stays responsive
                # between yields — otherwise a corpus of long issues with
                # rich descriptions would stall other async tasks.
                yield await asyncio.to_thread(self._synced, issue)

    def _synced(self, issue: RawIssue) -> SyncedDocument:
        elements = _parse_body(issue.description, issue.description_format)
        document = build_document(issue, elements, source_id=self.source_id)
        links: list[Link] = list(
            self._link_extractor.extract(issue, source_id=self.source_id),
        )
        return SyncedDocument(document=document, links=tuple(links))


def _parse_body(body: str, fmt: BodyFormat) -> tuple[StructuralElement, ...]:
    if fmt == "adf":
        return parse_adf(body)
    return parse_wiki(body)
