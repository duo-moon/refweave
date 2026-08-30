"""Turn a RawFile + frontmatter + parsed elements into a Document.

Title resolution order:
    1. frontmatter `title` key (Jekyll / Docusaurus / Hugo convention)
    2. first heading in the parsed body
    3. file basename (no extension) as a last-resort fallback

Non-title frontmatter fields (except `tags`, surfaced as its own typed
attribute) are packed into `MarkdownExtra.frontmatter` verbatim; the
whole Extra is written under a single namespaced key in metadata.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from refweave.model import Document, Section, SyncState
from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.base import (
    document_id,
    section_id,
    structural_element_to_section,
)
from refweave.plugins.source.markdown.extra import MarkdownExtra

if TYPE_CHECKING:
    from collections.abc import Sequence

    from refweave.plugins.source.base import StructuralElement
    from refweave.plugins.source.markdown.frontmatter import Format
    from refweave.plugins.source.markdown.types import RawFile


def build_document(
    raw: RawFile,
    elements: Sequence[StructuralElement],
    *,
    source_id: str,
    frontmatter: dict[str, Any] | None = None,
    frontmatter_format: Format = "none",
) -> Document:
    fm = frontmatter or {}
    doc_id = document_id(source_id, raw.path)
    sections = tuple(
        structural_element_to_section(
            elt,
            doc_id=doc_id,
            sec_id=section_id(source_id, raw.path, elt.seq),
        )
        for elt in elements
    )
    if not sections:
        sections = (
            Section(
                id=section_id(source_id, raw.path, 0),
                document=doc_id,
                seq=0,
                kind=SectionKind.PARAGRAPH,
                text="",
                raw="",
            ),
        )
    return Document(
        id=doc_id,
        title=_resolve_title(fm, elements, raw.path),
        sections=sections,
        sync=SyncState(
            version=int(raw.updated_at.timestamp()),
            updated_at=raw.updated_at,
        ),
        metadata=_document_metadata(raw, fm, frontmatter_format),
    )


def _resolve_title(
    frontmatter: dict[str, Any],
    elements: Sequence[StructuralElement],
    path: str,
) -> str:
    fm_title = frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    for elt in elements:
        if elt.kind == SectionKind.HEADING and elt.text.strip():
            return elt.text.strip()
    stem = PurePosixPath(path).stem
    return stem or path


_RESERVED_FRONTMATTER_KEYS: Final = frozenset({"title", "tags"})


def _document_metadata(
    raw: RawFile,
    frontmatter: dict[str, Any],
    fmt: Format,
) -> dict[str, Any]:
    tags_value = frontmatter.get("tags")
    tags = tuple(tags_value) if isinstance(tags_value, list) else ()
    remainder = {
        key: value
        for key, value in frontmatter.items()
        if key not in _RESERVED_FRONTMATTER_KEYS
    }
    extra = MarkdownExtra(
        path=raw.path,
        tags=tags,
        frontmatter_format=fmt,
        frontmatter=remainder,
    )
    return extra.write()
