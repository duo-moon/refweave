"""Jira Data Center / Server REST v2 implementation of JiraApi.

Uses classic `/rest/api/2/search` (GET) with `startAt` / `maxResults` /
`total` pagination. Description bodies come as wiki markup strings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

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

_V2: Final = "/rest/api/2"
_FIELDS: Final = (
    "summary,description,status,priority,issuetype,project,labels,"
    "reporter,assignee,updated,parent,subtasks,issuelinks,comment"
)
_PAGE_SIZE: Final = 100


class DcApi:
    """Jira DC/Server v2 client, endpoint-aware layer.

    Does not own the http client — whoever passed it in is responsible
    for `aclose`.
    """

    def __init__(self, http: HttpClient, *, path_prefix: str = "") -> None:
        self._http = http
        self._prefix = path_prefix.rstrip("/")

    async def iter_issues(self, project_key: str) -> AsyncIterator[RawIssue]:
        start_at = 0
        while True:
            params: dict[str, Any] = {
                "jql": f'project = "{project_key}"',
                "startAt": start_at,
                "maxResults": _PAGE_SIZE,
                "fields": _FIELDS,
            }
            response = await self._http.get(f"{self._prefix}{_V2}/search", params=params)
            data = response.json()
            issues = data.get("issues") or []
            for raw in issues:
                yield _to_raw_issue(raw)
            if not issues:
                return
            total = int(data.get("total", 0))
            start_at += len(issues)
            if start_at >= total:
                return


def _to_raw_issue(data: dict[str, Any]) -> RawIssue:
    fields = data.get("fields") or {}
    description = fields.get("description")
    return RawIssue(
        id=str(data.get("id", "")),
        key=str(data.get("key", "")),
        project=extract_project(fields),
        issue_type=extract_issue_type(fields),
        status=extract_status(fields),
        summary=str(fields.get("summary", "")),
        description=str(description) if description else "",
        description_format="wiki",
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


def _extract_comments(fields: dict[str, Any]) -> tuple[RawComment, ...]:
    comment_block = fields.get("comment") or {}
    comments = comment_block.get("comments") or ()
    total = comment_block.get("total")
    if isinstance(total, int) and total > len(comments):
        logger.debug(
            "jira dc: comments truncated at %d of %d for issue",
            len(comments),
            total,
        )
    out: list[RawComment] = []
    for node in comments:
        if not isinstance(node, dict):
            continue
        author_obj = node.get("author") or {}
        author = str(
            author_obj.get("displayName") or author_obj.get("name") or "",
        )
        created_raw = node.get("created")
        created = parse_iso(str(created_raw)) if created_raw else epoch()
        body = str(node.get("body") or "")
        out.append(RawComment(author=author, created=created, body=body))
    return tuple(out)
