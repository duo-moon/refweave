"""Jira wiki-markup → StructuralElement list.

Line-based state machine over Jira DC's legacy wiki syntax. Handles:
    - h1..h6 headings          → HEADING
    - {code[:lang]}...{code}   → CODE
    - {noformat}...{noformat}  → CODE (language=text)
    - {quote}...{quote}        → QUOTE (multi-line block)
    - bq. …                    → QUOTE (single-line)
    - {panel[:title=X]}...     → PANEL
    - {info|warning|note|tip}… → PANEL (panel_type set)
    - ----                     → HR
    - *item / - item / # item  → LIST (consecutive lines merged)
    - |cell|cell|              → TABLE (consecutive lines merged)
    - anything else            → PARAGRAPH (consecutive non-empty lines merged)

Inline formatting (`*bold*`, `[text|url]`, `[KEY]`) is stripped from
`text` but preserved in `raw` so `LinkExtractor` can find issue mentions.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.jira.elements import ElementKind
from refweave.plugins.source.base.elements import StructuralElement

logger = logging.getLogger(__name__)

_HEADING_RE: Final = re.compile(r"^h([1-6])\.\s+(.+)$")
_HR_RE: Final = re.compile(r"^-{4,}$")
_BLOCK_MACRO_RE: Final = re.compile(
    r"^\{(code|noformat|quote|panel|info|warning|note|tip)" r"(?::[^}]*)?\}$",
)
_MACRO_CLOSE_RE: Final = re.compile(r"^\{(code|noformat|quote|panel|info|warning|note|tip)\}$")
_LIST_LINE_RE: Final = re.compile(r"^([*#\-]+)\s+(.*)$")
_TABLE_LINE_RE: Final = re.compile(r"^\|.*\|\s*$")

# Panel-style call-outs whose macro name IS the panel type.
_PANEL_KIND: Final = {"info", "warning", "note", "tip"}

# Inline formatting patterns for plain-text stripping.
_LINK_LABELED_RE: Final = re.compile(r"\[([^|\]]+)\|[^\]]+\]")  # [label|url] → label
_LINK_PLAIN_RE: Final = re.compile(r"\[([^\]]+)\]")  # [X] → X (issue key or url)
_MONO_RE: Final = re.compile(r"\{\{([^}]+)\}\}")  # {{x}} → x
_BOLD_RE: Final = re.compile(r"\*([^*\n]+)\*")  # *x* → x
_ITALIC_RE: Final = re.compile(r"_([^_\n]+)_")  # _x_ → x


def parse_wiki(body: str) -> tuple[StructuralElement, ...]:
    """Parse Jira wiki markup into an ordered tuple of StructuralElements."""
    if not body:
        return ()
    lines = body.splitlines()
    elements: list[StructuralElement] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        element, next_i = _consume_block(lines, i, len(elements))
        elements.append(element)
        i = next_i
    return tuple(elements)


def _consume_block(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int]:
    """Try each block matcher in order; fall back to paragraph."""
    for matcher in _MATCHERS:
        result = matcher(lines, i, seq)
        if result is not None:
            return result
    return _consume_paragraph(lines, i, seq)


def _try_heading(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    m = _HEADING_RE.match(lines[i].strip())
    if not m:
        return None
    element = StructuralElement(
        seq=seq,
        kind=SectionKind.HEADING,
        text=_strip_inline(m.group(2).strip()),
        raw=lines[i],
        heading_level=int(m.group(1)),
    )
    return element, i + 1


def _try_hr(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    if not _HR_RE.match(lines[i].strip()):
        return None
    return (
        StructuralElement(seq=seq, kind=SectionKind.HR, text="", raw=lines[i]),
        i + 1,
    )


def _try_bq_quote(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    stripped = lines[i].strip()
    if not stripped.startswith("bq. "):
        return None
    element = StructuralElement(
        seq=seq,
        kind=SectionKind.QUOTE,
        text=_strip_inline(stripped[4:]),
        raw=lines[i],
    )
    return element, i + 1


def _try_macro(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    stripped = lines[i].strip()
    m = _BLOCK_MACRO_RE.match(stripped)
    if not m:
        return None
    macro_name = m.group(1)
    end_i = _find_block_end(lines, i, macro_name)
    body_lines = lines[i + 1 : end_i]
    raw = "\n".join(lines[i : end_i + 1])
    return _macro_element(seq, macro_name, stripped, body_lines, raw), end_i + 1


def _try_list(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    if not _LIST_LINE_RE.match(lines[i].strip()):
        return None
    j = i
    while j < len(lines) and _LIST_LINE_RE.match(lines[j].strip()):
        j += 1
    list_lines = lines[i:j]
    raw = "\n".join(list_lines)
    text = "\n".join(_strip_inline(_list_item_text(line)) for line in list_lines)
    return (
        StructuralElement(seq=seq, kind=SectionKind.LIST, text=text, raw=raw),
        j,
    )


def _try_table(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int] | None:
    if not _TABLE_LINE_RE.match(lines[i].strip()):
        return None
    j = i
    while j < len(lines) and _TABLE_LINE_RE.match(lines[j].strip()):
        j += 1
    table_lines = lines[i:j]
    raw = "\n".join(table_lines)
    cells = [
        _strip_inline(cell.strip())
        for line in table_lines
        for cell in line.strip().strip("|").split("|")
        if cell.strip()
    ]
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.TABLE,
            text=" ".join(cells),
            raw=raw,
        ),
        j,
    )


def _consume_paragraph(
    lines: list[str],
    i: int,
    seq: int,
) -> tuple[StructuralElement, int]:
    j = i
    while j < len(lines):
        candidate = lines[j].strip()
        if not candidate or _is_block_marker(candidate):
            break
        j += 1
    para_lines = lines[i:j]
    raw = "\n".join(para_lines)
    text = _strip_inline(" ".join(line.strip() for line in para_lines))
    return (
        StructuralElement(
            seq=seq,
            kind=SectionKind.PARAGRAPH,
            text=text,
            raw=raw,
        ),
        j,
    )


_MATCHERS: Final = (_try_heading, _try_hr, _try_bq_quote, _try_macro, _try_list, _try_table)


def _find_block_end(lines: list[str], start: int, macro_name: str) -> int:
    """Locate the closing `{macro_name}` line; if missing, treat rest as body."""
    for k in range(start + 1, len(lines)):
        m = _MACRO_CLOSE_RE.match(lines[k].strip())
        if m and m.group(1) == macro_name:
            return k
    logger.debug("wiki macro %s never closed; consuming to end", macro_name)
    # No close found — return len(lines) so body_lines = lines[start+1:] captures
    # everything after the open marker.
    return len(lines)


def _macro_element(
    seq: int,
    macro_name: str,
    open_line: str,
    body_lines: list[str],
    raw: str,
) -> StructuralElement:
    text = "\n".join(body_lines).strip()
    metadata: dict[str, Any] = {}

    if macro_name == "code":
        language = _macro_param(open_line, "language") or _macro_positional(open_line)
        if language:
            metadata["language"] = language
        return StructuralElement(
            seq=seq,
            kind=SectionKind.CODE,
            text=text,
            raw=raw,
            metadata=metadata,
        )
    if macro_name == "noformat":
        metadata["language"] = "text"
        return StructuralElement(
            seq=seq,
            kind=SectionKind.CODE,
            text=text,
            raw=raw,
            metadata=metadata,
        )
    if macro_name == "quote":
        return StructuralElement(
            seq=seq,
            kind=SectionKind.QUOTE,
            text=_strip_inline(text),
            raw=raw,
        )
    if macro_name == "panel":
        title = _macro_param(open_line, "title")
        if title:
            metadata["title"] = title
        return StructuralElement(
            seq=seq,
            kind=ElementKind.PANEL,
            text=_strip_inline(text),
            raw=raw,
            metadata=metadata,
        )
    if macro_name in _PANEL_KIND:
        metadata["panel_type"] = macro_name
        return StructuralElement(
            seq=seq,
            kind=ElementKind.PANEL,
            text=_strip_inline(text),
            raw=raw,
            metadata=metadata,
        )
    return StructuralElement(seq=seq, kind=SectionKind.UNKNOWN, text=text, raw=raw)


def _macro_param(open_line: str, name: str) -> str | None:
    """Extract a `name=value` param from a `{macro:key=val|key2=val2}` header."""
    inside = open_line[open_line.index(":") + 1 : -1] if ":" in open_line else ""
    for part in inside.split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


def _macro_positional(open_line: str) -> str | None:
    """Extract the first positional param (e.g. `{code:python}` → `python`)."""
    if ":" not in open_line:
        return None
    inside = open_line[open_line.index(":") + 1 : -1]
    first = inside.split("|", 1)[0].strip()
    return first if first and "=" not in first else None


def _list_item_text(line: str) -> str:
    m = _LIST_LINE_RE.match(line.strip())
    return m.group(2) if m else line.strip()


def _is_block_marker(line: str) -> bool:
    return bool(
        _HEADING_RE.match(line)
        or _HR_RE.match(line)
        or _BLOCK_MACRO_RE.match(line)
        or _LIST_LINE_RE.match(line)
        or _TABLE_LINE_RE.match(line)
        or line.startswith("bq. "),
    )


def _strip_inline(text: str) -> str:
    """Strip common wiki inline formatting while preserving readable text."""
    text = _LINK_LABELED_RE.sub(r"\1", text)
    text = _LINK_PLAIN_RE.sub(r"\1", text)
    text = _MONO_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    return " ".join(text.split())
