"""File-source abstraction for the Markdown plugin.

`RawFileProvider` is the contract MarkdownSource consumes: async
iteration over `RawFile` snapshots plus lifecycle. Two implementations
ship with the library:

- `LocalDirectoryProvider` — walks a filesystem tree.
- `GitCloneProvider` — clones a remote git repo (shallow) into a
  temporary or persistent cache dir, then walks the checkout.

Consumers can drop in their own provider (S3-bucket, VCS-specific API,
mock for tests) without touching MarkdownSource.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import aiofiles
import aiofiles.os

from refweave.plugins.source.markdown.types import RawFile

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "GitCloneProvider",
    "LocalDirectoryProvider",
    "RawFileProvider",
]


@runtime_checkable
class RawFileProvider(Protocol):
    """Yields `RawFile` snapshots for the Markdown source to process.

    `iter()` walks the underlying storage, applies pattern/exclude
    filters, and yields one RawFile per matched file. `aclose()`
    releases any owned resources (temp directories, network handles).

    Implementations should be safe to iterate multiple times if the
    underlying data hasn't changed — but this is not required by the
    protocol, and `MarkdownSource` currently iterates once per sync.
    """

    def iter(self) -> AsyncIterator[RawFile]: ...

    async def aclose(self) -> None: ...


# ---- shared walker helper --------------------------------------------------


async def _read_files(
    root: Path,
    entries: list[tuple[Path, datetime]],
    exclude_patterns: Sequence[str],
) -> AsyncIterator[RawFile]:
    """Read each entry via aiofiles and yield the RawFile.

    Providers precompute `entries` (path + updated_at) in a single
    `asyncio.to_thread` trip so the async loop below only does
    non-blocking read + fnmatch filter. No `stat()` per file here.
    """
    seen: set[str] = set()
    for path, updated_at in entries:
        relpath = path.relative_to(root).as_posix()
        if relpath in seen:
            continue
        if any(fnmatch.fnmatch(relpath, ex) for ex in exclude_patterns):
            continue
        seen.add(relpath)
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                body = await f.read()
        except OSError as exc:
            logger.warning("failed to read %s: %s", relpath, exc)
            continue
        except UnicodeDecodeError as exc:
            # Skip non-UTF-8 files (Windows-1251, latin-1, binary
            # mis-tagged as .md). One bad file must not stop the whole
            # sync — logging surfaces it for the caller.
            logger.warning("non-UTF-8 file skipped: %s: %s", relpath, exc)
            continue
        yield RawFile(path=relpath, body=body, updated_at=updated_at)


def _local_scan(
    root: Path,
    patterns: Sequence[str],
) -> list[tuple[Path, datetime]]:
    """Blocking rglob + per-file stat; call under `asyncio.to_thread`.

    Returns `[(absolute_path, filesystem_mtime), ...]`, sorted. Files
    whose stat fails are silently skipped — read attempt in the async
    loop will not have a mtime for them anyway.
    """
    found: list[tuple[Path, datetime]] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if not path.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError as exc:
                logger.warning("failed to stat %s: %s", path, exc)
                continue
            found.append((path, mtime))
    found.sort(key=lambda pair: pair[0])
    return found


def _git_scan(
    walk_root: Path,
    patterns: Sequence[str],
    commit_times: dict[str, datetime],
    tip_time: datetime,
    subdir: str,
) -> list[tuple[Path, datetime]]:
    """Blocking rglob + commit-time lookup; call under `asyncio.to_thread`.

    `commit_times` and `tip_time` are precomputed once per clone via
    `_resolve_commit_times`. Files not in the map fall back to
    `tip_time`, so `updated_at` stays stable across re-syncs of an
    unchanged repo.
    """
    found: list[tuple[Path, datetime]] = []
    for pattern in patterns:
        for path in walk_root.rglob(pattern):
            if not path.is_file():
                continue
            relpath = path.relative_to(walk_root).as_posix()
            key = f"{subdir}/{relpath}" if subdir else relpath
            found.append((path, commit_times.get(key, tip_time)))
    found.sort(key=lambda pair: pair[0])
    return found


# ---- providers -------------------------------------------------------------


class LocalDirectoryProvider:
    """Walks a local directory tree and yields `RawFile` per matched file.

    `updated_at` is the filesystem mtime — so `MarkdownSource`'s
    skip-detection on re-sync picks up any file whose mtime advanced.

    `patterns` — POSIX-style globs relative to `root` (default:
    `("**/*.md",)`).
    `exclude_patterns` — fnmatch patterns applied to each match's
    corpus-relative path (POSIX style).
    """

    def __init__(
        self,
        root: Path | str,
        *,
        patterns: Sequence[str] = ("**/*.md",),
        exclude_patterns: Sequence[str] = (),
    ) -> None:
        self._root = Path(root).resolve()
        self._patterns = tuple(patterns)
        self._exclude = tuple(exclude_patterns)

    async def iter(self) -> AsyncIterator[RawFile]:
        entries = await asyncio.to_thread(_local_scan, self._root, self._patterns)
        async for raw in _read_files(self._root, entries, self._exclude):
            yield raw

    async def aclose(self) -> None:
        return None


class GitCloneProvider:
    """Clones a git repo (shallow) and yields `RawFile` per matched file.

    Shells out to the system `git` binary — no `git` in PATH means
    construction succeeds but `iter()` fails on the first call. Auth
    (SSH keys, HTTPS credential helper) is whatever git is configured
    with locally.

    `url` — remote URL (`https://…`, `git@…`, or local path).
    `ref` — branch or tag to check out (default `HEAD`). Commit hashes
    are NOT supported by shallow clone; pass a branch or tag.
    `subdir` — walk only this subtree of the checkout (POSIX-style,
    relative to repo root). Empty = whole repo.
    `cache_dir` — if provided and non-existent (or empty), clones
    there and reuses across runs (`git fetch` on next `iter`). If
    None, clones into a fresh temp dir on each iter and removes it on
    `aclose()`.
    `patterns` / `exclude_patterns` — same semantics as
    `LocalDirectoryProvider`.

    `updated_at` on each RawFile is the timestamp of the last commit
    that touched that file — not the clone/checkout time, so
    skip-detection works across syncs.
    """

    def __init__(
        self,
        *,
        url: str,
        ref: str = "HEAD",
        subdir: str = "",
        cache_dir: Path | str | None = None,
        patterns: Sequence[str] = ("**/*.md",),
        exclude_patterns: Sequence[str] = (),
    ) -> None:
        self._url = url
        self._ref = ref
        self._subdir = subdir.strip("/")
        self._cache_dir = Path(cache_dir).resolve() if cache_dir is not None else None
        self._patterns = tuple(patterns)
        self._exclude = tuple(exclude_patterns)
        self._temp_dir: Path | None = None
        self._clone_root: Path | None = None

    async def iter(self) -> AsyncIterator[RawFile]:
        clone_root = await self._prepare_clone()
        walk_root = clone_root / self._subdir if self._subdir else clone_root
        # Shallow clones (--depth 1) may not expose all files through
        # `git log --name-only` — anything the log doesn't mention falls
        # back to the tip commit's timestamp. That keeps `updated_at`
        # stable across re-syncs of an unchanged repo (as opposed to
        # `datetime.now()` which would look "new" every time).
        commit_times, tip_time = await asyncio.to_thread(
            _resolve_commit_times,
            clone_root,
        )
        entries = await asyncio.to_thread(
            _git_scan,
            walk_root,
            self._patterns,
            commit_times,
            tip_time,
            self._subdir,
        )
        async for raw in _read_files(walk_root, entries, self._exclude):
            yield raw

    async def aclose(self) -> None:
        if self._temp_dir is not None:
            await asyncio.to_thread(shutil.rmtree, self._temp_dir, True)
            self._temp_dir = None
            self._clone_root = None

    async def _prepare_clone(self) -> Path:
        if self._clone_root is not None:
            return self._clone_root
        if self._cache_dir is not None:
            self._clone_root = await asyncio.to_thread(
                _prepare_cached_clone,
                self._cache_dir,
                self._url,
                self._ref,
            )
        else:
            self._temp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="refweave-git-"))
            await asyncio.to_thread(
                _clone_shallow,
                self._url,
                self._ref,
                self._temp_dir,
            )
            self._clone_root = self._temp_dir
        return self._clone_root


# ---- git shell helpers (blocking; call under asyncio.to_thread) ------------


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Run `git <args>`, return stdout. Raise CalledProcessError on failure.

    `args` are caller-supplied; `git` must be on PATH — the provider
    documents this and the caller controls the URL passed to `git clone`.
    See SECURITY.md → GitCloneProvider.
    """
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607 — git on PATH is the documented contract
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _clone_shallow(url: str, ref: str, dest: Path) -> None:
    if ref == "HEAD":
        _run_git("clone", "--depth", "1", url, str(dest))
    else:
        _run_git("clone", "--depth", "1", "--branch", ref, url, str(dest))


