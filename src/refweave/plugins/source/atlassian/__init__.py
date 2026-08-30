"""Shared infrastructure for Atlassian plugins (Confluence, Jira)."""

from refweave.plugins.source.atlassian.auth import ApiTokenAuth, NoAuth, PatAuth
from refweave.plugins.source.atlassian.pagination import next_link, paginate

__all__ = [
    "ApiTokenAuth",
    "NoAuth",
    "PatAuth",
    "next_link",
    "paginate",
]
