"""Shared helpers for chunker rule tests.

Rules now take a `ChunkContext` as third apply-arg. The vast majority
of unit tests don't care about the document or the outgoing map; this
module offers a builder that fabricates a minimal context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from refweave.model import Document, Section, SyncState
from refweave.plugins.chunker import ChunkContext

if TYPE_CHECKING:
    from collections.abc import Mapping


def make_ctx(
    outgoing_by_section: Mapping[str, tuple[str, ...]] | None = None,
    *,
    doc_id: str = "doc:s:1",
) -> ChunkContext:
    return ChunkContext(
        document=Document(
            id=doc_id,
            title="",
            sections=(
                Section(
                    id=f"sec:{doc_id.removeprefix('doc:')}:0",
                    document=doc_id,
                    seq=0,
                    kind="paragraph",
                    text="",
                ),
            ),
            sync=SyncState(version=1, updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        ),
        outgoing_by_section=dict(outgoing_by_section or {}),
    )
