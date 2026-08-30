"""Endpoint-agnostic Protocol for Jira API adapters.

`CloudApi` and `DcApi` both satisfy this. Source-level code depends on
the Protocol; the choice of adapter is made once in `JiraSource.__init__`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from refweave.plugins.source.atlassian.jira.types import RawIssue


@runtime_checkable
class JiraApi(Protocol):
    """Minimal surface: iterate all issues in one project."""

    def iter_issues(self, project_key: str) -> AsyncIterator[RawIssue]: ...
