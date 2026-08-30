"""Base class for source-specific typed metadata containers.

Sources publish typed views over their own slice of `Document.metadata`
(and, optionally, `Section.metadata`) by declaring a `SourceExtra`
subclass with a stable `NAMESPACE`. The base class handles serialization
into and back out of the underlying metadata dict.

Contract:

    Writer (source parser)::

        Document(
            ...,
            metadata={
                **ConfluenceExtra(space="DOCS", labels=("howto",)).write(),
            },
        )

    Reader (consumer application)::

        if (extra := ConfluenceExtra.read(document.metadata)) is not None:
            display(extra.space, extra.labels)

Data lives under a namespaced key (`_confluence`, `_jira`, …) so the
top-level metadata dict stays free for consumer-owned annotations and
for structural keys managed via `plugins.keys` accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class SourceExtra(BaseModel):
    """Typed view over a source's slice of a metadata dict.

    Subclasses declare `NAMESPACE` (a stable string key under which the
    serialized payload lives) and their fields. `read`/`write` are the
    only supported crossing points between the typed object and the
    metadata dict — callers should not touch the underlying key
    directly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    NAMESPACE: ClassVar[str]

    @classmethod
    def read(cls, metadata: Mapping[str, Any]) -> Self | None:
        """Return the typed view for this source, or None if not present.

        Raises `pydantic.ValidationError` if the payload is present but
        does not match the declared schema — indicates either a producer
        bug or a persisted-schema drift after a plugin upgrade.
        """
        raw = metadata.get(cls.NAMESPACE)
        if raw is None:
            return None
        return cls.model_validate(raw)

    def write(self) -> dict[str, Any]:
        """Return a metadata-dict fragment ready to merge via ``**`` splat."""
        return {self.NAMESPACE: self.model_dump(mode="json")}
