"""Resolves Confluence page/include/attachment links to target document ids.

Two-phase (Resolver Protocol): `prepare` builds a `(space, title) → doc_id`
index over the corpus; `resolve` fills `target_document` on unresolved
page/include/attachment links per document.

Dead links (target missing from the corpus) end with `target_document=None,
resolved=True` — no graph edge, no reprocessing until raw links regenerate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from refweave.plugins.source.atlassian.confluence.extra import ConfluenceExtra
from refweave.plugins.source.atlassian.confluence.keys import SPACE_KEY, TITLE_KEY
from refweave.plugins.source.atlassian.confluence.link_types import ConfluenceLinkKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from refweave.model import Document, Link

_RESOLVABLE_KINDS: Final = frozenset(
    {
        ConfluenceLinkKind.PAGE,
        ConfluenceLinkKind.INCLUDE,
        ConfluenceLinkKind.ATTACHMENT,
    },
)


class ConfluencePageResolver:
    """Resolves cross-page references within one Confluence source."""

    def __init__(self) -> None:
        self._index: dict[tuple[str, str], str] = {}

    async def prepare(self, docs: AsyncIterator[Document]) -> None:
        self._index = {}
        async for doc in docs:
            if doc.sync.deleted_at is not None:
                continue
            extra = ConfluenceExtra.read(doc.metadata)
            if extra is None or not extra.space:
                continue
            self._index[(extra.space, doc.title)] = doc.id

    def resolve(self, doc: Document, links: Sequence[Link]) -> Sequence[Link]:
        del doc
        updated: list[Link] = []
        changed = False
        for link in links:
            new_link = self._resolve(link)
            if new_link is not link:
                changed = True
            updated.append(new_link)
        return updated if changed else links

    def _resolve(self, link: Link) -> Link:
        if link.resolved:
            return link
        if link.kind not in _RESOLVABLE_KINDS:
            return link
        space = str(link.metadata.get(SPACE_KEY, ""))
        title = str(link.metadata.get(TITLE_KEY, ""))
        if not space or not title:
            return link.model_copy(update={"resolved": True})
        target = self._index.get((space, title))
        return link.model_copy(update={"target_document": target, "resolved": True})
