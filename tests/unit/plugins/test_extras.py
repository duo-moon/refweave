"""Contract tests for the SourceExtra base class."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import ValidationError

from refweave.plugins.extras import SourceExtra


class _DemoExtra(SourceExtra):
    NAMESPACE: ClassVar[str] = "_demo"

    name: str
    tags: tuple[str, ...] = ()


def test_write_produces_namespaced_fragment() -> None:
    fragment = _DemoExtra(name="alpha", tags=("a", "b")).write()
    assert fragment == {"_demo": {"name": "alpha", "tags": ["a", "b"]}}


def test_read_returns_typed_view() -> None:
    metadata = {"_demo": {"name": "alpha", "tags": ("a", "b")}}
    extra = _DemoExtra.read(metadata)
    assert extra is not None
    assert extra.name == "alpha"
    assert extra.tags == ("a", "b")


def test_read_returns_none_when_absent() -> None:
    assert _DemoExtra.read({}) is None
    assert _DemoExtra.read({"other": {}}) is None


def test_roundtrip_via_metadata() -> None:
    original = _DemoExtra(name="alpha", tags=("x",))
    metadata = {**original.write(), "unrelated": 42}
    restored = _DemoExtra.read(metadata)
    assert restored == original


def test_read_raises_on_schema_mismatch() -> None:
    with pytest.raises(ValidationError):
        _DemoExtra.read({"_demo": {"name": 123}})


def test_frozen_instance() -> None:
    extra = _DemoExtra(name="alpha")
    with pytest.raises(ValidationError):
        extra.name = "beta"


def test_forbids_extra_fields_on_construction() -> None:
    with pytest.raises(ValidationError):
        _DemoExtra(name="alpha", unknown="x")  # type: ignore[call-arg]
