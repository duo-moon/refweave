"""Tests for LinkExtractor (Jira issue-level references)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from refweave.plugins.source.atlassian.jira import (
    DIRECTION_KEY,
    LINK_TYPE_KEY,
    TARGET_KEY,
    JiraLinkKind,
)
from refweave.plugins.source.atlassian.jira.links import LinkExtractor
from refweave.plugins.source.atlassian.jira.types import RawIssue, RawIssueLink


def _issue(**overrides: Any) -> RawIssue:
    base: dict[str, Any] = {
        "id": "1",
        "key": "MFS-1",
        "project": "MFS",
        "issue_type": "Task",
        "status": "Open",
        "summary": "Title",
        "description": "",
        "description_format": "wiki",
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return RawIssue(**base)


def test_no_edges_yields_no_links() -> None:
    links = list(LinkExtractor().extract(_issue(), source_id="acme"))
    assert links == []


def test_issuelinks_carry_kind_direction_and_type() -> None:
    issue = _issue(
        issuelinks=(
            RawIssueLink(target_key="MFS-99", link_type="Blocks", direction="outward"),
            RawIssueLink(target_key="MFS-10", link_type="Relates", direction="inward"),
        ),
    )
    links = list(LinkExtractor().extract(issue, source_id="acme"))
    assert [link.kind for link in links] == [JiraLinkKind.ISSUE_LINK] * 2
    assert links[0].metadata[LINK_TYPE_KEY] == "Blocks"
    assert links[0].metadata[TARGET_KEY] == "MFS-99"
    assert links[0].metadata[DIRECTION_KEY] == "outward"
    assert links[1].metadata[DIRECTION_KEY] == "inward"


def test_subtasks_produce_subtask_links() -> None:
    issue = _issue(subtask_keys=("MFS-2", "MFS-3"))
    links = list(LinkExtractor().extract(issue, source_id="acme"))
    assert [link.kind for link in links] == [JiraLinkKind.SUBTASK] * 2
    assert [link.metadata[TARGET_KEY] for link in links] == ["MFS-2", "MFS-3"]


def test_parent_produces_parent_link() -> None:
    issue = _issue(parent_key="MFS-0")
    links = list(LinkExtractor().extract(issue, source_id="acme"))
    assert len(links) == 1
    assert links[0].kind == JiraLinkKind.PARENT
    assert links[0].metadata[TARGET_KEY] == "MFS-0"


def test_all_links_rooted_in_section_zero() -> None:
    issue = _issue(
        issuelinks=(RawIssueLink(target_key="MFS-99", link_type="Blocks", direction="outward"),),
        subtask_keys=("MFS-2",),
        parent_key="MFS-0",
    )
    links = list(LinkExtractor().extract(issue, source_id="acme"))
    assert all(link.section == "sec:acme:MFS-1:0" for link in links)


def test_link_ids_are_contiguous_from_zero() -> None:
    issue = _issue(
        issuelinks=(RawIssueLink(target_key="MFS-99", link_type="Blocks", direction="outward"),),
        subtask_keys=("MFS-2",),
        parent_key="MFS-0",
    )
    links = list(LinkExtractor().extract(issue, source_id="acme"))
    assert [link.seq for link in links] == [0, 1, 2]
    assert links[0].id == "lnk:acme:MFS-1:0:0"
    assert links[2].id == "lnk:acme:MFS-1:0:2"


def test_no_target_anchor_and_unresolved() -> None:
    issue = _issue(
        issuelinks=(RawIssueLink(target_key="MFS-99", link_type="Blocks", direction="outward"),),
    )
    link = next(iter(LinkExtractor().extract(issue, source_id="acme")))
    assert link.target_anchor is None
    assert link.resolved is False
    assert link.target_document is None
