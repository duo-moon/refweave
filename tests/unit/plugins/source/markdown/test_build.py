"""Tests for build_document — RawFile + parsed elements → Document."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from refweave.plugins.keys import ANCHOR_KEY, HEADING_LEVEL_KEY
from refweave.plugins.kinds import SectionKind
from refweave.plugins.source.base import StructuralElement
from refweave.plugins.source.markdown.build import build_document
from refweave.plugins.source.markdown.extra import MarkdownExtra
from refweave.plugins.source.markdown.types import RawFile

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _raw(**overrides: Any) -> RawFile:
    base: dict[str, Any] = {
        "path": "docs/setup.md",
        "body": "",
        "updated_at": _NOW,
    }
    base.update(overrides)
    return RawFile(**base)


def _elt(seq: int, kind: str, text: str = "body", **extra: Any) -> StructuralElement:
    return StructuralElement(seq=seq, kind=kind, text=text, raw="", **extra)


def _extra(doc_metadata: dict[str, Any]) -> MarkdownExtra:
    extra = MarkdownExtra.read(doc_metadata)
    assert extra is not None
    return extra


def test_document_id_uses_relative_path() -> None:
    doc = build_document(_raw(), (), source_id="docs")
    assert doc.id == "doc:docs:docs/setup.md"


def test_title_from_frontmatter_wins() -> None:
    doc = build_document(
        _raw(),
        (_elt(0, SectionKind.HEADING, text="Heading Title", heading_level=1),),
        source_id="docs",
        frontmatter={"title": "Frontmatter Title"},
    )
    assert doc.title == "Frontmatter Title"


def test_title_falls_back_to_first_heading() -> None:
    doc = build_document(
        _raw(),
        (_elt(0, SectionKind.HEADING, text="Setup", heading_level=1),),
        source_id="docs",
    )
    assert doc.title == "Setup"


def test_title_falls_back_to_path_basename() -> None:
    doc = build_document(_raw(path="docs/getting-started.md"), (), source_id="docs")
    assert doc.title == "getting-started"


def test_sync_version_is_mtime_timestamp() -> None:
    doc = build_document(_raw(), (), source_id="docs")
    assert doc.sync.version == int(_NOW.timestamp())
    assert doc.sync.updated_at == _NOW


def test_extra_carries_path_always() -> None:
    doc = build_document(_raw(), (), source_id="docs")
    assert _extra(doc.metadata).path == "docs/setup.md"


def test_frontmatter_format_reflects_absence_or_dialect() -> None:
    without = build_document(_raw(), (), source_id="docs")
    assert _extra(without.metadata).frontmatter_format == "none"

    with_fm = build_document(
        _raw(),
        (),
        source_id="docs",
        frontmatter={"x": 1},
        frontmatter_format="yaml",
    )
    assert _extra(with_fm.metadata).frontmatter_format == "yaml"


def test_tags_list_flows_from_frontmatter() -> None:
    doc = build_document(
        _raw(),
        (),
        source_id="docs",
        frontmatter={"tags": ["auth", "ops"]},
    )
    assert _extra(doc.metadata).tags == ("auth", "ops")


def test_frontmatter_fields_folded_verbatim_into_extra() -> None:
    doc = build_document(
        _raw(),
        (),
        source_id="docs",
        frontmatter={"author": "alice", "draft": True, "weight": 42},
    )
    fm = _extra(doc.metadata).frontmatter
    assert fm["author"] == "alice"
    assert fm["draft"] is True
    assert fm["weight"] == 42


def test_reserved_keys_not_duplicated() -> None:
    doc = build_document(
        _raw(),
        (),
        source_id="docs",
        frontmatter={"title": "X", "tags": ["t"], "author": "alice"},
        frontmatter_format="yaml",
    )
    extra = _extra(doc.metadata)
    # tags surfaced as a typed field, not duplicated in `frontmatter`.
    assert extra.tags == ("t",)
    assert "tags" not in extra.frontmatter
    # title is Document.title, not carried in metadata.
    assert "title" not in extra.frontmatter
    # non-reserved keys are preserved verbatim.
    assert extra.frontmatter["author"] == "alice"


def test_metadata_shape_is_only_the_extra_namespace() -> None:
    doc = build_document(_raw(), (), source_id="docs")
    assert set(doc.metadata.keys()) == {MarkdownExtra.NAMESPACE}


def test_sections_from_elements() -> None:
    elements = (
        _elt(0, SectionKind.HEADING, text="H1", heading_level=1, anchor="h1"),
        _elt(1, SectionKind.PARAGRAPH, text="Body"),
    )
    doc = build_document(_raw(), elements, source_id="docs")
    assert len(doc.sections) == 2
    assert doc.sections[0].metadata[HEADING_LEVEL_KEY] == 1
    assert doc.sections[0].metadata[ANCHOR_KEY] == "h1"


def test_fallback_section_when_no_elements() -> None:
    doc = build_document(_raw(), (), source_id="docs")
    assert len(doc.sections) == 1
    assert doc.sections[0].seq == 0
    assert doc.sections[0].kind == SectionKind.PARAGRAPH


def test_section_ids_are_stable() -> None:
    elements = (_elt(0, SectionKind.PARAGRAPH), _elt(1, SectionKind.PARAGRAPH))
    doc = build_document(_raw(), elements, source_id="docs")
    assert doc.sections[0].id == "sec:docs:docs/setup.md:0"
    assert doc.sections[1].id == "sec:docs:docs/setup.md:1"
