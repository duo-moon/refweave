"""ISO 8601 datetime helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp (including the `Z` UTC shorthand)."""
    return datetime.fromisoformat(raw)


def epoch() -> datetime:
    """UTC Unix epoch — safe fallback for missing timestamps."""
    return datetime.fromtimestamp(0, tz=UTC)
