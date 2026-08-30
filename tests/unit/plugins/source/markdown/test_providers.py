"""Tests for RawFileProvider implementations."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from refweave.plugins.source.markdown.providers import (
    GitCloneProvider,
    LocalDirectoryProvider,
)

if TYPE_CHECKING:
    from pathlib import Path

    from refweave.plugins.source.markdown.types import RawFile


async def _collect(provider: LocalDirectoryProvider | GitCloneProvider) -> list[RawFile]:
    return [raw async for raw in provider.iter()]


# ---- LocalDirectoryProvider ------------------------------------------------


@pytest.mark.asyncio
async def test_local_iter_yields_matching_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path)
    files = await _collect(provider)
    paths = {f.path for f in files}
    assert paths == {"a.md", "b.md"}


@pytest.mark.asyncio
async def test_local_iter_respects_subdir_patterns(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "keep.md").write_text("doc", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "skip.md").write_text("no", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path, patterns=("docs/**/*.md",))
    files = await _collect(provider)
    assert {f.path for f in files} == {"docs/keep.md"}


@pytest.mark.asyncio
async def test_local_iter_applies_exclude_patterns(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("k", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "wip.md").write_text("w", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path, exclude_patterns=("drafts/**",))
    files = await _collect(provider)
    assert {f.path for f in files} == {"keep.md"}


@pytest.mark.asyncio
async def test_local_iter_uses_filesystem_mtime(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("body", encoding="utf-8")
    # Backdate the file — provider must report that time, not "now".
    past = datetime(2024, 6, 1, 12, 0, tzinfo=UTC).timestamp()
    os.utime(file, (past, past))

    provider = LocalDirectoryProvider(tmp_path)
    files = await _collect(provider)
    assert files[0].updated_at == datetime.fromtimestamp(past, tz=UTC)


@pytest.mark.asyncio
async def test_local_aclose_is_noop(tmp_path: Path) -> None:
    provider = LocalDirectoryProvider(tmp_path)
    await provider.aclose()  # must not raise


@pytest.mark.asyncio
async def test_local_iter_skips_non_utf8_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Windows-1251/latin-1 files must not stop the whole sync."""
    (tmp_path / "good.md").write_text("# good", encoding="utf-8")
    # Bytes valid in cp1251 but not decodable as UTF-8.
    (tmp_path / "bad.md").write_bytes(b"# \xd0\xf1\xf2\xf0")

    provider = LocalDirectoryProvider(tmp_path)
    with caplog.at_level("WARNING"):
        files = await _collect(provider)

    paths = {f.path for f in files}
    assert paths == {"good.md"}
    assert any("non-UTF-8" in rec.message for rec in caplog.records)


# ---- GitCloneProvider ------------------------------------------------------


_HAS_GIT = shutil.which("git") is not None
skip_no_git = pytest.mark.skipif(not _HAS_GIT, reason="git binary required")


def _init_repo(root: Path, files: dict[str, str]) -> Path:
    """Create a bare-usable git repo at `root` populated with `files`."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=root, check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=root, check=True,
    )
    return root


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_iter_yields_repo_files(tmp_path: Path) -> None:
    origin = _init_repo(
        tmp_path / "origin",
        {"a.md": "# A", "b.md": "# B", "ignored.txt": "x"},
    )
    provider = GitCloneProvider(url=f"file://{origin}", ref="main")
    try:
        files = await _collect(provider)
        assert {f.path for f in files} == {"a.md", "b.md"}
    finally:
        await provider.aclose()


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_iter_uses_commit_timestamp(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin", {"only.md": "body"})
    # Snapshot the commit ts BEFORE entering async provider work, so the
    # sync subprocess call doesn't sit inside an async function.
    commit_ts = int(_git_head_ts(origin))
    expected = datetime.fromtimestamp(commit_ts, tz=UTC)

    provider = GitCloneProvider(url=f"file://{origin}", ref="main")
    try:
        files = await _collect(provider)
        # `updated_at` must be the commit time (not "now") — that's how
        # sync-skip detection stays deterministic across re-runs.
        assert files[0].updated_at == expected
    finally:
        await provider.aclose()


def _git_head_ts(repo: Path) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%ct"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_subdir_filter(tmp_path: Path) -> None:
    origin = _init_repo(
        tmp_path / "origin",
        {"docs/a.md": "A", "docs/nested/b.md": "B", "src/skip.md": "S"},
    )
    provider = GitCloneProvider(url=f"file://{origin}", ref="main", subdir="docs")
    try:
        files = await _collect(provider)
        # Paths returned by the provider are relative to walk_root (the subdir),
        # so consumers see `a.md`, `nested/b.md` — never the `src/` tree.
        assert {f.path for f in files} == {"a.md", "nested/b.md"}
    finally:
        await provider.aclose()


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_temp_dir_cleaned_on_aclose(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin", {"a.md": "A"})
    provider = GitCloneProvider(url=f"file://{origin}", ref="main")
    await _collect(provider)
    temp = provider._temp_dir
    assert temp is not None
    assert temp.exists()
    await provider.aclose()
    assert not temp.exists()


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_cache_dir_reused(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin", {"a.md": "A"})
    cache = tmp_path / "cache"

    # First run: clone into cache.
    p1 = GitCloneProvider(url=f"file://{origin}", ref="main", cache_dir=cache)
    files1 = await _collect(p1)
    await p1.aclose()
    # Cache must persist after aclose (it's user-owned, not temp).
    assert cache.exists()
    assert (cache / ".git").exists()

    # Second run: reuse cache, results unchanged.
    p2 = GitCloneProvider(url=f"file://{origin}", ref="main", cache_dir=cache)
    files2 = await _collect(p2)
    await p2.aclose()
    assert {f.path for f in files1} == {f.path for f in files2}


@skip_no_git
@pytest.mark.asyncio
async def test_git_clone_cache_dir_url_mismatch_refuses(tmp_path: Path) -> None:
    origin_a = _init_repo(tmp_path / "a", {"a.md": "A"})
    origin_b = _init_repo(tmp_path / "b", {"b.md": "B"})
    cache = tmp_path / "cache"

    p1 = GitCloneProvider(url=f"file://{origin_a}", ref="main", cache_dir=cache)
    await _collect(p1)
    await p1.aclose()

    # Second provider aimed at a different origin must NOT nuke the existing
    # clone — the safeguard is «refuse if origin URL doesn't match».
    p2 = GitCloneProvider(url=f"file://{origin_b}", ref="main", cache_dir=cache)
    with pytest.raises(RuntimeError, match="differs from requested url"):
        await _collect(p2)
    await p2.aclose()
