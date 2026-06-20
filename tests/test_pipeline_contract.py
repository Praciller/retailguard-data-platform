from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from retailguard.paths import DataPaths
from retailguard.quality import run_quality_gate
from retailguard.synthetic import generate_campaign_events, generate_retail_dataset
from retailguard.timeutils import UTC
from retailguard.warehouse import (
    load_duckdb_warehouse,
    warehouse_metrics,
    write_local_evidence_report,
)


def test_synthetic_dataset_is_deterministic_and_reconciled() -> None:
    dataset = generate_retail_dataset()

    assert len(dataset.customers) == 100
    assert len(dataset.products) == 50
    assert len(dataset.orders) == 500
    assert len(dataset.payments) == 500
    assert len(dataset.order_items) == 1_250

    item_total = sum(
        (row["unit_price"] * row["quantity"] for row in dataset.order_items),
        start=Decimal("0"),
    )
    payment_total = sum(
        (row["payment_amount"] for row in dataset.payments),
        start=Decimal("0"),
    )
    assert item_total == payment_total


def test_campaign_events_are_not_future_dated() -> None:
    events = generate_campaign_events()
    latest = max(datetime.fromisoformat(row["updated_at"]) for row in events)

    assert len(events) == 300
    assert latest < datetime(2026, 6, 14, tzinfo=UTC)


def test_quality_gate_blocks_bad_fixture(silver_paths: DataPaths) -> None:
    good_report = run_quality_gate(silver_paths, run_id="good")
    fixture = Path(__file__).parents[1] / "quality" / "fixtures" / "bad_order_items.csv"
    bad_report = run_quality_gate(
        silver_paths,
        run_id="bad",
        bad_fixture=fixture,
        raise_on_failure=False,
    )

    assert good_report["status"] == "passed"
    assert bad_report["status"] == "failed"
    assert bad_report["blocking_failures"] >= 1


def test_warehouse_load_is_idempotent(silver_paths: DataPaths) -> None:
    first = load_duckdb_warehouse(silver_paths, run_id="first")
    second = load_duckdb_warehouse(silver_paths, run_id="second")
    metrics = warehouse_metrics(silver_paths)

    assert first["fact_sales_rows"] == 1_250
    assert second["fact_sales_rows"] == 1_250
    assert metrics["fact_sales_rows"] == metrics["distinct_sales_keys"]
    assert metrics["pipeline_runs"] == 2

    connection = duckdb.connect(
        str(silver_paths.warehouse / "retailguard.duckdb"),
        read_only=True,
    )
    try:
        columns = {
            row[0].lower()
            for row in connection.execute("DESCRIBE dim_customer").fetchall()
        }
    finally:
        connection.close()

    assert not columns & {"full_name", "email", "phone", "address"}


def test_local_evidence_report_summarizes_demo(silver_paths: DataPaths) -> None:
    first = load_duckdb_warehouse(silver_paths, run_id="first")
    second = load_duckdb_warehouse(silver_paths, run_id="second")
    quality = run_quality_gate(silver_paths, run_id="good")
    report_path = write_local_evidence_report(
        silver_paths,
        {
            "source_counts": {"customers": 100, "orders": 500},
            "first_run": {
                "extract": {
                    "sources": [
                        {"source": "customers", "rows": 100},
                        {"source": "orders", "rows": 500},
                        {"source": "campaign_events", "rows": 300},
                    ]
                },
                "transform": {"counts": {"customers": 100, "orders": 500, "campaign_events": 300}},
            },
            "quality": quality,
            "warehouse": first,
            "idempotency": {
                "first_fact_rows": first["fact_sales_rows"],
                "second_fact_rows": second["fact_sales_rows"],
                "distinct_sales_keys": second["distinct_sales_keys"],
                "passed": True,
            },
            "bad_data_gate": {
                "status": "failed",
                "blocking_failures": 3,
                "warehouse_load_attempted": False,
            },
        },
    )

    report = report_path.read_text(encoding="utf-8")
    assert "# RetailGuard Local Portfolio Evidence" in report
    assert "No cloud account, billing account, or free trial was used." in report
    assert "| Revenue |" in report
    assert "| raw_pii_absent_from_silver | passed | 0 |" in report
    assert "| fact_sales | BASE TABLE | 1,250 |" in report
    assert "| campaign_events | 300 | 300 |" in report
    assert "| Passed | yes |" in report
