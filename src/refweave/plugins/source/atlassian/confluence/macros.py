"""Registry of handlers for `<ac:structured-macro>` nodes.

Each handler produces a StructuralElement (or None to drop the macro).
New handlers can be registered without touching the parser.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Protocol, runtime_checkable

from lxml import etree

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.confluence.elements import ElementKind, StructuralElement

logger = logging.getLogger(__name__)

AC_NS: Final = "http://atlassian.com/content"
RI_NS: Final = "http://atlassian.com/resource/identifier"

_AC_NAME: Final = f"{{{AC_NS}}}name"
_AC_PARAMETER: Final = f"{{{AC_NS}}}parameter"
_AC_PLAIN_BODY: Final = f"{{{AC_NS}}}plain-text-body"
_AC_RICH_BODY: Final = f"{{{AC_NS}}}rich-text-body"

# Shared with links.py — namespaced element tags for Confluence resource identifiers.
RI_PAGE: Final = f"{{{RI_NS}}}page"
RI_CONTENT_TITLE: Final = f"{{{RI_NS}}}content-title"
RI_SPACE_KEY: Final = f"{{{RI_NS}}}space-key"


@runtime_checkable
class MacroHandler(Protocol):
    """Turns a `<ac:structured-macro>` node into a StructuralElement.

    Returning None drops the macro from the parsed output.
    """

    def handle(self, macro: etree._Element, seq: int) -> StructuralElement | None: ...


# ---- utilities --------------------------------------------------------------


def get_macro_name(macro: etree._Element) -> str:
    return macro.get(_AC_NAME, "")


def get_param(macro: etree._Element, name: str) -> str | None:
    for param in macro.iterfind(_AC_PARAMETER):
        if param.get(_AC_NAME, "") == name:
            return (param.text or "").strip() or None
    return None


def get_default_param(macro: etree._Element) -> str | None:
    """Value of the unnamed default parameter (ac:name="")."""
    return get_param(macro, "")


def get_plain_body(macro: etree._Element) -> str:
    body = macro.find(_AC_PLAIN_BODY)
    if body is None:
        return ""
    return (body.text or "").strip("\n")


def get_rich_body_text(macro: etree._Element) -> str:
    body = macro.find(_AC_RICH_BODY)
    if body is None:
        return ""
    return " ".join(str(t) for t in body.itertext()).strip()


def serialize(node: etree._Element) -> str:
    return etree.tostring(node, encoding="unicode")


# ---- handlers ---------------------------------------------------------------


class CodeMacro:
    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        language = get_param(macro, "language") or "text"
        title = get_param(macro, "title")
        body = get_plain_body(macro)
        metadata: dict[str, Any] = {"language": language}
        if title:
            metadata["title"] = title
        return StructuralElement(
            seq=seq,
            kind=SectionKind.CODE,
            text=body,
            raw=serialize(macro),
            metadata=metadata,
        )


class CalloutMacro:
    """Handles info / warning / note / panel — visually distinct callout boxes."""

    def __init__(self, callout_kind: str) -> None:
        self._callout_kind = callout_kind

    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        title = get_param(macro, "title")
        text = get_rich_body_text(macro)
        metadata: dict[str, Any] = {"callout_kind": self._callout_kind}
        if title:
            metadata["title"] = title
        return StructuralElement(
            seq=seq,
            kind=ElementKind.CALLOUT,
            text=text,
            raw=serialize(macro),
            metadata=metadata,
        )


class ExpandMacro:
    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        title = get_param(macro, "title") or ""
        text = get_rich_body_text(macro)
        return StructuralElement(
            seq=seq,
            kind=ElementKind.EXPAND,
            text=text,
            raw=serialize(macro),
            metadata={"title": title} if title else {},
        )


class AnchorMacro:
    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        return StructuralElement(
            seq=seq,
            kind=ElementKind.ANCHOR,
            text="",
            raw=serialize(macro),
            anchor=get_default_param(macro),
        )


class IncludePageMacro:
    """`include` / `include-page` — embeds another page.

    Preserves position in the section stream; the actual target reference
    is captured as a Link edge by the link extractor.
    """

    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        return StructuralElement(
            seq=seq,
            kind=ElementKind.INCLUDE_PAGE,
            text="",
            raw=serialize(macro),
        )


class UnknownMacro:
    """Fallback for macros without a registered handler.

    Logs a warning **once per macro name** and DEBUG on subsequent
    occurrences — one instance shared across a whole sync would
    otherwise flood the log on corpora with many unhandled macros.
    Instance-local dedup is fine because the registry factory creates
    one `UnknownMacro` per parser.
    """

    def __init__(self) -> None:
        self._seen_names: set[str] = set()

    def handle(self, macro: etree._Element, seq: int) -> StructuralElement:
        name = get_macro_name(macro)
        if name and name not in self._seen_names:
            self._seen_names.add(name)
            logger.warning("unknown confluence macro: name=%s (subsequent hits at DEBUG)", name)
        else:
            logger.debug("unknown confluence macro: name=%s", name)
        return StructuralElement(
            seq=seq,
            kind=SectionKind.UNKNOWN,
            text=get_rich_body_text(macro) or get_plain_body(macro),
            raw=serialize(macro),
            metadata={"macro_name": name} if name else {},
        )


# ---- registry ---------------------------------------------------------------


def default_registry() -> dict[str, MacroHandler]:
    callout_info = CalloutMacro("info")
    callout_warning = CalloutMacro("warning")
    callout_note = CalloutMacro("note")
    callout_panel = CalloutMacro("panel")
    return {
        "code": CodeMacro(),
        "info": callout_info,
        "warning": callout_warning,
        "note": callout_note,
        "panel": callout_panel,
        "expand": ExpandMacro(),
        "anchor": AnchorMacro(),
        "include": IncludePageMacro(),
        "include-page": IncludePageMacro(),
    }
