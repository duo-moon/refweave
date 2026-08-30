"""Jira-scoped ElementKind namespace — source-specific kinds only.

Cross-source generic kinds (HEADING, PARAGRAPH, LIST, TABLE, CODE,
QUOTE, HR, UNKNOWN) live in `refweave.plugins.kinds.SectionKind` and
are used directly by the ADF / wiki parsers and Jira build code. This
module only defines Jira-unique element kinds (panels, comments) — a
namespace, not an Enum.

`StructuralElement` is re-exported here so plugin code can grab both
`ElementKind` and `StructuralElement` from one import.
"""

from __future__ import annotations

from typing import Final

from refweave.plugins.source.base.elements import StructuralElement

__all__ = ["ElementKind", "StructuralElement"]


class ElementKind:
    """Jira-specific `StructuralElement.kind` values.

    Cross-source generic kinds (HEADING/PARAGRAPH/...) — use
    `SectionKind.*` directly.
    """

    PANEL: Final = "panel"  # ADF panel / wiki {info}/{warning}/{note}
    COMMENT: Final = "comment"  # comment body inserted as a section by build
