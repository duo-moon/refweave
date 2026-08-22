from pathlib import Path

import pytest

import refweave
from refweave import Refweave


def test_version_string_present() -> None:
    assert isinstance(refweave.__version__, str)
    assert refweave.__version__


def test_refweave_construction(tmp_path: Path) -> None:
    rw = Refweave(storage=tmp_path)
    assert rw.storage == tmp_path
    assert rw.sources == []


def test_refweave_accepts_string_storage(tmp_path: Path) -> None:
    rw = Refweave(storage=str(tmp_path))
    assert rw.storage == tmp_path


async def test_sync_raises_not_implemented(tmp_path: Path) -> None:
    rw = Refweave(storage=tmp_path)
    with pytest.raises(NotImplementedError):
        await rw.sync("some-source")


async def test_recompute_clusters_raises_not_implemented(tmp_path: Path) -> None:
    rw = Refweave(storage=tmp_path)
    with pytest.raises(NotImplementedError):
        await rw.recompute_clusters()


async def test_related_raises_not_implemented(tmp_path: Path) -> None:
    rw = Refweave(storage=tmp_path)
    with pytest.raises(NotImplementedError):
        await rw.related("chunk-id", channels=["same_target"])
