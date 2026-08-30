"""Resolves Jira issuelink / subtask / parent references to target document ids.

Two-phase (Resolver Protocol): `prepare` builds a `key → doc_id` index
over the corpus; `resolve` fills `target_document` on unresolved
issue-level links per document.

Jira issue keys are globally unique across a tenant (project prefix +
sequence), so the index is a flat `dict[str, str]` — no need for the
(space, title) tuple keys Confluence uses.

Dead links (target missing from the corpus, typically a cross-project
reference outside the synced set) end with `target_document=None,
resolved=True`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from refweave.plugins.source.atlassian.jira.keys import TARGET_KEY
from refweave.plugins.source.atlassian.jira.link_types import JiraLinkKind
from refweave.plugins.source.base import parse_document_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from refweave.model import Document, Link

_RESOLVABLE_KINDS: Final = frozenset(
    {JiraLinkKind.ISSUE_LINK, JiraLinkKind.SUBTASK, JiraLinkKind.PARENT},
)


class JiraIssueResolver:
    """Resolves cross-issue references within one Jira source."""

    def __init__(self) -> None:
        self._index: dict[str, str] = {}

    async def prepare(self, docs: AsyncIterator[Document]) -> None:
        self._index = {}
        async for doc in docs:
            if doc.sync.deleted_at is not None:
                continue
            _, external = parse_document_id(doc.id)
            self._index[external] = doc.id

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
        target_key = str(link.metadata.get(TARGET_KEY, ""))
        if not target_key:
            return link.model_copy(update={"resolved": True})
        target = self._index.get(target_key)
        return link.model_copy(
            update={"target_document": target, "resolved": True},
        )
