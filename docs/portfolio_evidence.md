# Portfolio Evidence

## Current Local Review Path

Run `retailguard demo`, then inspect
`data/evidence/local_portfolio_report.md`. This is the primary portfolio evidence
and requires no cloud account, billing account, or free trial.

The generated report records local executive metrics, every quality check,
privacy controls, Silver-to-DuckDB reconciliation, two-run idempotency, layer row
counts, and DuckDB schema objects. See [Portfolio Review](portfolio_review.md).

## Archived Cloud Status

Verified on 2026-06-17.

Live dashboard:
[RetailGuard Executive Dashboard](https://lookerstudio.google.com/reporting/8e913aa6-d7c0-4367-991d-c173c8f05abb/page/2pS1F)

The dashboard was verified in Looker Studio view mode with these visible
components:

| Component | Value |
|---|---:|
| Revenue | 1,575,759 |
| Orders | 479 |
| Units | 3,005 |
| Average order value | 3,289.68 |
| Daily revenue trend | 44 daily points |

## Archived BigQuery Evidence

All verification queries were run with:

```powershell
--maximum_bytes_billed=104857600
```

Executive KPI view:

```sql
SELECT revenue, orders, average_order_value, units
FROM `retailguard-data-platform.retailguard.vw_executive_summary`;
```

```json
[
  {
    "average_order_value": "3289.68",
    "orders": "479",
    "revenue": "1575759",
    "units": "3005"
  }
]
```

Daily dashboard trend coverage:

```sql
SELECT
  COUNT(*) AS daily_points,
  MIN(calendar_date) AS start_date,
  MAX(calendar_date) AS end_date,
  SUM(revenue) AS revenue,
  SUM(orders) AS orders,
  SUM(units) AS units
FROM `retailguard-data-platform.retailguard.vw_daily_sales`;
```

```json
[
  {
    "daily_points": "44",
    "end_date": "2026-06-13",
    "orders": "479",
    "revenue": "1575759",
    "start_date": "2026-05-01",
    "units": "3005"
  }
]
```

Serving objects:

```sql
SELECT 'fact_sales' AS object_name, COUNT(*) AS row_count
FROM `retailguard-data-platform.retailguard.fact_sales`
UNION ALL
SELECT 'fact_campaign_events', COUNT(*)
FROM `retailguard-data-platform.retailguard.fact_campaign_events`
UNION ALL
SELECT 'vw_product_performance', COUNT(*)
FROM `retailguard-data-platform.retailguard.vw_product_performance`
UNION ALL
SELECT 'vw_customer_segments', COUNT(*)
FROM `retailguard-data-platform.retailguard.vw_customer_segments`
UNION ALL
SELECT 'vw_campaign_performance', COUNT(*)
FROM `retailguard-data-platform.retailguard.vw_campaign_performance`
ORDER BY object_name;
```

```json
[
  {
    "object_name": "fact_campaign_events",
    "row_count": "300"
  },
  {
    "object_name": "fact_sales",
    "row_count": "1250"
  },
  {
    "object_name": "vw_campaign_performance",
    "row_count": "4"
  },
  {
    "object_name": "vw_customer_segments",
    "row_count": "4"
  },
  {
    "object_name": "vw_product_performance",
    "row_count": "50"
  }
]
```

## Recruiter-Facing Story

RetailGuard demonstrates a complete small-scale data engineering path:

1. Collect source data from PostgreSQL and a campaign API.
2. Write incremental Bronze Parquet with per-source watermarks.
3. Transform with PySpark into PII-protected Silver datasets.
4. Block bad loads with data quality checks and a failing acceptance fixture.
5. Load a reconciled DuckDB star schema and serving views.
6. Generate a local reviewer-facing evidence report.

Historical Cloud Storage, BigQuery, and Looker Studio evidence remains above as
an optional extension. It is not required to run or review the project.
