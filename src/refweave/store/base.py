from typing import Protocol, runtime_checkable


@runtime_checkable
class Store(Protocol):
    """Persistent store for canonical refweave data.

    Concrete methods (put/get documents, sections, links, chunks) land in M1-M2.
    Kept as a marker Protocol during M0.
    """

    async def close(self) -> None: ...
