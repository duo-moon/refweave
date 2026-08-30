"""Detect Confluence headings that mark navigation blocks (see also / etc.).

Regex-based text matching lives here, not in the chunker. Downstream
navigation classification reads a metadata flag on Section — this module
sets that flag when a heading text matches one of the configured
patterns.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_NAVIGATION_HEADINGS: tuple[str, ...] = (
    r"what'?s?\s*next",
    r"see\s+also",
    r"related(\s+(topics|links|articles))?",
    r"further\s+reading",
    r"дальше",
    r"см\.?\s*также",
    r"см\.?\s*ещё",
    r"по\s+теме",
)


class NavigationHeadingDetector:
    """Matches heading text against a configurable list of navigation patterns.

    Passing `patterns=None` (default) uses `DEFAULT_NAVIGATION_HEADINGS`;
    passing an empty iterable is rejected because the resulting empty
    alternation would silently match every heading — the opposite of
    what a consumer clearing the list expects. To disable navigation
    detection, don't attach a detector at all.
    """

    def __init__(self, patterns: Iterable[str] | None = None) -> None:
        used = tuple(patterns) if patterns is not None else DEFAULT_NAVIGATION_HEADINGS
        if not used:
            msg = (
                "NavigationHeadingDetector requires at least one pattern; "
                "empty patterns produce an alternation that matches every "
                "heading. Omit the detector entirely to disable navigation "
                "detection."
            )
            raise ValueError(msg)
        self._pattern = re.compile(
            r"^\s*(?:" + "|".join(used) + r")[\s:?!.]*$",
            re.IGNORECASE,
        )

    def is_navigation(self, heading_text: str) -> bool:
        return bool(self._pattern.match(heading_text))
