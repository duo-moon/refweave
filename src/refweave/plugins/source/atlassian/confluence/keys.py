"""Confluence-scoped metadata keys.

Shared vocabulary between the parts of the Confluence plugin that write
and read Link metadata (build, links, resolver).

Document-level attributes (space, labels, parent) live on the typed
`ConfluenceExtra` view over `Document.metadata`, not here.
"""

from __future__ import annotations

from typing import Final

# Link.metadata keys populated by LinkExtractor.
SPACE_KEY: Final = "space"  # target page's space key
TITLE_KEY: Final = "title"  # target page title, used for (space, title) lookup
