"""Cross-source vocabulary for `Section.kind` and related groupings.

`SectionKind` names the structural categories that every built-in source
plugin produces with the same string value. Chunker rules default to
these constants — no magic strings in rule code. Source plugins that
produce equivalent content should use the same values; product-specific
categories (macros, panels, includes, ...) belong in the plugin's local
`ElementKind` namespace and never leak here.

Named groupings (`ATOMIC_KINDS`, ...) sit alongside as small, explicit
sets that rules default to. Adding a value to a grouping is a soft
behavior change for consumers relying on the default — treat it as a
release-notable event even though it doesn't move a type signature.
"""

from __future__ import annotations

from typing import Final


class SectionKind:
    """Well-known `Section.kind` values shared across source plugins.

    A namespace, not an Enum — source plugins are free to produce
    additional strings for product-specific structural elements. These
    constants document the cross-source contract that chunker rules
    consume.
    """

    HEADING: Final = "heading"
    PARAGRAPH: Final = "paragraph"
    LIST: Final = "list"
    TABLE: Final = "table"
    CODE: Final = "code"
    QUOTE: Final = "quote"
    HR: Final = "hr"
    UNKNOWN: Final = "unknown"


ATOMIC_KINDS: Final = frozenset({SectionKind.CODE, SectionKind.TABLE})
"""Section kinds treated as indivisible content blocks by default.

`AtomicBlockRule` uses this set to decide when an incoming section
should preserve adjacency with a small preceding buffer. Consumers who
want to widen or narrow the set pass their own tuple to the rule.
"""
