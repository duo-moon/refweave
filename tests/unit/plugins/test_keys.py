"""Contract tests for typed metadata accessors."""

from __future__ import annotations

import pytest

from refweave.model import Chunk, Section
from refweave.plugins.keys import (
    ANCHOR_KEY,
    ANCHORS_KEY,
    HEADING_LEVEL_KEY,
    NAVIGATION_KEY,
    anchor,
    chunk_anchors,
    heading_level,
    is_navigation,
)


def _section(**meta: object) -> Section:
    return Section(
        id="sec:s:e:0",
        document="doc:s:e",
        seq=0,
        kind="paragraph",
        text="",
        metadata=dict(meta),
    )


def _chunk(**meta: object) -> Chunk:
    return Chunk(
        id="chk:s:e:0",
        document="doc:s:e",
        seq=0,
        text="",
        metadata=dict(meta),
    )


# ---- heading_level ---------------------------------------------------------


def test_heading_level_returns_int_when_set() -> None:
    assert heading_level(_section(**{HEADING_LEVEL_KEY: 3})) == 3


def test_heading_level_none_when_absent() -> None:
    assert heading_level(_section()) is None


def test_heading_level_type_error_on_wrong_type() -> None:
    with pytest.raises(TypeError, match="heading_level"):
        heading_level(_section(**{HEADING_LEVEL_KEY: "2"}))


def test_heading_level_rejects_bool() -> None:
    # bool is technically an int subclass; make sure we reject it explicitly.
    with pytest.raises(TypeError, match="heading_level"):
        heading_level(_section(**{HEADING_LEVEL_KEY: True}))


# ---- is_navigation --------------------------------------------------------


def test_is_navigation_true_when_flag_set() -> None:
    assert is_navigation(_section(**{NAVIGATION_KEY: True})) is True


def test_is_navigation_false_when_absent() -> None:
    assert is_navigation(_section()) is False


def test_is_navigation_false_when_flag_falsy() -> None:
    assert is_navigation(_section(**{NAVIGATION_KEY: False})) is False


# ---- anchor ---------------------------------------------------------------


def test_anchor_returns_string() -> None:
    assert anchor(_section(**{ANCHOR_KEY: "setup"})) == "setup"


def test_anchor_none_when_absent() -> None:
    assert anchor(_section()) is None


def test_anchor_none_when_empty_string() -> None:
    # Empty anchor id has no meaning — treat as absent.
    assert anchor(_section(**{ANCHOR_KEY: ""})) is None


def test_anchor_type_error_on_non_string() -> None:
    with pytest.raises(TypeError, match="anchor"):
        anchor(_section(**{ANCHOR_KEY: 42}))


# ---- chunk_anchors --------------------------------------------------------


def test_chunk_anchors_returns_tuple() -> None:
    assert chunk_anchors(_chunk(**{ANCHORS_KEY: ("top", "install")})) == (
        "top",
        "install",
    )


def test_chunk_anchors_empty_when_absent() -> None:
    assert chunk_anchors(_chunk()) == ()


def test_chunk_anchors_type_error_on_wrong_type() -> None:
    with pytest.raises(TypeError, match="anchors"):
        chunk_anchors(_chunk(**{ANCHORS_KEY: "top"}))
