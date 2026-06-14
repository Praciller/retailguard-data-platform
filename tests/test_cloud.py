from __future__ import annotations

from pathlib import Path

import pytest

from retailguard.cloud import (
    CloudPublishError,
    _require_passed_quality_gate,
    _warehouse_statements,
    cloud_plan,
)
from retailguard.config import Settings
from retailguard.paths import DataPaths
from retailguard.state import write_json


def _paths(tmp_path: Path) -> DataPaths:
    settings = Settings(
        retailguard_project_root=tmp_path,
        retailguard_data_root=tmp_path / "data",
    )
    paths = DataPaths.from_settings(settings)
    for table in (
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "campaign_events",
    ):
        table_path = paths.silver / table
        table_path.mkdir(parents=True, exist_ok=True)
        (table_path / "part-00000.parquet").write_bytes(b"PAR1")
    return paths


def test_cloud_plan_lists_only_silver_parquet(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    settings = Settings(
        retailguard_project_root=tmp_path,
        retailguard_data_root=paths.root,
        gcs_bucket="retailguard-data-platform-111122397706",
    )

    plan = cloud_plan(settings, paths)

    assert plan["project_id"] == "retailguard-data-platform"
    assert plan["total_upload_bytes"] == 24
    assert set(plan["silver_files"]) == {
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "campaign_events",
    }


def test_cloud_plan_rejects_missing_table(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (paths.silver / "payments" / "part-00000.parquet").unlink()

    with pytest.raises(CloudPublishError, match="payments"):
        cloud_plan(Settings(retailguard_data_root=paths.root), paths)


def test_bigquery_sql_uses_qualified_objects() -> None:
    statements = dict(_warehouse_statements("retailguard-data-platform", "retailguard"))

    assert len(statements) == 11
    assert (
        "`retailguard-data-platform.retailguard.fact_sales`"
        in statements["vw_executive_summary"]
    )
    assert "SAFE_DIVIDE" in statements["vw_campaign_performance"]
    assert "CREATE OR REPLACE TABLE" in statements["fact_sales"]


def test_cloud_gate_uses_quality_for_last_loaded_run(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_json(paths.state / "last_warehouse_load.json", {"run_id": "good-run"})
    write_json(paths.quality / "good-run.json", {"run_id": "good-run", "status": "passed"})
    write_json(paths.quality / "latest.json", {"run_id": "bad-demo", "status": "failed"})

    assert _require_passed_quality_gate(paths) == "good-run"
