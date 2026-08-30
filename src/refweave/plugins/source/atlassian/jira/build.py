"""Turn a RawIssue + parsed description elements into a Document.

Sections are laid out in this order:
    1. Description elements (parsed StructuralElements) — seq 0..N-1.
    2. Comments, one section per comment — seq N..N+M-1, kind=COMMENT.

If both description and comments are empty, a single synthetic paragraph
section carrying the issue summary is generated so links always have a
seq-0 anchor to attach to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refweave.model import Document, Section, SyncState
from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.atlassian.jira.extra import JiraCommentExtra, JiraExtra
from refweave.plugins.source.atlassian.jira.parser_adf import parse_adf
from refweave.plugins.source.atlassian.jira.parser_wiki import parse_wiki
from refweave.plugins.source.base import (
    document_id,
    section_id,
    structural_element_to_section,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from refweave.plugins.source.atlassian.jira.types import BodyFormat, RawComment, RawIssue
    from refweave.plugins.source.base.elements import StructuralElement


def build_document(
    issue: RawIssue,
    elements: Sequence[StructuralElement],
    *,
    source_id: str,
    kind: str | None = None,
) -> Document:
    doc_id = document_id(source_id, issue.key)
    sections: list[Section] = []

    for elt in elements:
        sections.append(
            structural_element_to_section(
                elt,
                doc_id=doc_id,
                sec_id=section_id(source_id, issue.key, len(sections)),
            ),
        )

    for comment in issue.comments:
        sections.append(
            _section_from_comment(
                comment,
                issue.description_format,
                doc_id,
                source_id,
                issue.key,
                len(sections),
            ),
        )

    if not sections:
        sections.append(
            Section(
                id=section_id(source_id, issue.key, 0),
                document=doc_id,
                seq=0,
                kind=SectionKind.PARAGRAPH,
                text=issue.summary,
                raw="",
            ),
        )

    fields: dict[str, Any] = {
        "id": doc_id,
        "title": issue.summary,
        "sections": tuple(sections),
        "sync": SyncState(
            version=int(issue.updated_at.timestamp()),
            updated_at=issue.updated_at,
        ),
        "metadata": _document_metadata(issue, source_id=source_id),
    }
    if kind is not None:
        fields["kind"] = kind
    return Document(**fields)


def _section_from_comment(
    comment: RawComment,
    fmt: BodyFormat,
    doc_id: str,
    source_id: str,
    issue_key: str,
    seq: int,
) -> Section:
    # Comments carry the same body format as the parent issue. Parse to
    # produce a clean plain-text projection; keep the original body in `raw`
    # so LinkExtractor / other downstream code can still mine it.
    parsed = parse_adf(comment.body) if fmt == "adf" else parse_wiki(comment.body)
    text = "\n".join(e.text for e in parsed if e.text).strip() or comment.body
    return Section(
        id=section_id(source_id, issue_key, seq),
        document=doc_id,
        seq=seq,
        kind=ElementKind.COMMENT,
        text=text,
        raw=comment.body,
        metadata=JiraCommentExtra(
            author=comment.author,
            created=comment.created,
        ).write(),
    )


def _document_metadata(issue: RawIssue, *, source_id: str) -> dict[str, Any]:
    extra = JiraExtra(
        project=issue.project,
        issue_type=issue.issue_type,
        status=issue.status,
        priority=issue.priority,
        labels=issue.labels,
        reporter=issue.reporter,
        assignee=issue.assignee,
        parent=document_id(source_id, issue.parent_key) if issue.parent_key else None,
    )
    return extra.write()
