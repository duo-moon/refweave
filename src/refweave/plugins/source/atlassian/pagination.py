"""Cursor/offset pagination via the `_links.next` convention.

Used by Confluence (Cloud v2 and DC v1) and Jira REST endpoints that
return a `_links.next` cursor or offset URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from refweave.plugins.source.base import HttpClient

_T = TypeVar("_T")


async def paginate(
    http: HttpClient,
    path: str,
    params: dict[str, Any],
    map_fn: Callable[[dict[str, Any]], _T],
) -> AsyncIterator[_T]:
    """Follow `_links.next` pagination, yielding mapped items."""
    current_path: str | None = path
    current_params: dict[str, Any] | None = params
    while current_path is not None:
        response = await http.get(current_path, params=current_params)
        payload = response.json()
        for item in payload.get("results") or []:
            yield map_fn(item)
        current_path = next_link(payload)
        # `_links.next` URL carries its own query — don't re-append original params.
        current_params = None


def next_link(payload: dict[str, Any]) -> str | None:
    """Extract the `_links.next` path (with query), or None if last page."""
    links = payload.get("_links") or {}
    next_url = links.get("next")
    if not next_url:
        return None
    parsed = urlparse(next_url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
