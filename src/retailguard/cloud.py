from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery, storage

from retailguard.config import Settings
from retailguard.paths import DataPaths
from retailguard.state import read_json, write_json
from retailguard.timeutils import UTC

SILVER_TABLES = (
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "campaign_events",
)

_PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_DATASET_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")


class CloudPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudPlan:
    project_id: str
    location: str
    bucket: str
    dataset: str
    maximum_bytes_billed: int
    silver_files: dict[str, list[str]]
    total_upload_bytes: int


def _validate_settings(settings: Settings) -> None:
    if not _PROJECT_PATTERN.fullmatch(settings.gcp_project_id):
        raise CloudPublishError(f"Invalid GCP project ID: {settings.gcp_project_id}")
    if not _DATASET_PATTERN.fullmatch(settings.bigquery_dataset):
        raise CloudPublishError(f"Invalid BigQuery dataset: {settings.bigquery_dataset}")
    if not _BUCKET_PATTERN.fullmatch(settings.gcs_bucket):
        raise CloudPublishError(f"Invalid GCS bucket name: {settings.gcs_bucket}")
    if settings.bigquery_maximum_bytes_billed <= 0:
        raise CloudPublishError("BIGQUERY_MAXIMUM_BYTES_BILLED must be positive.")


def discover_silver_files(paths: DataPaths) -> dict[str, list[Path]]:
    files: dict[str, list[Path]] = {}
    for table in SILVER_TABLES:
        table_files = sorted((paths.silver / table).glob("*.parquet"))
        if not table_files:
            raise CloudPublishError(
                f"Silver table {table!r} has no Parquet files. Run the pipeline first."
            )
        files[table] = table_files
    return files


def cloud_plan(settings: Settings, paths: DataPaths) -> dict[str, Any]:
    _validate_settings(settings)
    files = discover_silver_files(paths)
    plan = CloudPlan(
        project_id=settings.gcp_project_id,
        location=settings.gcp_location,
        bucket=settings.gcs_bucket,
        dataset=settings.bigquery_dataset,
        maximum_bytes_billed=settings.bigquery_maximum_bytes_billed,
        silver_files={
            table: [str(path.relative_to(paths.root)) for path in table_files]
            for table, table_files in files.items()
        },
        total_upload_bytes=sum(
            path.stat().st_size for table_files in files.values() for path in table_files
        ),
    )
    return asdict(plan)


def _require_passed_quality_gate(paths: DataPaths) -> str:
    warehouse_report = read_json(paths.state / "last_warehouse_load.json", default={})
    run_id = warehouse_report.get("run_id")
    if not run_id:
        raise CloudPublishError("No successful local warehouse run is available.")

    report_path = paths.quality / f"{run_id}.json"
    report = read_json(report_path, default={})
    if report.get("status") != "passed":
        raise CloudPublishError(
            f"Warehouse run {run_id!r} has no passing quality report at {report_path}."
        )
    return str(run_id)


def _ensure_bucket(
    client: storage.Client,
    *,
    bucket_name: str,
    location: str,
) -> storage.Bucket:
    bucket = client.lookup_bucket(bucket_name)
    if bucket is None:
        bucket = client.bucket(bucket_name)
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"
        try:
            bucket = client.create_bucket(bucket, location=location)
        except Conflict as error:
            raise CloudPublishError(
                f"Bucket {bucket_name!r} already exists outside this project."
            ) from error

    if bucket.location.lower() != location.lower():
        raise CloudPublishError(
            f"Bucket location is {bucket.location}, expected {location}."
        )

    bucket.iam_configuration.uniform_bucket_level_access_enabled = True
    bucket.iam_configuration.public_access_prevention = "enforced"
    bucket.clear_lifecycle_rules()
    bucket.add_lifecycle_delete_rule(age=30)
    bucket.patch()
    return bucket


def _upload_silver(
    bucket: storage.Bucket,
    files: dict[str, list[Path]],
) -> list[dict[str, Any]]:
    uploads: list[dict[str, Any]] = []
    for table, table_files in files.items():
        prefix = f"silver/{table}/"
        for blob in bucket.list_blobs(prefix=prefix):
            blob.delete()
        for path in table_files:
            blob = bucket.blob(f"{prefix}{path.name}")
            blob.upload_from_filename(path, content_type="application/vnd.apache.parquet")
            uploads.append(
                {
                    "table": table,
                    "source": str(path),
                    "uri": f"gs://{bucket.name}/{blob.name}",
                    "bytes": path.stat().st_size,
                }
            )
    return uploads


