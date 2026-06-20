from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from retailguard.paths import DataPaths
from retailguard.state import write_json
from retailguard.timeutils import UTC


def _glob(path: Path) -> str:
    return (path / "**" / "*.parquet").resolve().as_posix().replace("'", "''")


def _create_source_views(connection: duckdb.DuckDBPyConnection, paths: DataPaths) -> None:
    for table in (
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "campaign_events",
    ):
        connection.execute(
            f"CREATE OR REPLACE VIEW silver_{table} AS "
            f"SELECT * FROM read_parquet('{_glob(paths.silver / table)}')"
        )


def load_duckdb_warehouse(
    paths: DataPaths,
    *,
    run_id: str,
) -> dict[str, Any]:
    database_path = paths.warehouse / "retailguard.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        _create_source_views(connection, paths)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id VARCHAR PRIMARY KEY,
                loaded_at TIMESTAMPTZ NOT NULL,
                fact_sales_rows BIGINT NOT NULL,
                fact_campaign_rows BIGINT NOT NULL,
                status VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE dim_customer AS
            SELECT
                CAST(hash(customer_id) AS UBIGINT) AS customer_key,
                customer_id,
                email_hash,
                phone_masked,
                customer_city,
                customer_segment,
                created_at,
                updated_at
            FROM silver_customers
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE dim_product AS
            SELECT
                CAST(hash(product_id) AS UBIGINT) AS product_key,
                product_id,
                product_name,
                category,
                unit_price AS current_unit_price,
                is_active,
                created_at,
                updated_at
            FROM silver_products
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE dim_date AS
            WITH dates AS (
                SELECT CAST(order_timestamp AS DATE) AS calendar_date
                FROM silver_orders
                UNION
                SELECT CAST(event_timestamp AS DATE) AS calendar_date
                FROM silver_campaign_events
            )
            SELECT
                CAST(strftime(calendar_date, '%Y%m%d') AS INTEGER) AS date_key,
                calendar_date,
                year(calendar_date) AS year,
                quarter(calendar_date) AS quarter,
                month(calendar_date) AS month,
                monthname(calendar_date) AS month_name,
                day(calendar_date) AS day,
                dayofweek(calendar_date) AS day_of_week,
                dayname(calendar_date) AS day_name,
                CASE WHEN dayofweek(calendar_date) IN (0, 6) THEN TRUE ELSE FALSE END
                    AS is_weekend
            FROM dates
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE dim_channel AS
            SELECT
                CAST(hash(channel) AS UBIGINT) AS channel_key,
                channel
            FROM silver_campaign_events
            GROUP BY channel
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE fact_sales AS
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
            FROM silver_order_items i
            JOIN silver_orders o USING (order_id)
            JOIN silver_payments p USING (order_id)
            JOIN dim_customer dc USING (customer_id)
            JOIN dim_product dp USING (product_id)
            JOIN dim_date dd ON dd.calendar_date = CAST(o.order_timestamp AS DATE)
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE fact_campaign_events AS
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
            FROM silver_campaign_events e
            JOIN dim_customer dc USING (customer_id)
            JOIN dim_channel dch USING (channel)
            JOIN dim_date dd ON dd.calendar_date = CAST(e.event_timestamp AS DATE)
            """
        )

        connection.execute(
            """
            CREATE OR REPLACE VIEW vw_daily_sales AS
            SELECT
                d.calendar_date,
                ROUND(SUM(f.gross_amount), 2) AS revenue,
                COUNT(DISTINCT f.order_id) AS orders,
                ROUND(SUM(f.gross_amount) / COUNT(DISTINCT f.order_id), 2)
                    AS average_order_value,
                SUM(f.quantity) AS units
            FROM fact_sales f
            JOIN dim_date d USING (date_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY d.calendar_date
            ORDER BY d.calendar_date
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW vw_product_performance AS
            SELECT
                p.category,
                p.product_name,
                ROUND(SUM(f.gross_amount), 2) AS revenue,
                SUM(f.quantity) AS units,
                COUNT(DISTINCT f.order_id) AS orders
            FROM fact_sales f
            JOIN dim_product p USING (product_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY p.category, p.product_name
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW vw_customer_segments AS
            SELECT
                c.customer_segment,
                COUNT(DISTINCT c.customer_id) AS customers,
                COUNT(DISTINCT f.order_id) AS orders,
                ROUND(SUM(f.gross_amount), 2) AS revenue
            FROM fact_sales f
            JOIN dim_customer c USING (customer_key)
            WHERE f.order_status <> 'cancelled'
            GROUP BY c.customer_segment
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW vw_campaign_performance AS
            SELECT
                e.campaign_id,
                c.channel,
                COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks,
                COUNT(*) FILTER (WHERE e.event_type = 'conversion') AS conversions,
                ROUND(SUM(e.revenue), 2) AS attributed_revenue,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE e.event_type = 'conversion')
                    / NULLIF(COUNT(*), 0),
                    2
                ) AS conversion_rate_percent
            FROM fact_campaign_events e
            JOIN dim_channel c USING (channel_key)
            GROUP BY e.campaign_id, c.channel
            """
        )

        fact_sales_rows = int(
            connection.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
        )
        fact_campaign_rows = int(
            connection.execute("SELECT COUNT(*) FROM fact_campaign_events").fetchone()[0]
        )
        distinct_sales = int(
            connection.execute("SELECT COUNT(DISTINCT sales_key) FROM fact_sales").fetchone()[0]
        )
        silver_total = float(
            connection.execute(
                "SELECT ROUND(SUM(line_amount), 2) FROM silver_order_items"
            ).fetchone()[0]
        )
        warehouse_total = float(
            connection.execute(
                "SELECT ROUND(SUM(gross_amount), 2) FROM fact_sales"
            ).fetchone()[0]
        )

        if fact_sales_rows != distinct_sales:
            raise RuntimeError("Warehouse load created duplicate fact_sales rows.")
        if abs(silver_total - warehouse_total) > 0.01:
            raise RuntimeError("Warehouse revenue does not reconcile to Silver.")

        connection.execute(
            """
            INSERT OR REPLACE INTO pipeline_runs
            VALUES (?, ?, ?, ?, 'success')
            """,
            [run_id, datetime.now(UTC), fact_sales_rows, fact_campaign_rows],
        )
        report = {
            "run_id": run_id,
            "loaded_at": datetime.now(UTC).isoformat(),
            "database": str(database_path),
            "fact_sales_rows": fact_sales_rows,
            "distinct_sales_keys": distinct_sales,
            "fact_campaign_rows": fact_campaign_rows,
            "silver_revenue": silver_total,
            "warehouse_revenue": warehouse_total,
        }
        write_json(paths.state / "last_warehouse_load.json", report)
        return report
    finally:
        connection.close()


def warehouse_metrics(paths: DataPaths) -> dict[str, Any]:
    database_path = paths.warehouse / "retailguard.duckdb"
    if not database_path.exists():
        return {"exists": False}
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        return {
            "exists": True,
            "fact_sales_rows": int(
                connection.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
            ),
            "distinct_sales_keys": int(
                connection.execute(
                    "SELECT COUNT(DISTINCT sales_key) FROM fact_sales"
                ).fetchone()[0]
            ),
            "fact_campaign_rows": int(
                connection.execute("SELECT COUNT(*) FROM fact_campaign_events").fetchone()[0]
            ),
            "pipeline_runs": int(
                connection.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            ),
        }
    finally:
        connection.close()


def write_local_evidence_report(paths: DataPaths, demo: dict[str, Any]) -> Path:
    """Write reviewer-facing evidence from a completed local demo."""
    database_path = paths.warehouse / "retailguard.duckdb"
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        revenue, orders, units = connection.execute(
            "SELECT ROUND(SUM(revenue), 2), SUM(orders), SUM(units) FROM vw_daily_sales"
        ).fetchone()
        objects = connection.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_type, table_name
            """
        ).fetchall()
        object_rows = [
            (name, kind, int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]))
            for name, kind in objects
        ]
        customer_columns = {
            row[0].lower() for row in connection.execute("DESCRIBE dim_customer").fetchall()
        }
    finally:
        connection.close()

    first_run = demo["first_run"]
    source_rows = {source["source"]: source["rows"] for source in first_run["extract"]["sources"]}
    quality = first_run.get("quality") or demo["quality"]
    warehouse = first_run.get("warehouse") or demo["warehouse"]
    idempotency = demo["idempotency"]
    bad_gate = demo["bad_data_gate"]
    protected_columns = ", ".join(sorted(customer_columns & {"email_hash", "phone_masked"}))
    warehouse_attempted = "yes" if bad_gate["warehouse_load_attempted"] else "no"
    output = paths.root / "evidence" / "local_portfolio_report.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# RetailGuard Local Portfolio Evidence",
        "",
        "Generated by `retailguard demo`. No cloud account, billing account, "
        "or free trial was used.",
        "",
        "## Executive Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Revenue | {float(revenue):,.2f} |",
        f"| Orders | {int(orders):,} |",
        f"| Units | {int(units):,} |",
        f"| Average order value | {float(revenue) / int(orders):,.2f} |",
        "",
        "## Quality and Privacy",
        "",
        "| Check | Status | Failures |",
        "|---|---|---:|",
        *[
            f"| {check['name']} | {'passed' if check['passed'] else 'failed'} | "
            f"{check['failures']} |"
            for check in quality["checks"]
        ],
        "",
        "Silver removes raw `full_name`, `email`, `phone`, and `address`. "
        f"DuckDB retains protected columns: {protected_columns}.",
        "",
        "## Reconciliation and Idempotency",
        "",
        "| Evidence | Value |",
        "|---|---:|",
        f"| Silver revenue | {warehouse['silver_revenue']:,.2f} |",
        f"| DuckDB revenue | {warehouse['warehouse_revenue']:,.2f} |",
        f"| First-run sales rows | {idempotency['first_fact_rows']:,} |",
        f"| Second-run sales rows | {idempotency['second_fact_rows']:,} |",
        f"| Distinct sales keys | {idempotency['distinct_sales_keys']:,} |",
        f"| Passed | {'yes' if idempotency['passed'] else 'no'} |",
        f"| Bad fixture blocked | {'yes' if bad_gate['status'] == 'failed' else 'no'} |",
        f"| Bad fixture blocking failures | {bad_gate['blocking_failures']} |",
        f"| Warehouse attempted after bad fixture | {warehouse_attempted} |",
        "",
        "## Layer Row Counts",
        "",
        "| Dataset | Source / Bronze | Silver |",
        "|---|---:|---:|",
        *[
            f"| {name} | {count:,} | {first_run['transform']['counts'].get(name, 0):,} |"
            for name, count in source_rows.items()
        ],
        "",
        "## DuckDB Objects",
        "",
        "| Object | Type | Rows |",
        "|---|---|---:|",
        *[f"| {name} | {kind} | {count:,} |" for name, kind, count in object_rows],
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
