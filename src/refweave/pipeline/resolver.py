"""Resolver — a plugin that fills unresolved link targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from refweave.model import Document, Link


@runtime_checkable
class Resolver(Protocol):
    """Plugin that fills `target_document` on links. Read-only against the
    corpus: `prepare` consumes the docs once to build any cross-doc
    context (title index, external-id map, ...); `resolve` is then called
    per document with its persisted links and returns the updated sequence.

    The Resolver only computes — the caller handles persistence.
    """

    async def prepare(self, docs: AsyncIterator[Document]) -> None:
        """Consume the corpus to build any cross-doc context for resolve.

        Implementations that don't need cross-doc context should still
        accept the iterator (drain or ignore) — Protocol has no default.
        """
        ...

    def resolve(self, doc: Document, links: Sequence[Link]) -> Sequence[Link]:
        """Return updated links for `doc`.

        Contract: return the input `links` object itself (identity-equal) if
        nothing changed. Callers use `is` to skip persistence when no update
        happened — returning a new Sequence with equal contents will trigger
        an unnecessary write.
        """
        ...