def _ensure_dataset(
    client: bigquery.Client,
    *,
    project_id: str,
    dataset_name: str,
    location: str,
) -> bigquery.Dataset:
    dataset_id = f"{project_id}.{dataset_name}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    dataset.description = "RetailGuard protected Silver, star schema, and Looker views."
    dataset.labels = {"project": "retailguard", "environment": "portfolio"}
    client.create_dataset(dataset, exists_ok=True)
    current = client.get_dataset(dataset_id)
    if current.location.lower() != location.lower():
        raise CloudPublishError(
            f"Dataset location is {current.location}, expected {location}."
        )
    return current


def _load_silver_tables(
    client: bigquery.Client,
    *,
    project_id: str,
    dataset_name: str,
    location: str,
    bucket_name: str,
) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for table in SILVER_TABLES:
        table_id = f"{project_id}.{dataset_name}.silver_{table}"
        uri = f"gs://{bucket_name}/silver/{table}/*.parquet"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        )
        job = client.load_table_from_uri(
            uri,
            table_id,
            job_config=job_config,
            location=location,
        )
        job.result()
        destination = client.get_table(table_id)
        loaded.append({"table": table_id, "rows": destination.num_rows, "uri": uri})
    return loaded


def _warehouse_statements(project_id: str, dataset_name: str) -> list[tuple[str, str]]:
    dataset = f"`{project_id}.{dataset_name}"
    return [
        (
            "dim_customer",
            f"""
            CREATE OR REPLACE TABLE {dataset}.dim_customer` AS
            SELECT
                FARM_FINGERPRINT(customer_id) AS customer_key,
                customer_id,
                email_hash,
                phone_masked,
                customer_city,
                customer_segment,
                created_at,
                updated_at
            FROM {dataset}.silver_customers`
            """,
        ),
        (
            "dim_product",
            f"""
            CREATE OR REPLACE TABLE {dataset}.dim_product` AS
            SELECT
                FARM_FINGERPRINT(product_id) AS product_key,
                product_id,
                product_name,
                category,
                unit_price AS current_unit_price,
                is_active,
                created_at,
                updated_at
            FROM {dataset}.silver_products`
            """,
        ),
        (
            "dim_date",
            f"""
            CREATE OR REPLACE TABLE {dataset}.dim_date` AS
            WITH dates AS (
                SELECT DATE(order_timestamp) AS calendar_date
                FROM {dataset}.silver_orders`
                UNION DISTINCT
                SELECT DATE(event_timestamp) AS calendar_date
                FROM {dataset}.silver_campaign_events`
            )
            SELECT
                CAST(FORMAT_DATE('%Y%m%d', calendar_date) AS INT64) AS date_key,
                calendar_date,
                EXTRACT(YEAR FROM calendar_date) AS year,
                EXTRACT(QUARTER FROM calendar_date) AS quarter,
                EXTRACT(MONTH FROM calendar_date) AS month,
                FORMAT_DATE('%B', calendar_date) AS month_name,
                EXTRACT(DAY FROM calendar_date) AS day,
                EXTRACT(DAYOFWEEK FROM calendar_date) AS day_of_week,
                FORMAT_DATE('%A', calendar_date) AS day_name,
                EXTRACT(DAYOFWEEK FROM calendar_date) IN (1, 7) AS is_weekend
            FROM dates
            """,
        ),
        (
            "dim_channel",
            f"""
            CREATE OR REPLACE TABLE {dataset}.dim_channel` AS
            SELECT
                FARM_FINGERPRINT(channel) AS channel_key,
                channel
            FROM {dataset}.silver_campaign_events`
            GROUP BY channel
            """,
        ),
        (
            "fact_sales",
            f"""
            CREATE OR REPLACE TABLE {dataset}.fact_sales` AS
            SELECT
                i.order_item_id AS sales_key,
                i.order_item_id,
                i.order_id,
                dc.customer_key,
                dp.product_key,
                dd.date_key,
                o.order_status,
                p.payment_method,
                i.quantity,
                i.unit_price,
                i.line_amount AS gross_amount,
                o.order_timestamp,
                p.payment_timestamp
            FROM {dataset}.silver_order_items` AS i
            JOIN {dataset}.silver_orders` AS o USING (order_id)
            JOIN {dataset}.silver_payments` AS p USING (order_id)
            JOIN {dataset}.dim_customer` AS dc USING (customer_id)
            JOIN {dataset}.dim_product` AS dp USING (product_id)
            JOIN {dataset}.dim_date` AS dd
              ON dd.calendar_date = DATE(o.order_timestamp)
            """,
        ),
        (
            "fact_campaign_events",
            f"""
            CREATE OR REPLACE TABLE {dataset}.fact_campaign_events` AS
            SELECT
                e.event_id AS campaign_event_key,
                e.event_id,
                e.campaign_id,
                dc.customer_key,
                dch.channel_key,
                dd.date_key,
                e.event_type,
                e.revenue,
                e.event_timestamp
            FROM {dataset}.silver_campaign_events` AS e
            JOIN {dataset}.dim_customer` AS dc USING (customer_id)
            JOIN {dataset}.dim_channel` AS dch USING (channel)
            JOIN {dataset}.dim_date` AS dd
              ON dd.calendar_date = DATE(e.event_timestamp)
            """,
        ),
        (
            "vw_executive_summary",
            f"""
            CREATE OR REPLACE VIEW {dataset}.vw_executive_summary` AS
            SELECT
                ROUND(SUM(gross_amount), 2) AS revenue,
                COUNT(DISTINCT order_id) AS orders,
                ROUND(SAFE_DIVIDE(SUM(gross_amount), COUNT(DISTINCT order_id)), 2)
                    AS average_order_value,
                SUM(quantity) AS units
            FROM {dataset}.fact_sales`
            WHERE order_status <> 'cancelled'
            """,
        ),
        (
            "vw_daily_sales",
            f"""
            CREATE OR REPLACE VIEW {dataset}.vw_daily_sales` AS
            SELECT
                d.calendar_date,
                ROUND(SUM(f.gross_amount), 2) AS revenue,
                COUNT(DISTINCT f.order_id) AS orders,
                ROUND(
                    SAFE_DIVIDE(SUM(f.gross_amount), COUNT(DISTINCT f.order_id)),
                    2
                ) AS average_order_value,
                SUM(f.quantity) AS units
            FROM {dataset}.fact_sales` AS f
            JOIN {dataset}.dim_date` AS d USING (date_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY d.calendar_date
            """,
        ),
        (
            "vw_product_performance",
            f"""
            CREATE OR REPLACE VIEW {dataset}.vw_product_performance` AS
            SELECT
                p.category,
                p.product_name,
                ROUND(SUM(f.gross_amount), 2) AS revenue,
                SUM(f.quantity) AS units,
                COUNT(DISTINCT f.order_id) AS orders
            FROM {dataset}.fact_sales` AS f
            JOIN {dataset}.dim_product` AS p USING (product_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY p.category, p.product_name
            """,
        ),
        (
            "vw_customer_segments",
            f"""
            CREATE OR REPLACE VIEW {dataset}.vw_customer_segments` AS
            SELECT
                c.customer_segment,
                COUNT(DISTINCT c.customer_id) AS customers,
                COUNT(DISTINCT f.order_id) AS orders,
                ROUND(SUM(f.gross_amount), 2) AS revenue
            FROM {dataset}.fact_sales` AS f
            JOIN {dataset}.dim_customer` AS c USING (customer_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY c.customer_segment
            """,
        ),
        (
            "vw_campaign_performance",
            f"""
            CREATE OR REPLACE VIEW {dataset}.vw_campaign_performance` AS
            SELECT
                e.campaign_id,
                c.channel,
                COUNTIF(e.event_type = 'click') AS clicks,
                COUNTIF(e.event_type = 'conversion') AS conversions,
                ROUND(SUM(e.revenue), 2) AS attributed_revenue,
                ROUND(
                    100 * SAFE_DIVIDE(COUNTIF(e.event_type = 'conversion'), COUNT(*)),
                    2
                ) AS conversion_rate_percent
            FROM {dataset}.fact_campaign_events` AS e
            JOIN {dataset}.dim_channel` AS c USING (channel_key)
            GROUP BY e.campaign_id, c.channel
            """,
        ),
    ]


