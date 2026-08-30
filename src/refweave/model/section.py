"""Section — one ordered unit inside a Document."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Section(BaseModel):
    """One structural element inside a Document.

    `id` — canonical `sec:<source>:<external>:<seq>` (see `refweave.ids`).
    `document` — id of the containing Document.
    `seq` — position among sibling sections, 0-based, contiguous.
    `kind` — string classification label. Vocabulary is not enforced.
    `text` — plain-text projection of the element's content.
    `raw` — original serialized fragment. May be empty.
    `metadata` — free-form key-value bag.
    """

    id: str
    document: str
    seq: int
    kind: str
    text: str
    raw: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
