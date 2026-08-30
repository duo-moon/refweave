"""Concrete Chunker implementations shipping with the library.

`PolicyChunker` — rule-driven, respects document structure + graph
signal. Composes a `Policy` of `Rule` objects and an optional
`ChunkClassifier` to label the emitted chunks.

`FixedWindowChunker` — naive sliding window; ignores document
structure. Ships as an A/B baseline so retrieval quality of the
structured chunker can be measured against it on the same corpus.

Both consume `(Document, Sequence[Link])` and produce `Chunk`
objects with the same shape, so downstream code (stores, retrieval)
can swap between them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

from refweave.ids import chunk_id, parse_document_id
from refweave.model import Chunk, ChunkLinkRef, Document, Link, Section
from refweave.plugins.chunker.rule import ChunkContext, Decision
from refweave.plugins.keys import ANCHORS_KEY, anchor

if TYPE_CHECKING:
    from refweave.plugins.chunker.policy import Policy

ChunkClassifier = Callable[[Sequence[Section], ChunkContext], str | None]


def _index_links_by_section(links: Sequence[Link]) -> dict[str, list[Link]]:
    """Group links by their owning Section.id."""
    index: dict[str, list[Link]] = {}
    for link in links:
        index.setdefault(link.section, []).append(link)
    return index


def _build_outgoing_link_refs(
    sections: Sequence[Section],
    by_section: dict[str, list[Link]],
) -> tuple[ChunkLinkRef, ...]:
    """Project every Link owned by `sections` into a compact ChunkLinkRef."""
    return tuple(
        ChunkLinkRef(
            target_document=link.target_document,
            target_anchor=link.target_anchor,
            kind=link.kind,
        )
        for section in sections
        for link in by_section.get(section.id, ())
    )


class PolicyChunker:
    """Turns a Document into Chunks by running a Policy over section boundaries.

    Walks the document's sections once. At each boundary it asks the
    Policy whether to MERGE `curr` into the current buffer or SPLIT
    (flush the buffer as a Chunk and start a new buffer). After a chunk
    is flushed, the optional classifier decides its `kind` from the
    final section list.

    Per-document data (each section's outgoing target doc ids) is
    gathered into a `ChunkContext` before the policy runs, and passed
    to every rule and classifier invocation. Rules that need chunker-
    run data (cluster priors, custom lookups) take it in their own
    constructor.
    """

    def __init__(
        self,
        policy: Policy,
        classifier: ChunkClassifier | None = None,
        *,
        text_separator: str = "\n\n",
        overlap_chars: int = 0,
    ) -> None:
        """`overlap_chars` — prepend the last N chars of each emitted chunk
        to the next one. The overlap lands in `Chunk.text` (not in
        `sections`) — `Chunk.text` therefore no longer maps 1:1 to
        `sections[i].text` when overlap is on.
        """
        if overlap_chars < 0:
            msg = f"overlap_chars must be non-negative, got {overlap_chars}"
            raise ValueError(msg)
        self._policy = policy
        self._classifier = classifier
        self._separator = text_separator
        self._overlap = overlap_chars

    def chunk(
        self,
        document: Document,
        links: Sequence[Link],
    ) -> Iterator[Chunk]:
        if not document.sections:
            return

        source_id, external = parse_document_id(document.id)
        by_section = _index_links_by_section(links)
        ctx = ChunkContext(
            document=document,
            outgoing_by_section=_build_outgoing_by_section(by_section),
        )
        buffer: list[Section] = [document.sections[0]]
        seq = 0
        prev_tail = ""

        for curr in document.sections[1:]:
            decision = self._policy.decide(curr, buffer, ctx)
            if decision is Decision.SPLIT:
                chunk = self._emit(
                    buffer,
                    document.id,
                    source_id,
                    external,
                    seq,
                    by_section,
                    ctx,
                    prev_tail,
                )
                prev_tail = self._compute_tail(chunk.text)
                yield chunk
                seq += 1
                buffer = [curr]
            else:
                buffer.append(curr)

        yield self._emit(
            buffer,
            document.id,
            source_id,
            external,
            seq,
            by_section,
            ctx,
            prev_tail,
        )

    def _compute_tail(self, text: str) -> str:
        if self._overlap <= 0:
            return ""
        return text[-self._overlap :]

    def _emit(
        self,
        sections: Sequence[Section],
        document_id: str,
        source_id: str,
        external: str,
        seq: int,
        by_section: dict[str, list[Link]],
        ctx: ChunkContext,
        prev_tail: str = "",
    ) -> Chunk:
        body = self._separator.join(s.text for s in sections if s.text)
        text = f"{prev_tail}{self._separator}{body}" if prev_tail and body else prev_tail or body
        outgoing = _build_outgoing_link_refs(sections, by_section)
        kind = self._classify(sections, ctx)
        # Dedupe while preserving order — a chunk that spans two sections
        # with the same slugified heading (common in generated docs like
        # "## Overview" repeated per API resource) would otherwise emit
        # the same anchor twice, tripping `chunk_anchor.PRIMARY KEY
        # (chunk_id, anchor)` in the SQLite index.
        anchors = tuple(dict.fromkeys(a for s in sections if (a := anchor(s)) is not None))
        metadata: dict[str, Any] = {ANCHORS_KEY: anchors} if anchors else {}
        fields: dict[str, Any] = {
            "id": chunk_id(source_id, external, seq),
            "document": document_id,
            "seq": seq,
            "text": text,
            "sections": tuple(s.id for s in sections),
            "outgoing_links": outgoing,
            "metadata": metadata,
        }
        if kind is not None:
            fields["kind"] = kind
        return Chunk(**fields)

    def _classify(
        self,
        sections: Sequence[Section],
        ctx: ChunkContext,
    ) -> str | None:
        if self._classifier is None:
            return None
        return self._classifier(sections, ctx)


def _build_outgoing_by_section(
    by_section: dict[str, list[Link]],
) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for section_id, links in by_section.items():
        targets = tuple(link.target_document for link in links if link.target_document is not None)
        if targets:
            out[section_id] = targets
    return out


class FixedWindowChunker:
    """Slides a `chunk_size`-char window over the concatenated document.

    Ignores document structure entirely. Concatenates all Section texts
    with a blank-line separator and slices the result into overlapping
    char-windows.

    Section coverage is tracked by char offsets so each emitted chunk
    correctly reports which sections it overlapped, and inherits their
    outgoing link references — the resulting `Chunk` has the same shape
    as `PolicyChunker`'s output regardless of how boundaries were picked.

    `chunk_size` — target window size in chars.
    `overlap` — chars of prior window prepended to each subsequent
                chunk. Must be strictly less than `chunk_size`.
    `text_separator` — placed between adjacent section texts before
                       windowing. Matches `PolicyChunker.text_separator`
                       so both chunkers produce comparable `Chunk.text`.
    """

    def __init__(
        self,
        *,
        chunk_size: int = 1000,
        overlap: int = 0,
        text_separator: str = "\n\n",
    ) -> None:
        if overlap < 0 or overlap >= chunk_size:
            msg = f"overlap must satisfy 0 <= overlap < chunk_size, got {overlap}"
            raise ValueError(msg)
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._separator = text_separator

    def chunk(self, document: Document, links: Sequence[Link]) -> Iterator[Chunk]:
        by_section = _index_links_by_section(links)
        offsets = _section_offsets(document.sections, len(self._separator))
        if not offsets:
            return
        full_text = self._separator.join(s.text for s in document.sections if s.text)
        source_id, external = parse_document_id(document.id)

        win_pos = 0
        seq = 0
        while win_pos < len(full_text):
            end = min(win_pos + self._chunk_size, len(full_text))
            covered_sections = [
                s for s, s_start, s_end in offsets if s_start < end and s_end > win_pos
            ]
            outgoing = _build_outgoing_link_refs(covered_sections, by_section)
            yield Chunk(
                id=chunk_id(source_id, external, seq),
                document=document.id,
                seq=seq,
                text=full_text[win_pos:end],
                sections=tuple(s.id for s in covered_sections),
                outgoing_links=outgoing,
            )
            seq += 1
            if end >= len(full_text):
                break
            win_pos = end - self._overlap


def _section_offsets(
    sections: Sequence[Section],
    separator_len: int,
) -> list[tuple[Section, int, int]]:
    """Return `(section, start_char, end_char)` intervals into the joined text."""
    offsets: list[tuple[Section, int, int]] = []
    pos = 0
    for s in sections:
        if not s.text:
            continue
        start = pos
        pos += len(s.text)
        offsets.append((s, start, pos))
        pos += separator_len
    return offsets