def _run_warehouse_statements(
    client: bigquery.Client,
    *,
    settings: Settings,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, sql in _warehouse_statements(
        settings.gcp_project_id,
        settings.bigquery_dataset,
    ):
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=settings.bigquery_maximum_bytes_billed,
            use_query_cache=True,
        )
        job = client.query(sql, job_config=config, location=settings.gcp_location)
        job.result()
        results.append(
            {
                "name": name,
                "bytes_processed": int(job.total_bytes_processed or 0),
                "cache_hit": bool(job.cache_hit),
            }
        )
    return results


def _verify_cloud_warehouse(
    client: bigquery.Client,
    *,
    settings: Settings,
) -> dict[str, Any]:
    dataset = f"`{settings.gcp_project_id}.{settings.bigquery_dataset}"
    sql = f"""
    SELECT
        (SELECT COUNT(*) FROM {dataset}.fact_sales`) AS fact_sales_rows,
        (SELECT COUNT(DISTINCT sales_key) FROM {dataset}.fact_sales`)
            AS distinct_sales_keys,
        (SELECT COUNT(*) FROM {dataset}.fact_campaign_events`) AS fact_campaign_rows,
        (SELECT ROUND(SUM(line_amount), 2) FROM {dataset}.silver_order_items`)
            AS silver_revenue,
        (SELECT ROUND(SUM(gross_amount), 2) FROM {dataset}.fact_sales`)
            AS warehouse_revenue
    """
    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=settings.bigquery_maximum_bytes_billed,
        use_query_cache=True,
    )
    job = client.query(sql, job_config=config, location=settings.gcp_location)
    row = next(iter(job.result()))
    metrics = {
        "fact_sales_rows": int(row["fact_sales_rows"]),
        "distinct_sales_keys": int(row["distinct_sales_keys"]),
        "fact_campaign_rows": int(row["fact_campaign_rows"]),
        "silver_revenue": float(row["silver_revenue"]),
        "warehouse_revenue": float(row["warehouse_revenue"]),
    }
    if metrics["fact_sales_rows"] != metrics["distinct_sales_keys"]:
        raise CloudPublishError("BigQuery fact_sales contains duplicate sales keys.")
    if abs(float(metrics["silver_revenue"]) - float(metrics["warehouse_revenue"])) > 0.01:
        raise CloudPublishError("BigQuery warehouse revenue does not reconcile to Silver.")
    metrics["bytes_processed"] = int(job.total_bytes_processed or 0)
    return metrics


