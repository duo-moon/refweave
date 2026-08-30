"""Markdown-scoped metadata keys for Link routing.

Document-level attributes (path, tags, frontmatter format, remaining
frontmatter fields) live on the typed `MarkdownExtra` view over
`Document.metadata`. This module only carries Link.metadata keys shared
between the LinkExtractor and the Resolver.
"""

from __future__ import annotations

from typing import Final

# Link.metadata keys populated by LinkExtractor.
HREF_KEY: Final = "href"  # raw href as written, e.g. "./other.md#anchor"
TARGET_PATH_KEY: Final = "target_path"  # normalized relative path for resolver
TITLE_KEY: Final = "title"  # visible link text
