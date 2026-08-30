"""Link — a directed edge from one Section to a target."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Link(BaseModel):
    """A directed edge from a Section to a target.

    `id` — canonical `lnk:<source>:<external>:<section_seq>:<link_seq>`
           (see `refweave.ids`).
    `document` — id of the containing Document.
    `section` — id of the containing Section.
    `seq` — position among sibling links, 0-based.
    `kind` — string classification label. Vocabulary is not enforced.
    `target_document` — target Document.id, or None when no target is set.
    `target_anchor` — target anchor within the target document, or None
                      when no anchor was specified.
    `resolved` — True when the target lookup has been performed for this
                 link; combined with `target_document=None` marks a link
                 whose target is not present in the corpus.
    `metadata` — free-form key-value bag.
    """

    id: str
    document: str
    section: str
    seq: int
    kind: str
    target_document: str | None = None
    target_anchor: str | None = None
    resolved: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
