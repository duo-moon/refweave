"""Markdown-file source plugin.

Reads `.md` files from a `RawFileProvider` — filesystem tree
(`LocalDirectoryProvider`) or remote git repo (`GitCloneProvider`).
Consumers can supply their own provider for other backends (S3,
in-memory, VCS API).
"""

from refweave.plugins.source.markdown.extra import MarkdownExtra
from refweave.plugins.source.markdown.link_types import MarkdownLinkKind
from refweave.plugins.source.markdown.providers import (
    GitCloneProvider,
    LocalDirectoryProvider,
    RawFileProvider,
)
from refweave.plugins.source.markdown.resolver import MarkdownFileResolver
from refweave.plugins.source.markdown.source import MarkdownSource

__all__ = [
    "GitCloneProvider",
    "LocalDirectoryProvider",
    "MarkdownExtra",
    "MarkdownFileResolver",
    "MarkdownLinkKind",
    "MarkdownSource",
    "RawFileProvider",
]
