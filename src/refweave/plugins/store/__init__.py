"""Storage impls.

    FsStore     — filesystem blob content (JSON/JSONL)
    SqliteStore — SQLite index + query (backed by a file)
    MemoryStore — dict-based; everything (blobs + index + query) in RAM.
                  Zero persistence; use for tests, notebooks, tiny corpora.
"""

from refweave.plugins.store.fs import FsStore
from refweave.plugins.store.memory import MemoryStore
from refweave.plugins.store.sqlite_index import SqliteStore

__all__ = ["FsStore", "MemoryStore", "SqliteStore"]
