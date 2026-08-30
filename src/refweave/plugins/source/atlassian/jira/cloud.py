"""Jira Cloud REST v3 implementation of JiraApi.

Uses the enhanced `/rest/api/3/search/jql` endpoint (POST) with
`nextPageToken`-based cursor pagination — Atlassian's replacement for
the older `startAt`-based `/search`, which is deprecated on Cloud.

Description bodies come as ADF (Atlassian Document Format) — nested JSON
trees. We serialize each body to a JSON string for `RawIssue`; the
downstream ADF parser deserializes on the way out.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from refweave.plugins.source.atlassian.jira._mapping import (
    extract_issue_type,
    extract_issuelinks,
    extract_labels,
    extract_parent_key,
    extract_priority,
    extract_project,
    extract_status,
    extract_subtask_keys,
    extract_updated,
    extract_user,
)
from refweave.plugins.source.atlassian.jira.types import (
    RawComment,
    RawIssue,
)
from refweave.plugins.source.base import HttpClient, epoch, parse_iso

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_V3 = "/rest/api/3"
_FIELDS: tuple[str, ...] = (
    "summary",
    "description",
    "status",
    "priority",
    "issuetype",
    "project",
    "labels",
    "reporter",
    "assignee",
    "updated",
    "parent",
    "subtasks",
    "issuelinks",
    "comment",
)


class CloudApi:
    """Jira Cloud v3 client, endpoint-aware layer.

    Does not own the http client — whoever passed it in is responsible
    for `aclose`. Multiple api-layer objects can share the same client.
    """

    def __init__(self, http: HttpClient, *, path_prefix: str = "") -> None:
        self._http = http
        self._prefix = path_prefix.rstrip("/")

    async def iter_issues(self, project_key: str) -> AsyncIterator[RawIssue]:
        payload: dict[str, Any] = {
            "jql": f'project = "{project_key}"',
            "fields": list(_FIELDS),
        }
        next_token: str | None = None
        while True:
            body = {**payload}
            if next_token is not None:
                body["nextPageToken"] = next_token
            response = await self._http.post(f"{self._prefix}{_V3}/search/jql", json=body)
            data = response.json()
            for raw in data.get("issues") or []:
                yield _to_raw_issue(raw)
            if data.get("isLast", True):
                return
            next_token = data.get("nextPageToken")
            if not next_token:
                return


def _to_raw_issue(data: dict[str, Any]) -> RawIssue:
    fields = data.get("fields") or {}
    return RawIssue(
        id=str(data.get("id", "")),
        key=str(data.get("key", "")),
        project=extract_project(fields),
        issue_type=extract_issue_type(fields),
        status=extract_status(fields),
        summary=str(fields.get("summary", "")),
        description=_serialize_adf(fields.get("description")),
        description_format="adf",
        updated_at=extract_updated(fields),
        priority=extract_priority(fields),
        reporter=extract_user(fields, "reporter"),
        assignee=extract_user(fields, "assignee"),
        parent_key=extract_parent_key(fields),
        comments=_extract_comments(fields),
        issuelinks=extract_issuelinks(fields),
        subtask_keys=extract_subtask_keys(fields),
        labels=extract_labels(fields),
    )


def _serialize_adf(body: Any) -> str:
    """ADF bodies come as JSON dicts; store as string so RawIssue stays flat."""
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    return json.dumps(body, ensure_ascii=False)


def _extract_comments(fields: dict[str, Any]) -> tuple[RawComment, ...]:
    comment_block = fields.get("comment") or {}
    comments = comment_block.get("comments") or ()
    total = comment_block.get("total")
    if isinstance(total, int) and total > len(comments):
        logger.debug(
            "jira cloud: comments truncated at %d of %d for issue (page through "
            "/issue/{id}/comment if you need all)",
            len(comments),
            total,
        )
    out: list[RawComment] = []
    for node in comments:
        if not isinstance(node, dict):
            continue
        author_obj = node.get("author") or {}
        author = str(
            author_obj.get("displayName")
            or author_obj.get("accountId")
            or author_obj.get("name")
            or "",
        )
        created_raw = node.get("created")
        created = parse_iso(str(created_raw)) if created_raw else epoch()
        body = _serialize_adf(node.get("body"))
        out.append(RawComment(author=author, created=created, body=body))
    return tuple(out)