def publish_cloud(settings: Settings, paths: DataPaths) -> dict[str, Any]:
    _validate_settings(settings)
    quality_run_id = _require_passed_quality_gate(paths)
    files = discover_silver_files(paths)

    storage_client = storage.Client(project=settings.gcp_project_id)
    bigquery_client = bigquery.Client(
        project=settings.gcp_project_id,
        location=settings.gcp_location,
    )

    bucket = _ensure_bucket(
        storage_client,
        bucket_name=settings.gcs_bucket,
        location=settings.gcp_location,
    )
    uploads = _upload_silver(bucket, files)
    dataset = _ensure_dataset(
        bigquery_client,
        project_id=settings.gcp_project_id,
        dataset_name=settings.bigquery_dataset,
        location=settings.gcp_location,
    )
    loaded = _load_silver_tables(
        bigquery_client,
        project_id=settings.gcp_project_id,
        dataset_name=settings.bigquery_dataset,
        location=settings.gcp_location,
        bucket_name=settings.gcs_bucket,
    )
    warehouse = _run_warehouse_statements(bigquery_client, settings=settings)
    verification = _verify_cloud_warehouse(bigquery_client, settings=settings)

    report = {
        "status": "passed",
        "published_at": datetime.now(UTC).isoformat(),
        "project_id": settings.gcp_project_id,
        "location": settings.gcp_location,
        "bucket": bucket.name,
        "bucket_lifecycle_days": 30,
        "dataset": dataset.full_dataset_id,
        "maximum_bytes_billed": settings.bigquery_maximum_bytes_billed,
        "quality_run_id": quality_run_id,
        "uploads": uploads,
        "loaded_tables": loaded,
        "warehouse_objects": warehouse,
        "verification": verification,
    }
    write_json(paths.state / "last_cloud_publish.json", report)
    return report


def cloud_status(settings: Settings) -> dict[str, Any]:
    _validate_settings(settings)
    storage_client = storage.Client(project=settings.gcp_project_id)
    bigquery_client = bigquery.Client(
        project=settings.gcp_project_id,
        location=settings.gcp_location,
    )
    bucket = storage_client.lookup_bucket(settings.gcs_bucket)
    dataset_id = f"{settings.gcp_project_id}.{settings.bigquery_dataset}"
    try:
        dataset = bigquery_client.get_dataset(dataset_id)
    except NotFound:
        dataset = None
    return {
        "project_id": settings.gcp_project_id,
        "bucket": {
            "exists": bucket is not None,
            "name": settings.gcs_bucket,
            "location": bucket.location if bucket else None,
        },
        "dataset": {
            "exists": dataset is not None,
            "id": dataset_id,
            "location": dataset.location if dataset else None,
        },
    }
