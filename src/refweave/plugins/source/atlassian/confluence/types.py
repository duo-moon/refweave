"""Wire-level types returned by Confluence API implementations.

Not the domain model — these are the shape of data as fetched from Cloud v2
or DC v1 endpoints, before the parser turns storage-format XHTML into
structural elements and `build_document` produces a Document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawPage:
    """A Confluence page fetched from either Cloud v2 or DC v1.

    Fields are the common denominator between the two APIs. Additional
    endpoint-specific data (e.g. cursor tokens, ETags) is not surfaced here.
    """

    id: str
    title: str
    space_key: str
    version: int
    body: str
    updated_at: datetime
    labels: tuple[str, ...] = ()
    parent_id: str | None = None
