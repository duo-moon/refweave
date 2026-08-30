"""Confluence source plugin: source + resolver + typed metadata."""

from refweave.plugins.source.atlassian.confluence.extra import ConfluenceExtra
from refweave.plugins.source.atlassian.confluence.keys import SPACE_KEY, TITLE_KEY
from refweave.plugins.source.atlassian.confluence.link_types import ConfluenceLinkKind
from refweave.plugins.source.atlassian.confluence.resolver import ConfluencePageResolver
from refweave.plugins.source.atlassian.confluence.source import ConfluenceSource, Tier

__all__ = [
    "SPACE_KEY",
    "TITLE_KEY",
    "ConfluenceExtra",
    "ConfluenceLinkKind",
    "ConfluencePageResolver",
    "ConfluenceSource",
    "Tier",
]
