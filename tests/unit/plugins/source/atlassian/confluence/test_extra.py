"""Contract tests for ConfluenceExtra + build_document integration."""

from __future__ import annotations

from datetime import UTC, datetime

from refweave.plugins.source.atlassian.confluence.build import build_document
from refweave.plugins.source.atlassian.confluence.extra import ConfluenceExtra
from refweave.plugins.source.atlassian.confluence.types import RawPage

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _raw_page(**overrides: object) -> RawPage:
    defaults: dict[str, object] = {
        "id": "42",
        "title": "Setup",
        "space_key": "DOCS",
        "version": 3,
        "body": "",
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return RawPage(**defaults)  # type: ignore[arg-type]


def test_extra_populated_on_document_metadata() -> None:
    page = _raw_page(labels=("howto", "setup"), parent_id="10")
    doc = build_document(page, elements=(), source_id="acme")

    extra = ConfluenceExtra.read(doc.metadata)
    assert extra is not None
    assert extra.space == "DOCS"
    assert extra.labels == ("howto", "setup")
    assert extra.parent == "doc:acme:10"


def test_extra_omits_absent_fields() -> None:
    doc = build_document(_raw_page(), elements=(), source_id="acme")

    extra = ConfluenceExtra.read(doc.metadata)
    assert extra is not None
    assert extra.space == "DOCS"
    assert extra.labels == ()
    assert extra.parent is None


def test_metadata_shape_is_only_the_extra_namespace() -> None:
    doc = build_document(_raw_page(), elements=(), source_id="acme")

    assert set(doc.metadata.keys()) == {ConfluenceExtra.NAMESPACE}
