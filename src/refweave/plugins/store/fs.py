"""Filesystem-backed implementation of storage protocols.

Layout:
    <root>/documents/<source_id>/<shard>/<safe_id>.json
    <root>/links/<source_id>/<shard>/<safe_id>.jsonl
    <root>/chunks/<source_id>/<shard>/<safe_id>.jsonl

`<shard>` = first two hex chars of sha256(document_id) — keeps directory
listings small.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Generic, TypeVar

import aiofiles
import aiofiles.os
from pydantic import BaseModel

from refweave.ids import source_of
from refweave.model import Chunk, Document, Link

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

T = TypeVar("T", bound=BaseModel)


def _shard_of(document_id: str) -> str:
    """First two hex chars of sha256(document_id) — directory shard."""
    return hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:2]


# Windows-reserved characters plus POSIX path separator.
# https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
_UNSAFE_FILENAME_CHARS: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(document_id: str) -> str:
    """Filesystem-safe form of a document id. Idempotent."""
    return _UNSAFE_FILENAME_CHARS.sub("_", document_id)


def _blob_path(
    root: Path,
    kind: str,
    source_id: str,
    document_id: str,
    ext: str,
) -> Path:
    """`<root>/<kind>/<source_id>/<shard>/<safe_id><ext>` per the layout."""
    return root / kind / source_id / _shard_of(document_id) / (_safe_filename(document_id) + ext)


def _tmp_path(final: Path) -> Path:
    """Unique per-process/random tmp path — safe for concurrent writers.

    A crashed process leaves `.<pid>-<rand>.tmp` debris; safe to delete on
    startup if desired. The iter/read paths filter by the real extension
    so debris is ignored during reads.
    """
    return final.with_name(f"{final.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")


def _iter_json_objects(payload: str) -> Iterable[dict[str, Any]]:
    """Yield each JSON object parsed from `payload`. Tolerant to pretty-printed
    multi-line JSON that may appear when an IDE auto-formats a jsonl file.
    """
    stripped = payload.strip()
    if not stripped:
        return
    decoder = json.JSONDecoder()
    i = 0
    while i < len(stripped):
        while i < len(stripped) and stripped[i].isspace():
            i += 1
        if i >= len(stripped):
            break
        obj, end = decoder.raw_decode(stripped, i)
        yield obj
        i = end


class _FsDocumentStore:
    """One JSON file per Document."""

    _KIND = "documents"
    _EXT = ".json"

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, source_id: str, document_id: str) -> Path:
        return _blob_path(self._root, self._KIND, source_id, document_id, self._EXT)

    async def put(self, document: Document) -> None:
        path = self._path(source_of(document.id), document.id)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)
        tmp = _tmp_path(path)
        payload = document.model_dump_json()
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(payload)
        await aiofiles.os.replace(tmp, path)

    async def get(self, source_id: str, document_id: str) -> Document | None:
        path = self._path(source_id, document_id)
        if not await aiofiles.os.path.exists(path):
            return None
        async with aiofiles.open(path, encoding="utf-8") as f:
            payload = await f.read()
        return Document.model_validate_json(payload)

    async def iter(self, source_id: str) -> AsyncIterator[Document]:
        source_dir = self._root / self._KIND / source_id
        if not await aiofiles.os.path.exists(source_dir):
            return
        for shard_name in sorted(await aiofiles.os.listdir(source_dir)):
            shard_dir = source_dir / shard_name
            if not await aiofiles.os.path.isdir(shard_dir):
                continue
            for file_name in sorted(await aiofiles.os.listdir(shard_dir)):
                if not file_name.endswith(self._EXT):
                    continue
                file = shard_dir / file_name
                async with aiofiles.open(file, encoding="utf-8") as f:
                    payload = await f.read()
                yield Document.model_validate_json(payload)


class _FsJsonlStore(Generic[T]):
    """One .jsonl file per document, one item per line. Parameterized on model."""

    _EXT = ".jsonl"

    def __init__(self, root: Path, kind: str, model: type[T]) -> None:
        self._root = root
        self._kind = kind
        self._model = model

    def _path(self, source_id: str, document_id: str) -> Path:
        return _blob_path(self._root, self._kind, source_id, document_id, self._EXT)

    async def put(self, document: Document, items: Sequence[T]) -> None:
        path = self._path(source_of(document.id), document.id)
        if not items:
            if await aiofiles.os.path.exists(path):
                await aiofiles.os.remove(path)
            return
        await aiofiles.os.makedirs(path.parent, exist_ok=True)
        tmp = _tmp_path(path)
        payload = "\n".join(item.model_dump_json() for item in items) + "\n"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(payload)
        await aiofiles.os.replace(tmp, path)

    async def get(self, source_id: str, document_id: str) -> AsyncIterator[T]:
        path = self._path(source_id, document_id)
        if not await aiofiles.os.path.exists(path):
            return
        async with aiofiles.open(path, encoding="utf-8") as f:
            payload = await f.read()
        for obj in _iter_json_objects(payload):
            yield self._model.model_validate(obj)


class FsStore:
    """Filesystem-backed storage: documents/links/chunks sub-stores over one root.

    Usage: `fs = FsStore(root); await fs.init(); ...; await fs.close()`.
    `init()` creates the layout directories; `close()` is a no-op (there are
    no persistent connections) and kept for symmetry with SqliteStore.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self.documents = _FsDocumentStore(self._root)
        self.links: _FsJsonlStore[Link] = _FsJsonlStore(self._root, "links", Link)
        self.chunks: _FsJsonlStore[Chunk] = _FsJsonlStore(self._root, "chunks", Chunk)

    async def init(self) -> None:
        """Create the three top-level directories (documents/links/chunks)."""
        for sub in ("documents", "links", "chunks"):
            await aiofiles.os.makedirs(self._root / sub, exist_ok=True)

    async def close(self) -> None:
        """No-op — FsStore holds no persistent connections."""
        return
