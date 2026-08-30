"""Extract Link edges from a RawIssue.

Jira issue-level references (issuelinks, subtasks, parent) don't belong
to any particular section of the description — they live on the issue
itself. We attach them all to section 0 of the built Document, which
`build.py` guarantees exists (falling back to a synthetic summary
section when description and comments are both empty).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refweave.model import Link
from refweave.plugins.source.atlassian.jira.keys import (
    DIRECTION_KEY,
    LINK_TYPE_KEY,
    TARGET_KEY,
)
from refweave.plugins.source.atlassian.jira.link_types import JiraLinkKind
from refweave.plugins.source.base import document_id, link_id, section_id

if TYPE_CHECKING:
    from collections.abc import Iterator

    from refweave.plugins.source.atlassian.jira.types import RawIssue


class LinkExtractor:
    """Stateless — takes a RawIssue, yields Link edges rooted in section 0."""

    def extract(
        self,
        issue: RawIssue,
        *,
        source_id: str,
        section_seq: int = 0,
    ) -> Iterator[Link]:
        doc_id = document_id(source_id, issue.key)
        sec_id = section_id(source_id, issue.key, section_seq)
        ctx = _Ctx(
            source_id=source_id,
            external=issue.key,
            doc_id=doc_id,
            section_id_=sec_id,
            section_seq=section_seq,
        )
        seq = 0
        for il in issue.issuelinks:
            yield _link(
                ctx,
                seq=seq,
                kind=JiraLinkKind.ISSUE_LINK,
                metadata={
                    LINK_TYPE_KEY: il.link_type,
                    TARGET_KEY: il.target_key,
                    DIRECTION_KEY: il.direction,
                },
            )
            seq += 1
        for target_key in issue.subtask_keys:
            yield _link(
                ctx,
                seq=seq,
                kind=JiraLinkKind.SUBTASK,
                metadata={TARGET_KEY: target_key},
            )
            seq += 1
        if issue.parent_key:
            yield _link(
                ctx,
                seq=seq,
                kind=JiraLinkKind.PARENT,
                metadata={TARGET_KEY: issue.parent_key},
            )


class _Ctx:
    """Carrier for per-link identity data — reduces argument fanout."""

    __slots__ = ("doc_id", "external", "section_id_", "section_seq", "source_id")

    def __init__(
        self,
        *,
        source_id: str,
        external: str,
        doc_id: str,
        section_id_: str,
        section_seq: int,
    ) -> None:
        self.source_id = source_id
        self.external = external
        self.doc_id = doc_id
        self.section_id_ = section_id_
        self.section_seq = section_seq


def _link(
    ctx: _Ctx,
    *,
    seq: int,
    kind: str,
    metadata: dict[str, Any],
) -> Link:
    return Link(
        id=link_id(ctx.source_id, ctx.external, ctx.section_seq, seq),
        document=ctx.doc_id,
        section=ctx.section_id_,
        seq=seq,
        kind=kind,
        target_anchor=None,
        resolved=False,
        metadata=metadata,
    )
