"""Shared field extractors for Jira API adapters.

The Cloud v3 and DC v2 `fields` payloads are structurally identical for
everything except body format (ADF vs wiki) — description and comment
extraction lives in the adapter modules; everything else lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refweave.plugins.source.atlassian.jira.types import RawIssueLink
from refweave.plugins.source.base import epoch, parse_iso

if TYPE_CHECKING:
    from datetime import datetime


def extract_project(fields: dict[str, Any]) -> str:
    project = fields.get("project") or {}
    return str(project.get("key", ""))


def extract_issue_type(fields: dict[str, Any]) -> str:
    issue_type = fields.get("issuetype") or {}
    return str(issue_type.get("name", ""))


def extract_status(fields: dict[str, Any]) -> str:
    status = fields.get("status") or {}
    return str(status.get("name", ""))


def extract_priority(fields: dict[str, Any]) -> str | None:
    priority = fields.get("priority")
    if not isinstance(priority, dict):
        return None
    name = priority.get("name")
    return str(name) if name else None


def extract_labels(fields: dict[str, Any]) -> tuple[str, ...]:
    labels = fields.get("labels") or ()
    return tuple(str(lab) for lab in labels if lab)


def extract_user(fields: dict[str, Any], key: str) -> str | None:
    user = fields.get(key)
    if not isinstance(user, dict):
        return None
    # displayName is the human-facing label; accountId is Cloud-only stable
    # id. We prefer displayName for readability and fall back to accountId /
    # name (DC).
    return (
        str(user.get("displayName") or user.get("accountId") or user.get("name") or "")
        or None
    )


def extract_updated(fields: dict[str, Any]) -> datetime:
    raw = fields.get("updated")
    if not raw:
        return epoch()
    return parse_iso(str(raw))


def extract_parent_key(fields: dict[str, Any]) -> str | None:
    parent = fields.get("parent")
    if not isinstance(parent, dict):
        return None
    key = parent.get("key")
    return str(key) if key else None


def extract_subtask_keys(fields: dict[str, Any]) -> tuple[str, ...]:
    subtasks = fields.get("subtasks") or ()
    return tuple(
        str(st["key"])
        for st in subtasks
        if isinstance(st, dict) and st.get("key")
    )


def extract_issuelinks(fields: dict[str, Any]) -> tuple[RawIssueLink, ...]:
    """Flatten `fields.issuelinks[]` into typed RawIssueLink tuples.

    Each Jira issuelink node has EITHER `outwardIssue` OR `inwardIssue`
    populated (never both). Direction is derived from which one is set.
    `type.name` is the link type name (e.g. "Blocks", "Relates").
    """
    links = fields.get("issuelinks") or ()
    out: list[RawIssueLink] = []
    for node in links:
        if not isinstance(node, dict):
            continue
        link_type = str((node.get("type") or {}).get("name") or "").strip()
        outward = node.get("outwardIssue")
        inward = node.get("inwardIssue")
        if isinstance(outward, dict) and outward.get("key"):
            out.append(
                RawIssueLink(
                    target_key=str(outward["key"]),
                    link_type=link_type,
                    direction="outward",
                ),
            )
        elif isinstance(inward, dict) and inward.get("key"):
            out.append(
                RawIssueLink(
                    target_key=str(inward["key"]),
                    link_type=link_type,
                    direction="inward",
                ),
            )
    return tuple(out)
