"""Confluence-specific link kinds."""

from __future__ import annotations

from typing import Final


class ConfluenceLinkKind:
    """Namespace of Confluence link-kind strings. `Link.kind` accepts any
    string; these are the well-known values Confluence emits.
    """

    PAGE: Final = "page"
    ATTACHMENT: Final = "attachment"
    USER: Final = "user"
    EXTERNAL: Final = "external"
    JIRA: Final = "jira"
    INCLUDE: Final = "include"
