"""Shared StructuralElement dataclass + `structural_element_to_section`.

`StructuralElement` is the intermediate content type every source's
parser (Confluence, Jira, Markdown, ...) converges on before
`build_document`. Field names mirror `refweave.model.Section` so build
code can map elements → Sections with minimal translation.

`structural_element_to_section` performs that translation for structural
core keys (anchor, heading_level). Product-specific enrichment (Confluence
navigation flag, Jira comment authorship, ...) is layered on top by the
plugin's own `build.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from refweave.model import Section
from refweave.plugins.keys import ANCHOR_KEY, HEADING_LEVEL_KEY


@dataclass(frozen=True, slots=True)
class StructuralElement:
    """One top-level element from a parsed source document.

    seq           — position in the source order (0-based).
    kind          — a `SectionKind.*` value for cross-source common
                    categories, a plugin-local `ElementKind.*` value
                    for source-specific ones, or any custom string.
    text          — plain-text projection of the element's content.
    raw           — the original serialized fragment (XHTML for Confluence,
                    ADF JSON / wiki markup for Jira, Markdown source for MD).
    anchor        — anchor id if the element defines one.
    heading_level — populated for heading kinds (1-6), else None.
    metadata      — free-form bag for product-specific data (language,
                    callout kind, comment author, list-kind, ...).
    """

    seq: int
    kind: str
    text: str
    raw: str
    anchor: str | None = None
    heading_level: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def structural_element_to_section(
    elt: StructuralElement,
    *,
    doc_id: str,
    sec_id: str,
) -> Section:
    """Convert a `StructuralElement` into a `Section` with structural core keys.

    Copies `elt.metadata` into the new Section, then folds in
    `ANCHOR_KEY` / `HEADING_LEVEL_KEY` when present on the element.
    Product-specific keys (`NAVIGATION_KEY`, comment authorship, ...)
    are the caller's responsibility — layer them on the returned
    Section's metadata via `model_copy` or wrap this helper.
    """
    metadata: dict[str, Any] = dict(elt.metadata)
    if elt.anchor is not None:
        metadata[ANCHOR_KEY] = elt.anchor
    if elt.heading_level is not None:
        metadata[HEADING_LEVEL_KEY] = elt.heading_level
    return Section(
        id=sec_id,
        document=doc_id,
        seq=elt.seq,
        kind=elt.kind,
        text=elt.text,
        raw=elt.raw,
        metadata=metadata,
    )
