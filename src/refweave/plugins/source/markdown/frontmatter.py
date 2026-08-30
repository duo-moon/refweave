"""Detect and parse frontmatter at the top of a Markdown file.

Supports three common conventions:
    ---\\n...\\n---\\n   YAML     (Jekyll, Docusaurus, Hugo default, MkDocs)
    +++\\n...\\n+++\\n   TOML     (Hugo alternative)
    {...}\\n            JSON      (Hugo raw-JSON variant, no fences)

Malformed frontmatter is left in the body (parser will treat the whole
file as content) and `format` is reported as `"none"` — no crash. YAML
is loaded via `yaml.safe_load` (no arbitrary tag execution).
"""

from __future__ import annotations

import json
import logging
import tomllib
from typing import TYPE_CHECKING, Any, Final, Literal

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

Format = Literal["yaml", "toml", "json", "none"]

_YAML_FENCE: Final = "---"
_TOML_FENCE: Final = "+++"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, Format]:
    """Return `(metadata, body_without_frontmatter, format)`.

    If no recognizable frontmatter is present at the top of `text`, the
    input is returned unchanged with an empty metadata dict and
    `format="none"`.
    """
    if text.startswith("{"):
        result = _parse_json(text)
        if result is not None:
            return result
    if _starts_with_fence(text, _YAML_FENCE):
        result = _parse_fenced(text, _YAML_FENCE, _load_yaml, "yaml")
        if result is not None:
            return result
    if _starts_with_fence(text, _TOML_FENCE):
        result = _parse_fenced(text, _TOML_FENCE, _load_toml, "toml")
        if result is not None:
            return result
    return {}, text, "none"


def _starts_with_fence(text: str, fence: str) -> bool:
    # Opening fence line must be exactly the fence followed by a newline.
    # `---abc\n...` is NOT frontmatter — even though the string starts with
    # `---`, anything past the fence marker on the same line disqualifies it
    # (matches how the closer is matched later, keeping open/close symmetric).
    return text.startswith((fence + "\n", fence + "\r\n"))


def _parse_fenced(
    text: str,
    fence: str,
    loader: Callable[[str], Any],
    fmt: Format,
) -> tuple[dict[str, Any], str, Format] | None:
    lines = text.splitlines(keepends=True)
    # First line is the opening fence — locate the matching closer.
    for i in range(1, len(lines)):
        stripped = lines[i].rstrip("\r\n")
        if stripped == fence:
            block = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            try:
                data = loader(block)
            except Exception as exc:  # noqa: BLE001 — YAML/TOML/JSON each raise their own hierarchy; user-supplied frontmatter is a plugin boundary, log-and-skip is intentional
                logger.warning("failed to parse %s frontmatter: %s", fmt, exc)
                return None
            # Empty frontmatter (fences present but no keys) is valid — YAML
            # yields None on empty input; TOML/JSON already give {}.
            if data is None:
                data = {}
            if not isinstance(data, dict):
                logger.warning(
                    "%s frontmatter is not a mapping (got %s); ignoring",
                    fmt,
                    type(data).__name__,
                )
                return None
            return data, body, fmt
    # Unclosed fence — treat as no frontmatter, don't drop content.
    logger.debug("%s frontmatter fence never closed; treating file as body-only", fmt)
    return None


def _parse_json(text: str) -> tuple[dict[str, Any], str, Format] | None:
    """Bare JSON object at file start; use raw_decode to find where it ends."""
    decoder = json.JSONDecoder()
    try:
        obj, end = decoder.raw_decode(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    body = text[end:].lstrip("\r\n")
    return obj, body, "json"


def _load_yaml(block: str) -> Any:
    return yaml.safe_load(block)


def _load_toml(block: str) -> Any:
    return tomllib.loads(block)
