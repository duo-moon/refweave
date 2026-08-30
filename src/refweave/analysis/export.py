"""Stream a synced corpus as JSONL — one enriched chunk per line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from refweave.pipeline import Persistence


async def export_jsonl(
    persistence: Persistence,
    source_id: str,
    path: Path | str,
) -> int:
    """Write every chunk of `source_id` to `path` as JSONL. Returns the count.

    Each line is a JSON object combining `Chunk` fields with graph
    state:

        {
            "id": "chk:s:doc:0",
            "document": "doc:s:doc",
            "document_title": "Doc Title",
            "seq": 0,
            "kind": "generic",
            "text": "...",
            "sections": ["sec:s:doc:0"],
            "outgoing_links": [...],
            "metadata": {},
            "cluster_id": 1,
            "incoming_anchor_from": ["chk:..."]
        }

    Deleted documents (tombstoned via `SyncState.deleted_at`) are
    skipped. Order is document-by-document, chunks in `seq` order within
    each — good for streaming ingestion into embedding pipelines.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    async with aiofiles.open(dest, "w", encoding="utf-8") as f:
        async for doc in persistence.documents.iter(source_id):
            if doc.sync.deleted_at is not None:
                continue
            async for cwg in persistence.query.get_chunks(source_id, doc.id):
                record: dict[str, Any] = {
                    "id": cwg.chunk.id,
                    "document": cwg.chunk.document,
                    "document_title": doc.title,
                    "seq": cwg.chunk.seq,
                    "kind": cwg.chunk.kind,
                    "text": cwg.chunk.text,
                    "sections": list(cwg.chunk.sections),
                    "outgoing_links": [
                        ref.model_dump() for ref in cwg.chunk.outgoing_links
                    ],
                    "metadata": dict(cwg.chunk.metadata),
                    "cluster_id": cwg.cluster_id,
                    "incoming_anchor_from": list(cwg.incoming_anchor_from),
                }
                await f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    return count
