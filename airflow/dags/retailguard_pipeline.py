from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

from retailguard.config import get_settings
from retailguard.db import apply_schema, create_db_engine, wait_for_database
from retailguard.extract import extract_all, new_run_id
from retailguard.paths import DataPaths
from retailguard.quality import run_quality_gate
from retailguard.transform import transform_bronze_to_silver
from retailguard.warehouse import load_duckdb_warehouse


def _context():
    settings = get_settings()
    paths = DataPaths.from_settings(settings)
    return settings, paths


@dag(
    dag_id="retailguard_pipeline",
    description="Privacy-aware retail batch pipeline with a blocking quality gate",
    schedule="0 1 * * *",
    start_date=pendulum.datetime(2026, 6, 1, tz="Asia/Bangkok"),
    catchup=False,
    default_args={
        "owner": "data-engineering",
        "retries": int(os.getenv("RETAILGUARD_AIRFLOW_RETRIES", "2")),
        "retry_delay": timedelta(minutes=2),
    },
    tags=["portfolio", "retail", "spark", "quality"],
)
def retailguard_pipeline():
    @task
    def create_run() -> str:
        return new_run_id()

    @task
    def extract(pipeline_run_id: str) -> dict:
        settings, paths = _context()
        engine = create_db_engine(settings)
        wait_for_database(engine)
        apply_schema(
            engine,
            settings.project_root / "sql" / "oltp" / "001_schema.sql",
        )
        return extract_all(engine, settings, paths, run_id=pipeline_run_id)

    @task
    def transform(pipeline_run_id: str) -> dict:
        settings, paths = _context()
        return transform_bronze_to_silver(settings, paths, run_id=pipeline_run_id)

    @task
    def quality(pipeline_run_id: str) -> dict:
        _, paths = _context()
        return run_quality_gate(paths, run_id=pipeline_run_id)

    @task
    def load(pipeline_run_id: str) -> dict:
        _, paths = _context()
        return load_duckdb_warehouse(paths, run_id=pipeline_run_id)

    pipeline_run_id = create_run()
    extracted = extract(pipeline_run_id)
    transformed = transform(pipeline_run_id)
    checked = quality(pipeline_run_id)
    loaded = load(pipeline_run_id)

    extracted >> transformed >> checked >> loaded


retailguard_pipeline()
