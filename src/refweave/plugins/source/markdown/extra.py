"""Typed view over Markdown-specific `Document.metadata` — see `MarkdownExtra`."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from refweave.plugins.extras import SourceExtra
from refweave.plugins.source.markdown.frontmatter import Format


class MarkdownExtra(SourceExtra):
    """Typed view over Markdown-specific `Document.metadata`.

    `path` — relative POSIX path from the source root (`docs/setup.md`).
    `tags` — pulled from frontmatter `tags:` if present as a list.
    `frontmatter_format` — which frontmatter dialect the parser matched.
    `frontmatter` — remaining frontmatter fields, verbatim, minus keys
        already surfaced elsewhere (`title` goes to Document.title;
        `tags`, `path`, `frontmatter_format` are surfaced via named
        fields). Consumers who need author/date/category/... reach
        into this dict.
    """

    NAMESPACE: ClassVar[str] = "_markdown"

    path: str
    tags: tuple[str, ...] = ()
    frontmatter_format: Format = "none"
    frontmatter: dict[str, Any] = Field(default_factory=dict)
