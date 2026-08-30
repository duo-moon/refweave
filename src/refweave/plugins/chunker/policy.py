"""Policy — an ordered set of Rules that collectively decide chunk boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refweave.plugins.chunker.rule import ChunkContext, Decision, Rule

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from refweave.model import Section


class Policy:
    """Composition of Rules. Rules are evaluated in order; the first
    non-DEFER decision is returned. If every rule defers, the policy
    returns its configured `default` (typically MERGE or SPLIT). DEFER
    is also accepted as `default` — the policy then passes through the
    lack of opinion, useful for nesting one policy inside another.
    """

    def __init__(
        self,
        rules: Iterable[Rule],
        *,
        default: Decision = Decision.MERGE,
    ) -> None:
        self._rules = tuple(rules)
        self._default = default

    def decide(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        """Return the first non-DEFER decision, or `default` if every rule deferred."""
        for rule in self._rules:
            answer = rule.apply(curr, buffer, ctx)
            if answer is not Decision.DEFER:
                return answer
        return self._default
