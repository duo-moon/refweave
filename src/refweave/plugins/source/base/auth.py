"""HTTP authentication contract for plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import httpx


@runtime_checkable
class AuthProvider(Protocol):
    """Applies auth to a prepared httpx.Request.

    Implementations mutate the request in place (typically by adding an
    Authorization header). Must be safe to call concurrently across many
    requests over the same client instance.
    """

    def apply(self, request: httpx.Request) -> None: ...
