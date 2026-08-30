"""Well-known kinds for Jira Link edges."""

from __future__ import annotations

from typing import Final


class JiraLinkKind:
    """Namespace for `Link.kind` values that `JiraSource` produces.

    A namespace, not an Enum — custom extractors may produce their own
    kind strings without extending the core type.
    """

    ISSUE_LINK: Final = "issue_link"  # typed edge (blocks, relates to, ...)
    SUBTASK: Final = "subtask"  # parent → subtask edge
    PARENT: Final = "parent"  # subtask → parent edge
