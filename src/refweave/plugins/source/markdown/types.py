"""Wire-format types produced by the Markdown source walker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawFile:
    """One Markdown file snapshot pulled from the filesystem.

    `path` — relative POSIX-style path from the source root (used as
    `<external>` in `document_id`). Kept as-is so link resolution can
    compare against `[](./other.md)` hrefs from other files without
    platform-dependent normalization.

    `body` — full file contents including frontmatter. Downstream
    `build_document` strips the frontmatter before parsing the Markdown.

    `updated_at` — filesystem mtime; used as `int(updated_at.timestamp())`
    for `SyncState.version`, enabling skip-detection on re-sync.
    """

    path: str
    body: str
    updated_at: datetime
