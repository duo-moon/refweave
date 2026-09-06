"""Tests for MarkdownFileResolver — prepare + resolve + path normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Document, Link, Section, SyncState
from refweave.plugins.source.markdown import (
    MarkdownExtra,
    MarkdownFileResolver,
    MarkdownLinkKind,
)
from refweave.plugins.source.markdown.keys import HREF_KEY, TARGET_PATH_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _doc(path: str, *, deleted: bool = False) -> Document:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    doc_id = f"doc:s:{path}"
    return Document(
        id=doc_id,
        title=path,
        sections=(
            Section(
                id=f"sec:s:{path}:0",
                document=doc_id,
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
        metadata=MarkdownExtra(path=path).write(),
    )


async def _stream(*docs: Document) -> AsyncIterator[Document]:
    for d in docs:
        yield d


def _link(target_path: str, *, resolved: bool = False) -> Link:
    return Link(
        id="lnk:s:src.md:0:0",
        document="doc:s:src.md",
        section="sec:s:src.md:0",
        seq=0,
        kind=MarkdownLinkKind.INTERNAL,
        target_anchor=None,
        resolved=resolved,
        metadata={TARGET_PATH_KEY: target_path},
    )


@pytest.mark.asyncio
async def test_prepare_builds_normalized_path_index() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md"), _doc("guides/setup.md")))
    src = _doc("index.md")
    result = resolver.resolve(src, [_link("./guides/setup.md")])
    assert result[0].target_document == "doc:s:guides/setup.md"


@pytest.mark.asyncio
async def test_dot_dot_traverses_up_from_source_dir() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(
        _stream(_doc("guides/setup.md"), _doc("index.md")),
    )
    src = _doc("guides/setup.md")
    result = resolver.resolve(src, [_link("../index.md")])
    assert result[0].target_document == "doc:s:index.md"


@pytest.mark.asyncio
async def test_absolute_path_treated_as_corpus_root() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("docs/x.md")))
    src = _doc("index.md")
    result = resolver.resolve(src, [_link("/docs/x.md")])
    assert result[0].target_document == "doc:s:docs/x.md"


@pytest.mark.asyncio
async def test_missing_target_marked_dead() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    result = resolver.resolve(src, [_link("./missing.md")])
    assert result[0].resolved is True
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_empty_target_path_marked_dead() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    result = resolver.resolve(src, [_link("")])
    assert result[0].resolved is True
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_deleted_docs_excluded_from_index() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("target.md", deleted=True)))
    src = _doc("index.md")
    result = resolver.resolve(src, [_link("./target.md")])
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_already_resolved_links_pass_through_unchanged() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md"), _doc("target.md")))
    src = _doc("index.md")
    already = _link("./target.md", resolved=True)
    result = resolver.resolve(src, [already])
    assert result[0] is already


@pytest.mark.asyncio
async def test_resolve_returns_input_identity_when_nothing_changes() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    input_links = [_link("./x.md", resolved=True)]
    result = resolver.resolve(src, input_links)
    # Contract: return the exact input sequence when nothing changed.
    assert result is input_links


@pytest.mark.asyncio
async def test_external_links_untouched() -> None:
    resolver = MarkdownFileResolver()
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    external = Link(
        id="lnk:s:index.md:0:0",
        document="doc:s:index.md",
        section="sec:s:index.md:0",
        seq=0,
        kind=MarkdownLinkKind.EXTERNAL,
        target_anchor=None,
        resolved=True,
        metadata={},
    )
    result = resolver.resolve(src, [external])
    assert result[0] is external


def _external(href: str, *, seq: int = 0) -> Link:
    return Link(
        id=f"lnk:s:src.md:0:{seq}",
        document="doc:s:src.md",
        section="sec:s:src.md:0",
        seq=seq,
        kind=MarkdownLinkKind.EXTERNAL,
        target_anchor=None,
        resolved=True,
        metadata={HREF_KEY: href},
    )


@pytest.mark.asyncio
async def test_url_rewriter_promotes_matching_external_to_internal() -> None:
    def rewriter(href: str) -> str | None:
        prefix = "https://docs.example.com/"
        if href.startswith(prefix):
            return "/" + href[len(prefix) :].strip("/") + ".md"
        return None

    resolver = MarkdownFileResolver(url_rewriter=rewriter)
    await resolver.prepare(_stream(_doc("guide.md")))
    src = _doc("index.md")
    ext = _external("https://docs.example.com/guide")
    result = resolver.resolve(src, [ext])
    assert result[0].kind == MarkdownLinkKind.INTERNAL
    assert result[0].target_document == "doc:s:guide.md"
    assert result[0].resolved is True
    assert result[0].metadata[TARGET_PATH_KEY] == "/guide.md"


@pytest.mark.asyncio
async def test_url_rewriter_preserves_fragment_as_target_anchor() -> None:
    def rewriter(href: str) -> str | None:
        prefix = "https://docs.example.com/"
        if href.startswith(prefix):
            path = href[len(prefix) :]
            return "/" + path if "#" in path else "/" + path + ".md"
        return None

    resolver = MarkdownFileResolver(url_rewriter=rewriter)
    await resolver.prepare(_stream(_doc("guide.md")))
    src = _doc("index.md")
    ext = _external("https://docs.example.com/guide.md#setup")
    result = resolver.resolve(src, [ext])
    assert result[0].target_document == "doc:s:guide.md"
    assert result[0].target_anchor == "setup"


@pytest.mark.asyncio
async def test_url_rewriter_returning_none_leaves_link_external() -> None:
    resolver = MarkdownFileResolver(url_rewriter=lambda _href: None)
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    ext = _external("https://elsewhere.com/something")
    result = resolver.resolve(src, [ext])
    assert result[0].kind == MarkdownLinkKind.EXTERNAL
    assert result[0].target_document is None


@pytest.mark.asyncio
async def test_url_rewriter_promoted_to_missing_target_is_dead_internal() -> None:
    resolver = MarkdownFileResolver(
        url_rewriter=lambda href: "/does-not-exist.md" if href else None,
    )
    await resolver.prepare(_stream(_doc("index.md")))
    src = _doc("index.md")
    ext = _external("https://any.example.com/foo")
    result = resolver.resolve(src, [ext])
    # Promoted → internal, but no target in corpus → dead-but-resolved.
    assert result[0].kind == MarkdownLinkKind.INTERNAL
    assert result[0].target_document is None
    assert result[0].resolved is True
