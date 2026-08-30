"""Layering invariants for refweave — AST-based import guards.

Every rule defines a scope (a set of files) and a set of forbidden import
prefixes. The test walks each file's AST, extracts every module it imports,
and fails if any of them matches a forbidden pattern.

Update the RULES table (not the test logic) when new layers are introduced
or existing boundaries change. Deliberately breaking a rule requires a
matching update here so the intent is explicit.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_REFWEAVE_SRC = Path(__file__).resolve().parents[2] / "src" / "refweave"


@dataclass(frozen=True)
class LayerRule:
    """One layering constraint.

    `scope` — glob relative to `src/refweave` selecting files this rule
    applies to. The special value `"+top"` targets top-level utility
    modules (`graph.py`, `keys.py`, `ids.py`) which live directly under
    `src/refweave/` and shouldn't depend on any of the nested layers.

    `forbidden` — tuple of import prefixes. If any file in `scope`
    imports a module starting with any of these, the rule fails.
    """

    name: str
    scope: str
    forbidden: tuple[str, ...]


_TOP_LEVEL_FILES = ("graph.py", "keys.py", "ids.py")

RULES: tuple[LayerRule, ...] = (
    LayerRule(
        name="atlassian → markdown (peer, not parent)",
        scope="plugins/source/atlassian/**/*.py",
        forbidden=("refweave.plugins.source.markdown",),
    ),
    LayerRule(
        name="markdown → atlassian (peer, not parent)",
        scope="plugins/source/markdown/**/*.py",
        forbidden=("refweave.plugins.source.atlassian",),
    ),
    LayerRule(
        name="base → product plugins (one-way parent→child)",
        scope="plugins/source/base/**/*.py",
        forbidden=(
            "refweave.plugins.source.atlassian",
            "refweave.plugins.source.markdown",
        ),
    ),
    LayerRule(
        name="pipeline → plugins (protocols only, no impls)",
        scope="pipeline/**/*.py",
        forbidden=("refweave.plugins",),
    ),
    LayerRule(
        name="plugins/store → plugins/source (index doesn't know sources)",
        scope="plugins/store/**/*.py",
        forbidden=("refweave.plugins.source",),
    ),
    LayerRule(
        name="plugins/chunker → plugins/source (chunker doesn't know sources)",
        scope="plugins/chunker/**/*.py",
        forbidden=("refweave.plugins.source",),
    ),
    LayerRule(
        name="model → plugins or pipeline (pure data)",
        scope="model/**/*.py",
        forbidden=("refweave.plugins", "refweave.pipeline"),
    ),
    LayerRule(
        name="top-level utilities → plugins or pipeline",
        scope="+top",
        forbidden=("refweave.plugins", "refweave.pipeline"),
    ),
)


def _files_matching(scope: str) -> Iterator[Path]:
    if scope == "+top":
        for name in _TOP_LEVEL_FILES:
            path = _REFWEAVE_SRC / name
            if path.exists():
                yield path
        return
    for path in _REFWEAVE_SRC.glob(scope):
        if path.is_file() and path.suffix == ".py":
            yield path


def _imports_from(source: str) -> set[str]:
    """Every module name imported by this source (both forms)."""
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.name)
def test_layer_rule(rule: LayerRule) -> None:
    violations: list[str] = []
    for path in _files_matching(rule.scope):
        source = path.read_text(encoding="utf-8")
        imports = _imports_from(source)
        for imp in sorted(imports):
            for forbidden in rule.forbidden:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    rel = path.relative_to(_REFWEAVE_SRC.parent)
                    violations.append(f"  {rel} imports {imp} (forbidden: {forbidden})")
    if violations:
        pytest.fail(
            f"Layer violations for rule {rule.name!r}:\n" + "\n".join(violations),
        )


def test_all_rules_have_at_least_one_file_in_scope() -> None:
    """Sanity — if a scope glob matches nothing, the rule is silently vacuous."""
    for rule in RULES:
        files = list(_files_matching(rule.scope))
        assert files, f"rule {rule.name!r} scope {rule.scope!r} matched no files"


# ---- Test-layer isolation --------------------------------------------------
#
# Guards that unit tests for isolated layers stay isolated. Test files may
# use in-scope helpers freely; they may not reach into peer layers.

_TESTS_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TestsLayerRule:
    """Layering rule for the tests/ tree — same shape as LayerRule but rooted
    at `tests/unit/`.
    """

    __test__ = False  # not a pytest collection target despite Test* name

    name: str
    scope: str
    forbidden: tuple[str, ...]


TEST_RULES: tuple[TestsLayerRule, ...] = (
    TestsLayerRule(
        name="tests/unit/model → plugins or pipeline",
        scope="unit/model/**/*.py",
        forbidden=("refweave.plugins", "refweave.pipeline"),
    ),
    TestsLayerRule(
        name="tests/unit/pipeline → plugins (orchestrator uses fakes, not plugin impls)",
        scope="unit/pipeline/**/*.py",
        forbidden=("refweave.plugins",),
    ),
)


def _test_files_matching(scope: str) -> Iterator[Path]:
    for path in _TESTS_ROOT.glob(scope):
        if path.is_file() and path.suffix == ".py":
            yield path


@pytest.mark.parametrize("rule", TEST_RULES, ids=lambda r: r.name)
def test_test_layer_rule(rule: TestsLayerRule) -> None:
    violations: list[str] = []
    for path in _test_files_matching(rule.scope):
        source = path.read_text(encoding="utf-8")
        imports = _imports_from(source)
        for imp in sorted(imports):
            for forbidden in rule.forbidden:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    rel = path.relative_to(_TESTS_ROOT.parent)
                    violations.append(f"  {rel} imports {imp} (forbidden: {forbidden})")
    if violations:
        pytest.fail(
            f"Test-layer violations for rule {rule.name!r}:\n" + "\n".join(violations),
        )


def test_all_test_rules_have_at_least_one_file_in_scope() -> None:
    for rule in TEST_RULES:
        files = list(_test_files_matching(rule.scope))
        assert files, f"test rule {rule.name!r} scope {rule.scope!r} matched no files"
