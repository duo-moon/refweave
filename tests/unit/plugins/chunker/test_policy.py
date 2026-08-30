"""Policy composition: first non-DEFER wins, fallback MERGE."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refweave.model import Section
from refweave.plugins.chunker import ChunkContext, Decision, Policy

from .conftest import make_ctx

if TYPE_CHECKING:
    from collections.abc import Sequence


class _Const:
    def __init__(self, decision: Decision) -> None:
        self._decision = decision

    def apply(
        self,
        curr: Section,
        buffer: Sequence[Section],
        ctx: ChunkContext,
    ) -> Decision:
        del curr, buffer, ctx
        return self._decision


def _sec(seq: int) -> Section:
    return Section(id=f"sec:s:1:{seq}", document="doc:s:1", seq=seq, kind="paragraph", text="")


def test_first_non_defer_wins() -> None:
    policy = Policy([_Const(Decision.DEFER), _Const(Decision.SPLIT), _Const(Decision.MERGE)])
    assert policy.decide(_sec(1), [_sec(0)], make_ctx()) is Decision.SPLIT


def test_all_defer_falls_back_to_merge() -> None:
    policy = Policy([_Const(Decision.DEFER), _Const(Decision.DEFER)])
    assert policy.decide(_sec(1), [_sec(0)], make_ctx()) is Decision.MERGE


def test_empty_policy_falls_back_to_merge() -> None:
    policy = Policy([])
    assert policy.decide(_sec(1), [_sec(0)], make_ctx()) is Decision.MERGE


def test_custom_default_is_used_on_all_defer() -> None:
    policy = Policy([_Const(Decision.DEFER)], default=Decision.SPLIT)
    assert policy.decide(_sec(1), [_sec(0)], make_ctx()) is Decision.SPLIT


def test_default_defer_passes_through() -> None:
    """DEFER as default lets an outer policy pick up the decision."""
    policy = Policy([_Const(Decision.DEFER)], default=Decision.DEFER)
    assert policy.decide(_sec(1), [_sec(0)], make_ctx()) is Decision.DEFER
