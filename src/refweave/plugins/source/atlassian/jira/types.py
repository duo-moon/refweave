"""Raw types produced by the Jira API layer.

The wire-format-agnostic view that the API adapters (`cloud.py`, `dc.py`)
converge on and feed to `parser` / `build` / `links`. Description bodies
carry a `format` tag so the right parser can be picked downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

BodyFormat = Literal["adf", "wiki"]


@dataclass(frozen=True, slots=True)
class RawComment:
    """One comment on an issue.

    `body` is the raw format described by the parent RawIssue's
    `description_format` — ADF JSON string on Cloud, wiki markup on DC.
    """

    author: str
    created: datetime
    body: str


@dataclass(frozen=True, slots=True)
class RawIssueLink:
    """One issuelink edge.

    Jira reports issuelinks with a direction (outward = "this blocks X",
    inward = "X is blocked by this"). We keep both — build normalizes to
    a single Link kind but preserves `link_type` + `direction` in
    metadata so consumers can distinguish.
    """

    target_key: str  # "MFS-1234"
    link_type: str  # "blocks", "relates to", "duplicates", ...
    direction: Literal["outward", "inward"]


@dataclass(frozen=True, slots=True)
class RawIssue:
    """One issue snapshot pulled from the Jira REST API.

    `key` (e.g. "MFS-1234") is used as `<external>` in `document_id`; it
    is the human-facing cross-reference identifier that appears in
    issuelinks and inline mentions. `id` is Jira's internal numeric id —
    retained for traceability but not used for correlation.

    `description_format` picks the parser: 'adf' for Cloud (description
    is a JSON-serialized ADF tree), 'wiki' for DC (Jira wiki markup).
    Comments share the same format as their parent issue.

    `updated_at` provides sync-version semantics: refweave's SyncState
    stores it as `int(updated_at.timestamp())` so re-sync can detect
    unchanged issues without touching them.
    """

    id: str
    key: str
    project: str
    issue_type: str
    status: str
    summary: str
    description: str
    description_format: BodyFormat
    updated_at: datetime
    priority: str | None = None
    reporter: str | None = None
    assignee: str | None = None
    parent_key: str | None = None
    comments: tuple[RawComment, ...] = ()
    issuelinks: tuple[RawIssueLink, ...] = ()
    subtask_keys: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
