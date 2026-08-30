"""Confluence Data Center / Server REST API v1 implementation of ConfluenceApi.

Uses offset/limit pagination (via `_links.next`). Space keys are used
directly by v1 endpoints — no key→id translation needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from refweave.plugins.source.atlassian import paginate
from refweave.plugins.source.atlassian.confluence.types import RawPage
from refweave.plugins.source.base import HttpClient, epoch, parse_iso

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_V1: Final = "/rest/api"
_EXPAND: Final = "body.storage,version,ancestors,metadata.labels,space"


class DcApi:
    """Confluence DC/Server v1 client, endpoint-aware layer.

    Does not own the http client — whoever passed it in is responsible
    for `aclose`. Multiple api-layer objects can share the same client.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def iter_pages(self, space_key: str) -> AsyncIterator[RawPage]:
        path = f"{_V1}/space/{space_key}/content/page"
        params: dict[str, Any] = {"expand": _EXPAND, "start": 0, "limit": 100}
        async for page in paginate(self._http, path, params, _to_raw_page):
            yield page


def _to_raw_page(data: dict[str, Any]) -> RawPage:
    space = data.get("space") or {}
    space_key = str(space.get("key", ""))
    body = ((data.get("body") or {}).get("storage") or {}).get("value", "") or ""
    version_obj = data.get("version") or {}
    version_number = int(version_obj.get("number", 0))
    updated_raw = version_obj.get("when")
    updated_at = parse_iso(updated_raw) if updated_raw else epoch()
    metadata = data.get("metadata") or {}
    labels_block = metadata.get("labels") or {}
    labels = tuple(
        str(lab.get("name", "")) for lab in labels_block.get("results") or [] if lab.get("name")
    )
    ancestors_data = data.get("ancestors") or []
    parent_id: str | None = None
    for candidate in reversed(ancestors_data):
        if candidate.get("id"):
            parent_id = str(candidate["id"])
            break
    return RawPage(
        id=str(data["id"]),
        title=str(data.get("title", "")),
        space_key=space_key,
        version=version_number,
        body=body,
        updated_at=updated_at,
        labels=labels,
        parent_id=parent_id,
    )
