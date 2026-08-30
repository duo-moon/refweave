"""Unit tests for FsStore — blob layout, sharding, atomic writes, tombstones."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.model import Chunk, Document, Link, Section, SyncState
from refweave.plugins.store import FsStore

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _doc(external: str, source_id: str = "s", *, deleted: bool = False) -> Document:
    doc_id = f"doc:{source_id}:{external}"
    return Document(
        id=doc_id,
        title=f"Doc {external}",
        sections=(
            Section(
                id=f"sec:{source_id}:{external}:0",
                document=doc_id,
                seq=0,
                kind="paragraph",
                text=f"body of {external}",
                raw="",
            ),
        ),
        sync=SyncState(
            version=1,
            updated_at=_NOW,
            deleted_at=_NOW if deleted else None,
        ),
    )


def _link(external: str, source_id: str = "s") -> Link:
    doc_id = f"doc:{source_id}:{external}"
    return Link(
        id=f"lnk:{source_id}:{external}:0:0",
        document=doc_id,
        section=f"sec:{source_id}:{external}:0",
        seq=0,
        kind="internal",
        resolved=False,
    )


def _chunk(external: str, seq: int = 0, source_id: str = "s") -> Chunk:
    return Chunk(
        id=f"chk:{source_id}:{external}:{seq}",
        document=f"doc:{source_id}:{external}",
        seq=seq,
        text=f"chunk {external}/{seq}",
    )


@pytest.mark.asyncio
async def test_init_creates_layout_directories(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()

    for sub in ("documents", "links", "chunks"):
        assert (tmp_path / sub).is_dir()


@pytest.mark.asyncio
async def test_document_put_and_get_roundtrip(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("1"))

    got = await fs.documents.get("s", "doc:s:1")
    assert got is not None
    assert got.title == "Doc 1"


@pytest.mark.asyncio
async def test_document_get_missing_returns_none(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()

    assert await fs.documents.get("s", "doc:s:nope") is None


@pytest.mark.asyncio
async def test_document_iter_yields_all_docs(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    for external in ("a", "b", "c"):
        await fs.documents.put(_doc(external))

    docs = [doc async for doc in fs.documents.iter("s")]
    assert {d.id for d in docs} == {"doc:s:a", "doc:s:b", "doc:s:c"}


@pytest.mark.asyncio
async def test_document_iter_empty_when_source_absent(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()

    docs = [doc async for doc in fs.documents.iter("unknown")]
    assert docs == []


@pytest.mark.asyncio
async def test_layout_is_sharded_by_document_id_hash(tmp_path: Path) -> None:
    """Every document lives at documents/<source>/<2-hex-shard>/<safe_id>.json."""
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("shard-check"))

    files = list((tmp_path / "documents" / "s").rglob("*.json"))
    assert len(files) == 1
    # Shard is the file's parent directory name — must be 2 hex chars.
    shard_dir = files[0].parent
    assert len(shard_dir.name) == 2
    assert all(c in "0123456789abcdef" for c in shard_dir.name)


@pytest.mark.asyncio
async def test_unsafe_filename_chars_are_sanitized(tmp_path: Path) -> None:
    """Windows-reserved chars in document_id are replaced with `_`."""
    fs = FsStore(tmp_path)
    await fs.init()

    # Colon is reserved on Windows and it's also the id separator, so a
    # canonical id contains multiple colons — verify the file name has none.
    await fs.documents.put(_doc("bad:name"))
    files = list((tmp_path / "documents" / "s").rglob("*.json"))
    assert len(files) == 1
    assert ":" not in files[0].name


@pytest.mark.asyncio
async def test_document_put_is_atomic_via_tmp_and_replace(tmp_path: Path) -> None:
    """No .tmp debris after a completed put — replace ran successfully."""
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("atomic"))

    tmp_debris = list((tmp_path / "documents" / "s").rglob("*.tmp*"))
    assert tmp_debris == []


@pytest.mark.asyncio
async def test_links_put_get_roundtrip(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    doc = _doc("1")
    await fs.links.put(doc, [_link("1")])

    got = [link async for link in fs.links.get("s", "doc:s:1")]
    assert len(got) == 1
    assert got[0].id == "lnk:s:1:0:0"


@pytest.mark.asyncio
async def test_links_put_empty_wipes_existing_file(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    doc = _doc("1")
    await fs.links.put(doc, [_link("1")])
    # Now overwrite with an empty list — file should be removed.
    await fs.links.put(doc, [])

    got = [link async for link in fs.links.get("s", "doc:s:1")]
    assert got == []


@pytest.mark.asyncio
async def test_links_get_missing_yields_nothing(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()

    got = [link async for link in fs.links.get("s", "doc:s:nope")]
    assert got == []


@pytest.mark.asyncio
async def test_chunks_put_get_roundtrip(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    doc = _doc("1")
    await fs.chunks.put(doc, [_chunk("1", 0), _chunk("1", 1)])

    got = [c async for c in fs.chunks.get("s", "doc:s:1")]
    assert [c.seq for c in got] == [0, 1]


@pytest.mark.asyncio
async def test_close_is_a_no_op(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.close()
    # Sub-stores are still usable after close (FsStore holds no connections).
    await fs.documents.put(_doc("after-close"))
    assert await fs.documents.get("s", "doc:s:after-close") is not None


@pytest.mark.asyncio
async def test_document_iter_ignores_non_json_debris(tmp_path: Path) -> None:
    """iter() filters by .json extension — .tmp/.bak files must not crash it."""
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("real"))

    # Drop a fake .tmp file into the same shard directory.
    doc_dir = next((tmp_path / "documents" / "s").iterdir())
    (doc_dir / "leftover.tmp").write_text("garbage")

    docs = [doc async for doc in fs.documents.iter("s")]
    assert {d.id for d in docs} == {"doc:s:real"}


@pytest.mark.asyncio
async def test_document_put_overwrites_previous_version(tmp_path: Path) -> None:
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("1"))
    updated = _doc("1").model_copy(update={"title": "Updated Title"})
    await fs.documents.put(updated)

    got = await fs.documents.get("s", "doc:s:1")
    assert got is not None
    assert got.title == "Updated Title"


@pytest.mark.asyncio
async def test_deleted_document_is_persisted_with_tombstone(tmp_path: Path) -> None:
    """Store persists whatever SyncState it's given — tombstone included."""
    fs = FsStore(tmp_path)
    await fs.init()
    await fs.documents.put(_doc("1", deleted=True))

    got = await fs.documents.get("s", "doc:s:1")
    assert got is not None
    assert got.sync.deleted_at is not None
