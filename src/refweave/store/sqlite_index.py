from pathlib import Path


class SqliteIndex:
    """Rebuildable SQLite index over the FS store.

    Schema: refweave-plan.md §6. Skeleton for M0; implementation lands in M1.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    async def close(self) -> None:
        return None
