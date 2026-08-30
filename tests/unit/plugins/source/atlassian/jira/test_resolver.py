"""Tests for JiraIssueResolver — prepare + resolve contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Document, Link, Section, SyncState
from refweave.plugins.source.atlassian.jira import (
    TARGET_KEY,
    JiraIssueResolver,
    JiraLinkKind,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _doc(source: str, key: str, *, deleted: bool = False) -> Document:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Document(
        id=f"doc:{source}:{key}",
        title=key,
        sections=(
            Section(
                id=f"sec:{source}:{key}:0",
                document=f"doc:{source}:{key}",
                seq=0,
                kind="paragraph",
                text="",
                raw="",
            ),
        ),
        sync=SyncState(
            version=1,
            updated_at=now,
            deleted_at=now if deleted else None,
        ),
    )


async def _stream(*docs: Document) -> AsyncIterator[Document]:
    for d in docs:
        yield d


def _link(kind: str, target_key: str, *, resolved: bool = False) -> Link:
    return Link(
        id=f"lnk:acme:MFS-1:0:{hash(target_key) % 1000}",
        document="doc:acme:MFS-1",
        section="sec:acme:MFS-1:0",
        seq=0,
        kind=kind,
        target_anchor=None,
        resolved=resolved,
        metadata={TARGET_KEY: target_key},
    )


@pytest.mark.asyncio
async def test_prepare_builds_key_to_doc_index():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1"), _doc("acme", "MFS-2")))
    doc = _doc("acme", "MFS-1")
    links = [_link(JiraLinkKind.PARENT, "MFS-2")]
    result = resolver.resolve(doc, links)
    assert result[0].target_document == "doc:acme:MFS-2"
    assert result[0].resolved is True


@pytest.mark.asyncio
async def test_prepare_skips_deleted_docs():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-2", deleted=True)))
    doc = _doc("acme", "MFS-1")
    links = [_link(JiraLinkKind.PARENT, "MFS-2")]
    result = resolver.resolve(doc, links)
    # MFS-2 was deleted → treated as absent → dead link
    assert result[0].resolved is True
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_resolve_marks_missing_target_as_dead():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1")))
    doc = _doc("acme", "MFS-1")
    links = [_link(JiraLinkKind.ISSUE_LINK, "MFS-99")]
    result = resolver.resolve(doc, links)
    assert result[0].resolved is True
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_resolve_skips_already_resolved_links_unchanged():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1"), _doc("acme", "MFS-2")))
    doc = _doc("acme", "MFS-1")
    already = _link(JiraLinkKind.PARENT, "MFS-2", resolved=True)
    result = resolver.resolve(doc, [already])
    # No change → identity contract: returned sequence is the input.
    assert result is not None
    assert result[0] is already


@pytest.mark.asyncio
async def test_resolve_returns_input_identity_when_nothing_changes():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1")))
    doc = _doc("acme", "MFS-1")
    links = [_link(JiraLinkKind.PARENT, "MFS-99", resolved=True)]
    result = resolver.resolve(doc, links)
    assert result is links  # identity return per Resolver Protocol


@pytest.mark.asyncio
async def test_resolve_skips_non_resolvable_kinds():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1")))
    doc = _doc("acme", "MFS-1")
    other = Link(
        id="lnk:acme:MFS-1:0:0",
        document="doc:acme:MFS-1",
        section="sec:acme:MFS-1:0",
        seq=0,
        kind="external",
        target_anchor=None,
        resolved=False,
        metadata={"url": "https://example.com"},
    )
    result = resolver.resolve(doc, [other])
    assert result is not None
    assert result[0] is other  # untouched


@pytest.mark.asyncio
async def test_resolve_empty_target_key_marked_dead():
    resolver = JiraIssueResolver()
    await resolver.prepare(_stream(_doc("acme", "MFS-1")))
    doc = _doc("acme", "MFS-1")
    weird = Link(
        id="lnk:acme:MFS-1:0:0",
        document="doc:acme:MFS-1",
        section="sec:acme:MFS-1:0",
        seq=0,
        kind=JiraLinkKind.ISSUE_LINK,
        target_anchor=None,
        resolved=False,
        metadata={},  # no TARGET_KEY at all
    )
    result = resolver.resolve(doc, [weird])
    assert result[0].resolved is True
    assert result[0].target_document is None
