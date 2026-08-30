"""Confluence-scoped ElementKind namespace — source-specific kinds only.

Cross-source generic kinds (HEADING, PARAGRAPH, LIST, TABLE, CODE,
QUOTE, HR, UNKNOWN) live in `refweave.plugins.kinds.SectionKind` and
are used directly by the Confluence parser + build code. This module
only defines Confluence-unique element kinds (macros, page includes,
anchors) — a namespace, not an Enum, so custom macro handlers can
produce their own kind strings without extending the core type.

`StructuralElement` is re-exported here so plugin code can grab both
`ElementKind` and `StructuralElement` from one import.
"""

from __future__ import annotations

from typing import Final

from refweave.plugins.source.base.elements import StructuralElement

__all__ = ["ElementKind", "StructuralElement"]


class ElementKind:
    """Confluence-specific `StructuralElement.kind` values.

    Cross-source generic kinds (HEADING/PARAGRAPH/...) — use
    `SectionKind.*` directly.
    """

    CALLOUT: Final = "callout"
    EXPAND: Final = "expand"
    ANCHOR: Final = "anchor"
    INCLUDE_PAGE: Final = "include_page"
