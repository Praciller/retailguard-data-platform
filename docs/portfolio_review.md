# Zero-Cost Portfolio Review

This review path runs entirely on the reviewer's machine. It needs no cloud
account, billing account, free trial, BigQuery, GCS, Looker Studio, Supabase,
Vercel, or other hosted service.

## Run

```powershell
docker compose up -d postgres mock-api
docker compose --profile tools build pipeline
docker compose --profile tools run --rm pipeline demo
Get-Content .\data\evidence\local_portfolio_report.md
```

The single `demo` command performs these checks in order:

1. resets local generated data and seeds deterministic PostgreSQL/API sources;
2. runs incremental Bronze extraction;
3. transforms protected Silver Parquet with PySpark;
4. runs the blocking quality gate;
5. loads the DuckDB star schema;
6. repeats the pipeline and verifies fact-key idempotency;
7. injects the invalid fixture and proves the warehouse load is blocked;
8. writes `data/evidence/local_portfolio_report.md`.

## Inspect

The generated report contains:

- revenue, order, unit, and average-order-value metrics;
- every quality check and failure count;
- the raw-PII absence check plus hashed/masked customer fields;
- Silver-to-DuckDB revenue reconciliation;
- first-run, second-run, and distinct fact-key counts;
- source and Silver row counts;
- DuckDB table/view names, types, and row counts;
- the failing-fixture result and confirmation that no warehouse load followed it.

Pass criteria:

| Evidence | Required result |
|---|---|
| Demo status | `passed` |
| Quality gate | all production-run checks passed |
| Privacy | `raw_pii_absent_from_silver` passed |
| Reconciliation | Silver revenue equals DuckDB revenue |
| Idempotency | first rows = second rows = distinct keys |
| Bad fixture | failed with `warehouse_load_attempted: false` |

## Optional Direct DuckDB Check

```powershell
@'
import duckdb
db = "data/warehouse/retailguard.duckdb"
con = duckdb.connect(db, read_only=True)
print(con.sql("SELECT * FROM vw_daily_sales ORDER BY calendar_date LIMIT 5"))
print(con.sql("SELECT COUNT(*) AS rows, COUNT(DISTINCT sales_key) AS keys FROM fact_sales"))
'@ | .\.venv\Scripts\python.exe -
```

Cloud publication is an optional extension only. See
[Optional Cloud Publish](cloud_optional.md).
