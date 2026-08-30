"""Well-known kinds for Markdown Link edges."""

from __future__ import annotations

from typing import Final


class MarkdownLinkKind:
    """Namespace for `Link.kind` values that `MarkdownSource` produces.

    A namespace, not an Enum — custom extractors may produce their own
    kind strings without extending the core type.
    """

    INTERNAL: Final = "internal"  # relative path to another MD file in corpus
    EXTERNAL: Final = "external"  # http/https/mailto/... URL
