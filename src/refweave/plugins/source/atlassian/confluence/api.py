"""Endpoint-agnostic contract for Confluence data access.

Two implementations ship:
    * CloudApi — Confluence Cloud REST API v2 (cursor pagination)
    * DcApi    — Confluence DC/Server REST API v1 (offset pagination)

Both consume an `HttpClient` for transport (auth, retries, rate limits).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from refweave.plugins.source.atlassian.confluence.types import RawPage


@runtime_checkable
class ConfluenceApi(Protocol):
    """Uniform interface over Cloud v2 and DC v1 endpoints.

    Implementations do not own the underlying http client — the caller
    that constructed the client is responsible for closing it.
    """

    def iter_pages(self, space_key: str) -> AsyncIterator[RawPage]: ...
