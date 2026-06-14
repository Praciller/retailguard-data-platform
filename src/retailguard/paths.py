from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from retailguard.config import Settings


@dataclass(frozen=True)
class DataPaths:
    root: Path
    bronze: Path
    silver: Path
    state: Path
    warehouse: Path
    quality: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> DataPaths:
        root = settings.data_root
        paths = cls(
            root=root,
            bronze=root / "bronze",
            silver=root / "silver",
            state=root / "state",
            warehouse=root / "warehouse",
            quality=root / "quality",
        )
        for path in paths.__dict__.values():
            path.mkdir(parents=True, exist_ok=True)
        return paths
