from pathlib import Path


class FsStore:
    """Filesystem-backed store — source of truth.

    Layout: refweave-plan.md §5. Skeleton for M0; implementation lands in M1.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    async def close(self) -> None:
        return None
