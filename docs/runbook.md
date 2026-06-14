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

## Publish Cloud

```powershell
gcloud auth login
gcloud auth application-default login
gcloud config set project retailguard-data-platform
gcloud services enable bigquery.googleapis.com storage.googleapis.com

retailguard cloud-plan
retailguard publish-cloud
retailguard cloud-status
```

Never run cloud publication after a failed quality report.

## Verify BigQuery

```powershell
bq --location=asia-southeast1 query --use_legacy_sql=false --maximum_bytes_billed=104857600 `
  "SELECT * FROM \`retailguard-data-platform.retailguard.vw_executive_summary\`"
```

## Stop Local Services

```powershell
docker compose --profile airflow down
```

Use `docker compose down -v` only when local PostgreSQL and Airflow state should be
discarded.
