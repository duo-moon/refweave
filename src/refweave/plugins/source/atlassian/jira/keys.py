"""Jira-scoped metadata keys for Link routing.

Document-level attributes (project, status, priority, ...) live on
`JiraExtra`; comment-section attributes live on `JiraCommentExtra`.
This module only carries Link.metadata keys shared between the
LinkExtractor and the Resolver.
"""

from __future__ import annotations

from typing import Final

# Link.metadata keys populated by LinkExtractor.
LINK_TYPE_KEY: Final = "link_type"  # e.g. "blocks", "relates to"
TITLE_KEY: Final = "title"  # target issue summary, for dead-link audit
TARGET_KEY: Final = "target_key"  # "MFS-1234" — resolver looks this up
DIRECTION_KEY: Final = "direction"  # "outward" | "inward" (issuelinks)
