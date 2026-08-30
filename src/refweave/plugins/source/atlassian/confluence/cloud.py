"""Confluence Cloud REST API v2 implementation of ConfluenceApi.

Uses cursor-based pagination through `_links.next`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refweave.plugins.source.atlassian import paginate
from refweave.plugins.source.atlassian.confluence.types import RawPage
from refweave.plugins.source.base import HttpClient, epoch, parse_iso

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_V2 = "/wiki/api/v2"


class CloudApi:
    """Confluence Cloud v2 client, endpoint-aware layer.

    Does not own the http client — whoever passed it in is responsible
    for `aclose`. Multiple api-layer objects can share the same client.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._space_id_cache: dict[str, str] = {}

    async def iter_pages(self, space_key: str) -> AsyncIterator[RawPage]:
        space_id = await self._resolve_space_id(space_key)
        path = f"{_V2}/spaces/{space_id}/pages"
        params: dict[str, Any] = {"body-format": "storage", "limit": 250}
        async for page in paginate(
            self._http,
            path,
            params,
            lambda item: _to_raw_page(item, space_key),
        ):
            yield page

    async def _resolve_space_id(self, space_key: str) -> str:
        cached = self._space_id_cache.get(space_key)
        if cached is not None:
            return cached
        response = await self._http.get(
            f"{_V2}/spaces",
            params={"keys": space_key, "limit": 1},
        )
        results = response.json().get("results") or []
        if not results:
            msg = f"confluence space not found: {space_key}"
            raise LookupError(msg)
        space_id = str(results[0]["id"])
        self._space_id_cache[space_key] = space_id
        return space_id


def _to_raw_page(data: dict[str, Any], space_key: str) -> RawPage:
    body = ((data.get("body") or {}).get("storage") or {}).get("value", "") or ""
    version_obj = data.get("version") or {}
    version_number = int(version_obj.get("number", 0))
    updated_raw = version_obj.get("createdAt")
    updated_at = parse_iso(updated_raw) if updated_raw else epoch()
    labels_data = data.get("labels")
    labels: tuple[str, ...] = ()
    if isinstance(labels_data, dict):
        labels = tuple(
            str(lab.get("name", ""))
            for lab in labels_data.get("results") or []
            if lab.get("name")
        )
    parent_raw = data.get("parentId")
    return RawPage(
        id=str(data["id"]),
        title=str(data.get("title", "")),
        space_key=space_key,
        version=version_number,
        body=body,
        updated_at=updated_at,
        labels=labels,
        parent_id=str(parent_raw) if parent_raw else None,
    )
