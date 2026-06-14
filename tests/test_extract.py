from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as parquet

from retailguard.config import Settings
from retailguard.extract import _write_bronze
from retailguard.paths import DataPaths


def test_bronze_timestamps_are_spark_compatible(tmp_path: Path) -> None:
    paths = DataPaths.from_settings(Settings(retailguard_data_root=tmp_path / "data"))
    frame = pd.DataFrame(
        {
            "event_id": ["EVT000001"],
            "updated_at": [pd.Timestamp("2026-06-01T12:34:56.123456789Z")],
        }
    )

    output = _write_bronze(
        frame,
        source_name="events",
        paths=paths,
        run_id="precision-test",
    )

    assert output is not None
    field = parquet.read_schema(output).field("updated_at")
    assert field.type.unit == "us"
