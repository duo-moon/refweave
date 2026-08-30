"""Infrastructure shared across source plugins: HTTP client, auth, date parsing.

ID helpers (document_id, section_id, chunk_id, link_id, parse_document_id)
are re-exported from `refweave.ids` for plugin-author convenience.
"""

from refweave.ids import (
    chunk_id,
    document_id,
    link_id,
    parse_document_id,
    section_id,
)
from refweave.plugins.source.base.auth import AuthProvider
from refweave.plugins.source.base.dates import epoch, parse_iso
from refweave.plugins.source.base.elements import (
    StructuralElement,
    structural_element_to_section,
)
from refweave.plugins.source.base.http import HttpClient

__all__ = [
    "AuthProvider",
    "HttpClient",
    "StructuralElement",
    "chunk_id",
    "document_id",
    "epoch",
    "link_id",
    "parse_document_id",
    "parse_iso",
    "section_id",
    "structural_element_to_section",
]
