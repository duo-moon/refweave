"""Chunking engine and generic rules.

Two chunker implementations ship: `PolicyChunker` (rule-driven, respects
document structure + graph signal) and `FixedWindowChunker` (naive
sliding window; ships as an A/B baseline).

`Rule`, `Decision`, `ChunkContext`, and `Policy` are the composition
primitives for `PolicyChunker` — custom rules implement `Rule`; a
`Policy` composes them; the engine consumes the policy.

Built-in Rule / Classifier implementations live alongside the `Rule`
protocol in `rule.py` and are re-exported here for convenience.
"""

from refweave.plugins.chunker.chunkers import (
    ChunkClassifier,
    FixedWindowChunker,
    PolicyChunker,
)
from refweave.plugins.chunker.policy import Policy
from refweave.plugins.chunker.rule import (
    AtomicBlockRule,
    ChunkContext,
    ClusterBoundaryRule,
    Decision,
    HeadingRule,
    LinkOverlapRule,
    MinSizeRule,
    NavigationClassifier,
    Rule,
    SizeLimitRule,
)

__all__ = [
    "AtomicBlockRule",
    "ChunkClassifier",
    "ChunkContext",
    "ClusterBoundaryRule",
    "Decision",
    "FixedWindowChunker",
    "HeadingRule",
    "LinkOverlapRule",
    "MinSizeRule",
    "NavigationClassifier",
    "Policy",
    "PolicyChunker",
    "Rule",
    "SizeLimitRule",
]
