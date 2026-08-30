"""Extract Link edges from a parsed Section's raw XHTML.

Handles the link shapes we see in Confluence storage format:
    * `<ac:link><ri:page/>`                            → ConfluenceLinkKind.PAGE
    * `<ac:link><ri:attachment/>`                      → ConfluenceLinkKind.ATTACHMENT
    * `<ac:link><ri:user/>`                            → ConfluenceLinkKind.USER
    * `<a href="...">` (top-level)                     → ConfluenceLinkKind.EXTERNAL
    * `<ac:structured-macro name="jira">`              → ConfluenceLinkKind.JIRA
    * `<ac:structured-macro name="include|include-page">` → ConfluenceLinkKind.INCLUDE

`resolved=True` for external / jira / user (nothing to look up further).
`resolved=False` for page / attachment / include — a resolver fills
`target_document` in a later stage.

All source-specific data (space, title, url, issue_key, label, ...)
goes flat into `Link.metadata`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from lxml import etree

from refweave.model import Link, Section
from refweave.plugins.source.atlassian.confluence.keys import SPACE_KEY, TITLE_KEY
from refweave.plugins.source.atlassian.confluence.link_types import ConfluenceLinkKind
from refweave.plugins.source.atlassian.confluence.macros import (
    AC_NS,
    RI_CONTENT_TITLE,
    RI_NS,
    RI_PAGE,
    RI_SPACE_KEY,
    get_default_param,
    get_macro_name,
    get_param,
)
from refweave.plugins.source.base import link_id, parse_document_id

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_AC_LINK: Final = f"{{{AC_NS}}}link"
_AC_STRUCTURED_MACRO: Final = f"{{{AC_NS}}}structured-macro"
_AC_PLAIN_LINK_BODY: Final = f"{{{AC_NS}}}plain-text-link-body"
_AC_RICH_LINK_BODY: Final = f"{{{AC_NS}}}rich-text-link-body"
_RI_ATTACHMENT: Final = f"{{{RI_NS}}}attachment"
_RI_USER: Final = f"{{{RI_NS}}}user"
_RI_FILENAME: Final = f"{{{RI_NS}}}filename"
_RI_ACCOUNT_ID: Final = f"{{{RI_NS}}}account-id"
_RI_USERKEY: Final = f"{{{RI_NS}}}userkey"

_ROOT_OPEN: Final = f'<root xmlns:ac="{AC_NS}" xmlns:ri="{RI_NS}">'
_ROOT_CLOSE: Final = "</root>"


class LinkExtractor:
    """Stateless — takes a Section, yields Link edges rooted in it."""

    def extract(
        self,
        section: Section,
        *,
        default_space: str = "",
    ) -> Iterator[Link]:
        """Yield Link edges from `section.raw`.

        `default_space` fills in `metadata["space"]` when a `<ri:page>` or
        `<ri:attachment>` node omits `ri:space-key`. Confluence storage
        format treats an absent space-key as "same space as source page",
        so callers should pass the source Document's space here.
        """
        source_id, external = parse_document_id(section.document)
        wrapped = _ROOT_OPEN + section.raw + _ROOT_CLOSE
        # See ConfluenceParser.parse() — same XXE hardening.
        parser = etree.XMLParser(
            recover=True,
            remove_blank_text=False,
            resolve_entities=False,
            no_network=True,
        )
        root = etree.fromstring(wrapped.encode("utf-8"), parser=parser)  # noqa: S320
        if root is None:
            return

        seq = 0
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            link = self._handle(
                node,
                section=section,
                source_id=source_id,
                external=external,
                default_space=default_space,
                seq=seq,
            )
            if link is not None:
                yield link
                seq += 1

    def _handle(
        self,
        node: etree._Element,
        *,
        section: Section,
        source_id: str,
        external: str,
        default_space: str,
        seq: int,
    ) -> Link | None:
        ctx = _LinkCtx(section=section, source_id=source_id, external=external, seq=seq)

        if node.tag == _AC_STRUCTURED_MACRO:
            name = get_macro_name(node)
            if name == "jira":
                return self._jira(node, ctx)
            if name in ("include", "include-page"):
                return self._include(node, ctx, default_space)
            return None

        if node.tag == _AC_LINK and not _inside(node, (_AC_STRUCTURED_MACRO,)):
            return self._ac_link(node, ctx, default_space)

        if node.tag == "a" and not _inside(node, (_AC_LINK, _AC_STRUCTURED_MACRO)):
            return self._a_href(node, ctx)

        return None

    def _ac_link(
        self,
        node: etree._Element,
        ctx: _LinkCtx,
        default_space: str,
    ) -> Link | None:
        target_anchor = node.get(f"{{{AC_NS}}}anchor") or None
        label = _ac_link_text(node)

        page_ref = node.find(RI_PAGE)
        if page_ref is not None:
            metadata: dict[str, Any] = {
                SPACE_KEY: page_ref.get(RI_SPACE_KEY) or default_space,
                TITLE_KEY: page_ref.get(RI_CONTENT_TITLE) or "",
            }
            if label:
                metadata["label"] = label
            return _link(
                ctx,
                kind=ConfluenceLinkKind.PAGE,
                target_anchor=target_anchor,
                resolved=False,
                metadata=metadata,
            )

        attach_ref = node.find(_RI_ATTACHMENT)
        if attach_ref is not None:
            metadata = {"filename": attach_ref.get(_RI_FILENAME) or ""}
            page_ref = attach_ref.find(RI_PAGE)
            if page_ref is not None:
                metadata[SPACE_KEY] = page_ref.get(RI_SPACE_KEY) or default_space
                metadata[TITLE_KEY] = page_ref.get(RI_CONTENT_TITLE) or ""
            if label:
                metadata["label"] = label
            return _link(
                ctx,
                kind=ConfluenceLinkKind.ATTACHMENT,
                resolved=False,
                metadata=metadata,
            )

        user_ref = node.find(_RI_USER)
        if user_ref is not None:
            metadata = {}
            account_id = user_ref.get(_RI_ACCOUNT_ID)
            userkey = user_ref.get(_RI_USERKEY)
            if account_id:
                metadata["account_id"] = account_id
            if userkey:
                metadata["userkey"] = userkey
            if label:
                metadata["label"] = label
            return _link(
                ctx,
                kind=ConfluenceLinkKind.USER,
                resolved=True,
                metadata=metadata,
            )

        logger.warning("unrecognized ac:link shape in section %s", ctx.section.id)
        return None

    def _a_href(self, node: etree._Element, ctx: _LinkCtx) -> Link | None:
        href = node.get("href")
        if not href:
            return None
        metadata: dict[str, Any] = {"url": href}
        label = (node.text or "").strip()
        if label:
            metadata["label"] = label
        return _link(
            ctx,
            kind=ConfluenceLinkKind.EXTERNAL,
            resolved=True,
            metadata=metadata,
        )

    def _jira(self, node: etree._Element, ctx: _LinkCtx) -> Link | None:
        key = get_param(node, "key")
        if not key:
            return None
        metadata: dict[str, Any] = {"issue_key": key}
        server = get_param(node, "server")
        if server:
            metadata["server"] = server
        return _link(
            ctx,
            kind=ConfluenceLinkKind.JIRA,
            resolved=True,
            metadata=metadata,
        )

    def _include(
        self,
        node: etree._Element,
        ctx: _LinkCtx,
        default_space: str,
    ) -> Link | None:
        # The target page reference sits inside the default parameter, e.g.
        # <ac:parameter ac:name=""><ac:link><ri:page/></ac:link></ac:parameter>
        page_ref = node.find(f".//{RI_PAGE}")
        if page_ref is None:
            # Sometimes older syntax uses the default parameter as text.
            plain = get_default_param(node)
            if not plain:
                return None
            return _link(
                ctx,
                kind=ConfluenceLinkKind.INCLUDE,
                resolved=False,
                metadata={TITLE_KEY: plain},
            )
        return _link(
            ctx,
            kind=ConfluenceLinkKind.INCLUDE,
            resolved=False,
            metadata={
                SPACE_KEY: page_ref.get(RI_SPACE_KEY) or default_space,
                TITLE_KEY: page_ref.get(RI_CONTENT_TITLE) or "",
            },
        )


@dataclass(frozen=True, slots=True)
class _LinkCtx:
    """Carrier for per-link identity data — reduces argument fanout."""

    section: Section
    source_id: str
    external: str
    seq: int


def _link(
    ctx: _LinkCtx,
    *,
    kind: str,
    target_anchor: str | None = None,
    resolved: bool = False,
    metadata: dict[str, Any] | None = None,
) -> Link:
    return Link(
        id=link_id(ctx.source_id, ctx.external, ctx.section.seq, ctx.seq),
        document=ctx.section.document,
        section=ctx.section.id,
        seq=ctx.seq,
        kind=kind,
        target_anchor=target_anchor,
        resolved=resolved,
        metadata=metadata or {},
    )


def _ac_link_text(node: etree._Element) -> str:
    for tag in (_AC_PLAIN_LINK_BODY, _AC_RICH_LINK_BODY):
        body = node.find(tag)
        if body is not None:
            return " ".join(str(t) for t in body.itertext()).strip()
    return ""


def _inside(node: etree._Element, tags: tuple[str, ...]) -> bool:
    return any(anc.tag in tags for anc in node.iterancestors())
