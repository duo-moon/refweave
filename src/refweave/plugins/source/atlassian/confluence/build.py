"""Turn a RawPage + parsed StructuralElements into a Document."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refweave.model import Document, Section, SyncState
from refweave.plugins.keys import NAVIGATION_KEY
from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.atlassian.confluence.extra import ConfluenceExtra
from refweave.plugins.source.atlassian.confluence.navigation import (
    NavigationHeadingDetector,
)
from refweave.plugins.source.base import (
    document_id,
    section_id,
    structural_element_to_section,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from refweave.plugins.source.atlassian.confluence.types import RawPage
    from refweave.plugins.source.base import StructuralElement


def _build_section(
    elt: StructuralElement,
    *,
    doc_id: str,
    sec_id: str,
    nav_detector: NavigationHeadingDetector,
) -> Section:
    section = structural_element_to_section(elt, doc_id=doc_id, sec_id=sec_id)
    if elt.kind == SectionKind.HEADING and nav_detector.is_navigation(elt.text):
        metadata = {**section.metadata, NAVIGATION_KEY: True}
        return section.model_copy(update={"metadata": metadata})
    return section


def _document_metadata(page: RawPage, *, source_id: str) -> dict[str, Any]:
    extra = ConfluenceExtra(
        space=page.space_key,
        labels=page.labels,
        parent=document_id(source_id, page.parent_id) if page.parent_id else None,
    )
    return extra.write()


def build_document(
    page: RawPage,
    elements: Sequence[StructuralElement],
    *,
    source_id: str,
    nav_detector: NavigationHeadingDetector | None = None,
) -> Document:
    doc_id = document_id(source_id, page.id)
    detector = nav_detector or NavigationHeadingDetector()
    sections = tuple(
        _build_section(
            elt,
            doc_id=doc_id,
            sec_id=section_id(source_id, page.id, elt.seq),
            nav_detector=detector,
        )
        for elt in elements
    )
    return Document(
        id=doc_id,
        title=page.title,
        sections=sections,
        sync=SyncState(version=page.version, updated_at=page.updated_at),
        metadata=_document_metadata(page, source_id=source_id),
    )
