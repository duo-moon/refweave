"""Markdown-scoped ElementKind namespace — source-specific kinds only.

Cross-source generic kinds (HEADING, PARAGRAPH, LIST, TABLE, CODE,
QUOTE, HR, UNKNOWN) live in `refweave.plugins.kinds.SectionKind` and
are used directly by the Markdown parser and build code. This module
only defines Markdown-unique element kinds — a namespace, not an
Enum.

`StructuralElement` is re-exported here so plugin code can grab both
`ElementKind` and `StructuralElement` from one import.
"""

from __future__ import annotations

from typing import Final

from refweave.plugins.source.base import StructuralElement

__all__ = ["ElementKind", "StructuralElement"]


class ElementKind:
    """Markdown-specific `StructuralElement.kind` values.

    Cross-source generic kinds (HEADING/PARAGRAPH/...) — use
    `SectionKind.*` directly.
    """

    HTML: Final = "html"  # raw HTML blocks embedded in Markdown