def _prepare_cached_clone(cache_dir: Path, url: str, ref: str) -> Path:
    """Reuse `cache_dir` if it already contains a matching clone, else clone.

    `matching` means: it's a git repo AND `origin` remote points at `url`.
    Anything else — refuse to write into the directory (safer than nuking
    user data).
    """
    if cache_dir.exists() and any(cache_dir.iterdir()):
        remote = _run_git("config", "--get", "remote.origin.url", cwd=cache_dir).strip()
        if remote != url:
            msg = (
                f"cache_dir {cache_dir} already exists but its origin ({remote!r}) "
                f"differs from requested url ({url!r}); refusing to overwrite"
            )
            raise RuntimeError(msg)
        _run_git("fetch", "origin", cwd=cache_dir)
        _run_git("checkout", ref, cwd=cache_dir)
        reset_target = f"origin/{ref}" if ref != "HEAD" else "FETCH_HEAD"
        _run_git("reset", "--hard", reset_target, cwd=cache_dir)
    else:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _clone_shallow(url, ref, cache_dir)
    return cache_dir


def _resolve_commit_times(clone_root: Path) -> tuple[dict[str, datetime], datetime]:
    """Return `({path: last_commit_time}, tip_commit_time)` for the clone.

    `git log --name-only --format=%ct` gives per-file last-touch times in
    one pass (no per-file subprocess). Shallow clones may omit files that
    weren't touched by the latest commit — callers fall back to the tip
    commit's timestamp for anything missing.
    """
    tip_out = _run_git("log", "-1", "--format=%ct", cwd=clone_root).strip()
    tip_time = datetime.fromtimestamp(int(tip_out), tz=UTC)

    log_out = _run_git(
        "log",
        "--name-only",
        "--format=%ct",
        "--diff-filter=AMR",
        cwd=clone_root,
    )
    times: dict[str, datetime] = {}
    current_ts: datetime | None = None
    for raw_line in log_out.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.isdigit():
            current_ts = datetime.fromtimestamp(int(line), tz=UTC)
            continue
        if current_ts is not None and line not in times:
            times[line] = current_ts
    return times, tip_time
