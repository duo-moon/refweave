"""Resolves Markdown internal links to target document ids.

Two-phase (Resolver Protocol): `prepare` builds a `normalized_path →
doc_id` index over the corpus; `resolve` fills `target_document` on
unresolved internal links per document, by normalizing each link's
`target_path` relative to the source document's own path.

Optional `url_rewriter` promotes external links (e.g. absolute
`https://mydocs.io/tutorial/foo/` URLs that point back into this same
corpus) to internal before resolution — useful when documentation
frameworks emit absolute canonical URLs instead of relative Markdown
paths. See `MarkdownFileResolver` for the contract.

Dead links (target missing from the corpus, or an intra-doc `#anchor`
where target_path is empty) end with `target_document=None,
resolved=True`.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from refweave.plugins.source.markdown.extra import MarkdownExtra
from refweave.plugins.source.markdown.keys import HREF_KEY, TARGET_PATH_KEY
from refweave.plugins.source.markdown.link_types import MarkdownLinkKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from refweave.model import Document, Link


class MarkdownFileResolver:
    """Resolves cross-file references within one Markdown source.

    `url_rewriter` (optional) turns an external `href` into an internal
    corpus path so the resolver can point the link at a document in the
    index. The callable receives the raw href as it appeared in the
    Markdown source and returns either:

        - a corpus-relative path (`"tutorial/foo.md"`), or
        - a root-absolute path (`"/tutorial/foo.md"`), optionally with
          a `#anchor` fragment, or
        - `None` to leave the link as external.

    A promoted link has its `kind` flipped from `EXTERNAL` to
    `INTERNAL`, its `target_path` metadata set to the rewritten path,
    and its `target_anchor` populated from any fragment.
    """

    def __init__(self, url_rewriter: Callable[[str], str | None] | None = None) -> None:
        self._index: dict[str, str] = {}
        self._url_rewriter = url_rewriter

    async def prepare(self, docs: AsyncIterator[Document]) -> None:
        self._index = {}
        async for doc in docs:
            if doc.sync.deleted_at is not None:
                continue
            extra = MarkdownExtra.read(doc.metadata)
            if extra is None or not extra.path:
                continue
            self._index[_normalize(extra.path)] = doc.id

    def resolve(self, doc: Document, links: Sequence[Link]) -> Sequence[Link]:
        extra = MarkdownExtra.read(doc.metadata)
        source_dir = _dirname(extra.path if extra is not None else "")
        updated: list[Link] = []
        changed = False
        for link in links:
            new_link = self._resolve(link, source_dir)
            if new_link is not link:
                changed = True
            updated.append(new_link)
        return updated if changed else links

    def _resolve(self, link: Link, source_dir: str) -> Link:
        if link.resolved and link.kind == MarkdownLinkKind.INTERNAL:
            # Already resolved as internal — leave alone.
            return link

        # Try to promote external links via the URL rewriter first.
        if self._url_rewriter is not None and link.kind == MarkdownLinkKind.EXTERNAL:
            promoted = self._promote_external(link, source_dir)
            if promoted is not None:
                return promoted

        if link.kind != MarkdownLinkKind.INTERNAL:
            return link

        target_path = str(link.metadata.get(TARGET_PATH_KEY, ""))
        if not target_path:
            # Pure `#anchor` link — intra-doc; nothing to resolve to another doc.
            return link.model_copy(update={"resolved": True})
        resolved_path = _resolve_relative(source_dir, target_path)
        target = self._index.get(resolved_path)
        return link.model_copy(
            update={"target_document": target, "resolved": True},
        )

    def _promote_external(self, link: Link, source_dir: str) -> Link | None:
        """Try the URL rewriter on `link`. Return promoted link or None."""
        assert self._url_rewriter is not None  # noqa: S101 — narrowed by caller
        href = str(link.metadata.get(HREF_KEY, ""))
        if not href:
            return None
        rewritten = self._url_rewriter(href)
        if rewritten is None:
            return None
        parsed = urlparse(rewritten)
        target_path = parsed.path
        target_anchor = parsed.fragment or None
        resolved_path = _resolve_relative(source_dir, target_path)
        target = self._index.get(resolved_path)
        new_metadata = dict(link.metadata)
        new_metadata[TARGET_PATH_KEY] = target_path
        return link.model_copy(
            update={
                "kind": MarkdownLinkKind.INTERNAL,
                "target_document": target,
                "target_anchor": target_anchor,
                "resolved": True,
                "metadata": new_metadata,
            },
        )


def _normalize(path: str) -> str:
    """POSIX-style relative path with `.` / `..` collapsed."""
    p = PurePosixPath(path.lstrip("/"))
    return _collapse(p)


def _dirname(path: str) -> str:
    if not path:
        return ""
    return str(PurePosixPath(path).parent)


def _resolve_relative(base_dir: str, rel: str) -> str:
    """Join `rel` onto `base_dir`, then collapse `.` / `..`.

    Absolute-looking hrefs (`/foo/bar.md`) are treated as corpus-root
    absolute — the leading slash is stripped.
    """
    if rel.startswith("/"):
        return _collapse(PurePosixPath(rel.lstrip("/")))
    combined = PurePosixPath(base_dir or ".") / rel
    return _collapse(combined)


def _collapse(path: PurePosixPath) -> str:
    """Symbolically resolve `.` / `..` in a pure path (no filesystem access)."""
    parts: list[str] = []
    for part in path.parts:
        if part in (".", ""):
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            # Attempts to escape the corpus root are collapsed as if the
            # leading `..` never appeared; the resolved path stays
            # root-relative. It may still miss the index (dead link) if the
            # remaining segments don't map to any document.
            continue
        parts.append(part)
    return "/".join(parts)
