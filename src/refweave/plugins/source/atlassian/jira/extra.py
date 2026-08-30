"""Typed views over Jira-specific metadata surfaces.

`JiraExtra` — one per issue, attached to `Document.metadata`.

`JiraCommentExtra` — one per comment section, attached to
`Section.metadata` on sections with kind == COMMENT.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from refweave.plugins.extras import SourceExtra


class JiraExtra(SourceExtra):
    """Issue-level attributes surfaced on `Document.metadata`.

    `parent` — when present, the *doc id* of the parent issue (already
    namespaced by source), not the raw Jira key.
    """

    NAMESPACE: ClassVar[str] = "_jira"

    project: str
    issue_type: str
    status: str
    priority: str | None = None
    labels: tuple[str, ...] = ()
    reporter: str | None = None
    assignee: str | None = None
    parent: str | None = None


class JiraCommentExtra(SourceExtra):
    """Attributes for comment sections, surfaced on `Section.metadata`."""

    NAMESPACE: ClassVar[str] = "_jira_comment"

    author: str
    created: datetime
