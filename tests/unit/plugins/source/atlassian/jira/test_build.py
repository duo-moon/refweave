"""Tests for build_document — Jira issue → refweave Document."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from refweave.plugins.keys import HEADING_LEVEL_KEY
from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.build import build_document
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.atlassian.jira.extra import JiraCommentExtra, JiraExtra
from refweave.plugins.source.atlassian.jira.types import RawComment, RawIssue
from refweave.plugins.source.base.elements import StructuralElement

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _issue(**overrides: Any) -> RawIssue:
    base: dict[str, Any] = {
        "id": "1",
        "key": "MFS-1",
        "project": "MFS",
        "issue_type": "Task",
        "status": "Open",
        "summary": "Fix login",
        "description": "",
        "description_format": "wiki",
        "updated_at": _NOW,
    }
    base.update(overrides)
    return RawIssue(**base)


def _elt(seq: int, kind: str, text: str = "body", **extra: Any) -> StructuralElement:
    return StructuralElement(seq=seq, kind=kind, text=text, raw="", **extra)


def test_title_matches_issue_summary() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    assert doc.title == "Fix login"


def test_document_id_uses_issue_key() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    assert doc.id == "doc:acme:MFS-1"


def test_sync_version_is_updated_at_timestamp() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    assert doc.sync.version == int(_NOW.timestamp())
    assert doc.sync.updated_at == _NOW


def test_required_metadata_always_present() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    extra = JiraExtra.read(doc.metadata)
    assert extra is not None
    assert extra.project == "MFS"
    assert extra.issue_type == "Task"
    assert extra.status == "Open"


def test_optional_metadata_populated_conditionally() -> None:
    doc = build_document(
        _issue(
            priority="High",
            labels=("auth", "sec"),
            reporter="Alice",
            assignee="Bob",
            parent_key="MFS-0",
        ),
        (),
        source_id="acme",
    )
    extra = JiraExtra.read(doc.metadata)
    assert extra is not None
    assert extra.priority == "High"
    assert extra.labels == ("auth", "sec")
    assert extra.reporter == "Alice"
    assert extra.assignee == "Bob"
    assert extra.parent == "doc:acme:MFS-0"


def test_optional_metadata_absent_when_source_absent() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    extra = JiraExtra.read(doc.metadata)
    assert extra is not None
    assert extra.priority is None
    assert extra.labels == ()
    assert extra.reporter is None
    assert extra.assignee is None
    assert extra.parent is None


def test_metadata_shape_is_only_the_extra_namespace() -> None:
    doc = build_document(_issue(), (), source_id="acme")
    assert set(doc.metadata.keys()) == {JiraExtra.NAMESPACE}


def test_sections_from_elements_come_first() -> None:
    elements = (
        _elt(0, SectionKind.HEADING, text="Overview", heading_level=2),
        _elt(1, SectionKind.PARAGRAPH, text="Body"),
    )
    doc = build_document(_issue(), elements, source_id="acme")
    assert len(doc.sections) == 2
    assert doc.sections[0].kind == SectionKind.HEADING
    assert doc.sections[0].metadata[HEADING_LEVEL_KEY] == 2
    assert doc.sections[1].kind == SectionKind.PARAGRAPH


def test_comment_sections_follow_description() -> None:
    elements = (_elt(0, SectionKind.PARAGRAPH, text="Description body"),)
    doc = build_document(
        _issue(
            comments=(
                RawComment(author="Alice", created=_NOW, body="First comment"),
                RawComment(author="Bob", created=_NOW, body="Second"),
            ),
        ),
        elements,
        source_id="acme",
    )
    assert len(doc.sections) == 3
    assert doc.sections[0].kind == SectionKind.PARAGRAPH
    assert doc.sections[1].kind == ElementKind.COMMENT
    alice = JiraCommentExtra.read(doc.sections[1].metadata)
    bob = JiraCommentExtra.read(doc.sections[2].metadata)
    assert alice is not None
    assert bob is not None
    assert alice.author == "Alice"
    assert alice.created == _NOW
    assert bob.author == "Bob"


def test_fallback_section_when_description_and_comments_empty() -> None:
    doc = build_document(_issue(summary="Just a title"), (), source_id="acme")
    assert len(doc.sections) == 1
    assert doc.sections[0].kind == SectionKind.PARAGRAPH
    assert doc.sections[0].text == "Just a title"
    assert doc.sections[0].seq == 0


def test_section_ids_are_contiguous_from_zero() -> None:
    doc = build_document(
        _issue(comments=(RawComment(author="A", created=_NOW, body="c1"),)),
        (_elt(0, SectionKind.PARAGRAPH),),
        source_id="acme",
    )
    assert [s.seq for s in doc.sections] == [0, 1]
    assert doc.sections[0].id == "sec:acme:MFS-1:0"
    assert doc.sections[1].id == "sec:acme:MFS-1:1"


def test_kind_override_flows_through() -> None:
    doc = build_document(_issue(), (), source_id="acme", kind="bug")
    assert doc.kind == "bug"


def test_comment_body_gets_plain_text_projection() -> None:
    # Wiki-format comment with markup — build parses it and stores plain text.
    doc = build_document(
        _issue(
            comments=(
                RawComment(
                    author="Alice",
                    created=_NOW,
                    body="See [MFS-42] for *important* details.",
                ),
            ),
        ),
        (),
        source_id="acme",
    )
    # No description elements + 1 comment → 1 section (the comment) at index 0.
    comment_section = doc.sections[0]
    assert comment_section.kind == ElementKind.COMMENT
    assert comment_section.text == "See MFS-42 for important details."
    assert comment_section.raw == "See [MFS-42] for *important* details."
