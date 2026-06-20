# Operations Runbook

## Start Local Services

```powershell
docker compose up -d postgres mock-api
docker compose ps
```

## Run Acceptance Demo

```powershell
docker compose --profile tools build pipeline
docker compose --profile tools run --rm pipeline demo
Get-Content .\data\evidence\local_portfolio_report.md
```

Pass criteria:

- all six source counts match their deterministic contract;
- the quality status is `passed`;
- `fact_sales_rows` equals `distinct_sales_keys`;
- Silver and warehouse revenue match;
- second-run fact count is unchanged;
- bad fixture status is `failed`;
- no warehouse load is attempted for the bad fixture.

## Run Airflow

```powershell
docker compose --profile airflow up -d airflow
docker compose --profile airflow exec airflow airflow dags list-import-errors
docker compose --profile airflow exec airflow airflow dags test retailguard_pipeline 2026-06-14
```

## Optional Cloud Publish

Cloud publication is not required for operations or portfolio review. Follow
[Optional Cloud Publish](cloud_optional.md) only when intentionally exercising
that extension. Never publish after a failed quality report.

## Stop Local Services

```powershell
docker compose --profile airflow down
```

Use `docker compose down -v` only when local PostgreSQL and Airflow state should be
discarded.
