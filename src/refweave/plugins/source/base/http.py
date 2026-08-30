"""Async HTTP client with auth injection, retries, rate limiting, concurrency.

Not endpoint-aware. Plugins wrap this with their own request builders.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any, Final, Self

import httpx
from aiolimiter import AsyncLimiter

if TYPE_CHECKING:
    from types import TracebackType

    from refweave.plugins.source.base.auth import AuthProvider

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES: Final = frozenset({429, 502, 503, 504})


class HttpClient:
    """Async HTTP worker with exponential-backoff retries on 429/503
    (honors Retry-After), client-side rate limiting, bounded concurrency,
    and pluggable auth injection.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth: AuthProvider,
        rate_limit: float = 10.0,
        concurrency: int = 20,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        timeout: httpx.Timeout | float = 30.0,
    ) -> None:
        """
        `rate_limit` — max requests per second (client-side throttling).
        `concurrency` — max in-flight requests.
        `max_retries` — additional attempts after the initial (total = 1 + max_retries).
        `backoff_base` / `backoff_cap` — seconds; full-jitter backoff bounded by cap.
        `timeout` — httpx timeout (default 30s).
        """
        self._auth = auth
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.request("POST", path, params=params, json=json)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                is_last = attempt >= self._max_retries
                async with self._limiter:
                    request = self._client.build_request(
                        method,
                        path,
                        params=params,
                        json=json,
                    )
                    self._auth.apply(request)
                    logger.debug(
                        "http request: %s %s attempt=%d",
                        method,
                        request.url,
                        attempt,
                    )
                    try:
                        response = await self._client.send(request)
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        if is_last:
                            raise
                        sleep_for = self._backoff(attempt)
                        logger.warning(
                            "http transport error, retrying in %.2fs: %s",
                            sleep_for,
                            exc,
                        )
                        await asyncio.sleep(sleep_for)
                        continue

                if response.status_code in _RETRYABLE_STATUSES and not is_last:
                    sleep_for = self._retry_after(response, attempt)
                    logger.warning(
                        "http %d, retrying in %.2fs",
                        response.status_code,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                response.raise_for_status()
                return response

        msg = "retry loop exited without return or raise"
        raise AssertionError(msg)

    def _backoff(self, attempt: int) -> float:
        upper = min(self._backoff_cap, self._backoff_base * (2**attempt))
        return random.uniform(0.0, upper)  # noqa: S311 — jitter, not crypto

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        """Retry-After header → seconds. Numeric form only.

        HTTP-date form (`Retry-After: Wed, 21 Oct 2015 07:28:00 GMT`) is
        rare in modern APIs; it silently falls back to exponential backoff.
        """
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
        return self._backoff(attempt)
