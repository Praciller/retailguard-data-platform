from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import typer

from retailguard.cloud import cloud_plan, cloud_status, publish_cloud
from retailguard.config import get_settings
from retailguard.db import (
    apply_schema,
    create_db_engine,
    seed_database,
    source_counts,
    wait_for_database,
)
from retailguard.extract import extract_all, new_run_id, reset_ingestion_state
from retailguard.paths import DataPaths
from retailguard.quality import QualityGateError, run_quality_gate
from retailguard.transform import transform_bronze_to_silver
from retailguard.warehouse import load_duckdb_warehouse, warehouse_metrics

app = typer.Typer(
    no_args_is_help=True,
    help="RetailGuard privacy-aware retail data platform.",
)


def _context() -> tuple[Any, DataPaths, Any]:
    settings = get_settings()
    paths = DataPaths.from_settings(settings)
    engine = create_db_engine(settings)
    return settings, paths, engine


def _print(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _schema_path(settings: Any) -> Path:
    return settings.project_root / "sql" / "oltp" / "001_schema.sql"


def _bad_fixture_path(settings: Any) -> Path:
    return settings.project_root / "quality" / "fixtures" / "bad_order_items.csv"


@app.command()
def init_db() -> None:
    """Wait for PostgreSQL and apply the OLTP schema."""
    settings, _, engine = _context()
    wait_for_database(engine)
    apply_schema(engine, _schema_path(settings))
    _print({"status": "ready"})


@app.command()
def seed(reset: bool = typer.Option(True, help="Reset source tables before seeding.")) -> None:
    """Generate and load deterministic synthetic retail records."""
    settings, _, engine = _context()
    wait_for_database(engine)
    apply_schema(engine, _schema_path(settings))
    _print(seed_database(engine, reset=reset))


@app.command()
def extract(run_id: str | None = None) -> None:
    """Incrementally extract PostgreSQL and mock API data to Bronze Parquet."""
    settings, paths, engine = _context()
    _print(extract_all(engine, settings, paths, run_id=run_id))


@app.command()
def transform(run_id: str | None = None) -> None:
    """Transform all Bronze snapshots into protected Silver Parquet."""
    settings, paths, _ = _context()
    current_run_id = run_id or new_run_id()
    _print(transform_bronze_to_silver(settings, paths, run_id=current_run_id))


@app.command()
def quality(
    run_id: str | None = None,
    bad_fixture: bool = typer.Option(False, help="Inject the tracked bad-data fixture."),
    allow_failure: bool = typer.Option(False, help="Return the report instead of raising."),
) -> None:
    """Run blocking data-quality and PII checks."""
    settings, paths, _ = _context()
    fixture = _bad_fixture_path(settings) if bad_fixture else None
    report = run_quality_gate(
        paths,
        run_id=run_id or new_run_id(),
        bad_fixture=fixture,
        raise_on_failure=not allow_failure,
    )
    _print(report)


@app.command()
def load(run_id: str | None = None) -> None:
    """Create or replace the local DuckDB star schema and serving views."""
    _, paths, _ = _context()
    _print(load_duckdb_warehouse(paths, run_id=run_id or new_run_id()))


def _run_pipeline(*, run_id: str) -> dict[str, Any]:
    settings, paths, engine = _context()
    extraction = extract_all(engine, settings, paths, run_id=run_id)
    transformation = transform_bronze_to_silver(settings, paths, run_id=run_id)
    quality_report = run_quality_gate(paths, run_id=run_id)
    warehouse = load_duckdb_warehouse(paths, run_id=run_id)
    return {
        "run_id": run_id,
        "extract": extraction,
        "transform": transformation,
        "quality": quality_report,
        "warehouse": warehouse,
    }


@app.command()
def run() -> None:
    """Run extract, transform, quality, and local warehouse load."""
    _print(_run_pipeline(run_id=new_run_id()))


@app.command()
def demo(reset_data: bool = True) -> None:
    """Run the complete local acceptance demo, including idempotency and bad data."""
    settings, paths, engine = _context()
    wait_for_database(engine)
    apply_schema(engine, _schema_path(settings))

    if reset_data:
        root = paths.root.resolve()
        if root.name != "data":
            raise RuntimeError(f"Refusing to reset unexpected data directory: {root}")
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        paths = DataPaths.from_settings(settings)
        reset_ingestion_state(paths)

    seeded = seed_database(engine, reset=True)
    first = _run_pipeline(run_id=f"{new_run_id()}-first")
    first_metrics = warehouse_metrics(paths)
    second = _run_pipeline(run_id=f"{new_run_id()}-second")
    second_metrics = warehouse_metrics(paths)

    if first_metrics["fact_sales_rows"] != second_metrics["fact_sales_rows"]:
        raise RuntimeError("Idempotency failed: fact row count changed on the second run.")
    if second_metrics["fact_sales_rows"] != second_metrics["distinct_sales_keys"]:
        raise RuntimeError("Idempotency failed: duplicate sales keys exist.")

    fixture = _bad_fixture_path(settings)
    bad_report = run_quality_gate(
        paths,
        run_id=f"{new_run_id()}-bad-fixture",
        bad_fixture=fixture,
        raise_on_failure=False,
    )
    if bad_report["status"] != "failed":
        raise RuntimeError("Bad-data fixture did not fail the quality gate.")

    _print(
        {
            "status": "passed",
            "seeded": seeded,
            "source_counts": source_counts(engine),
            "first_run": first,
            "second_run": second,
            "idempotency": {
                "first_fact_rows": first_metrics["fact_sales_rows"],
                "second_fact_rows": second_metrics["fact_sales_rows"],
                "distinct_sales_keys": second_metrics["distinct_sales_keys"],
                "passed": True,
            },
            "bad_data_gate": {
                "status": bad_report["status"],
                "blocking_failures": bad_report["blocking_failures"],
                "warehouse_load_attempted": False,
            },
        }
    )


@app.command()
def status() -> None:
    """Show source and local warehouse status."""
    _, paths, engine = _context()
    payload: dict[str, Any] = {"warehouse": warehouse_metrics(paths)}
    try:
        payload["source"] = source_counts(engine)
    except Exception as error:  # noqa: BLE001
        payload["source"] = {"available": False, "error": str(error)}
    _print(payload)


@app.command("cloud-plan")
def cloud_plan_cmd() -> None:
    """Show the protected cloud publish plan without making changes."""
    settings, paths, _ = _context()
    _print(cloud_plan(settings, paths))


@app.command("publish-cloud")
def publish_cloud_cmd() -> None:
    """Publish protected Silver data and serving views to GCS and BigQuery."""
    settings, paths, _ = _context()
    _print(publish_cloud(settings, paths))


@app.command("cloud-status")
def cloud_status_cmd() -> None:
    """Show whether the configured GCS bucket and BigQuery dataset exist."""
    settings, _, _ = _context()
    _print(cloud_status(settings))


def main() -> None:
    try:
        app()
    except QualityGateError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


if __name__ == "__main__":
    main()
