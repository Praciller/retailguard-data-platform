# Architecture

## Design Goals

1. Demonstrate the complete R2DE lifecycle locally without a cloud account,
   billing account, or free trial.
2. Stop data with broken keys, relationships, amounts, or privacy controls before it
   reaches a serving warehouse.
3. Keep every local run reproducible and any optional cloud operation explicit and
   removable.

## Data Flow

| Stage | Technology | Responsibility |
|---|---|---|
| Source | PostgreSQL 17 | Customers, products, orders, order items, and payments |
| Source | FastAPI | Campaign click and conversion events |
| Bronze | PyArrow Parquet | Incremental immutable extracts and watermarks |
| Silver | PySpark 4 | Deduplication, typing, normalization, and PII protection |
| Quality | DuckDB SQL | Blocking cross-table and privacy checks |
| Local warehouse | DuckDB | Dimensions, facts, reconciliation, and serving views |
| Orchestration | Airflow 3 | Daily task dependencies, retries, and observability |
| Local evidence | Markdown | KPIs, quality, privacy, reconciliation, idempotency, and row counts |
| Optional cloud lake | Cloud Storage | Manual protected Silver publication |
| Optional cloud warehouse/BI | BigQuery + Looker Studio | Archived extension path |

## Incremental Contract

Each PostgreSQL source is extracted with `(updated_at, primary_key)` ordering. The
watermark advances only after its Parquet batch is written. Campaign events use the
same contract through the API query parameters.

Silver is rebuilt from all Bronze snapshots. Source primary keys are deduplicated,
so replaying an extract is safe. Facts use stable business keys and are replaced as
one atomic warehouse build.

## Failure Boundary

The quality task is upstream of both warehouse loads. Any blocking failure raises an
error and prevents DuckDB or cloud publication. The tracked fixture deliberately
adds duplicate, orphaned, and invalid order-item data to prove this boundary.

## Optional Cloud Boundary

Airflow stops at the local DuckDB warehouse. `retailguard publish-cloud` is a manual
promotion command. This prevents retries or schedules from causing unexpected cloud
queries and keeps cost ownership explicit. Blank cloud destination values are the
documented default.
