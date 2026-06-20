# Optional Cloud Publish

GCS, BigQuery, and Looker Studio are an optional extension. They are not needed
for the default demo or portfolio review and may incur cost.

## Safety Boundary

- `retailguard demo` has no cloud call.
- The Airflow DAG ends at DuckDB.
- CI runs lint, tests, and Compose validation without cloud credentials.
- `.env.example` leaves `GCP_PROJECT_ID` and `GCS_BUCKET` blank.
- `publish-cloud` is a separate, explicit CLI command.
- Publication requires a passing quality report for the last local warehouse run.

## Prerequisites

Only continue if you intentionally accept the provider's current pricing and
have a Google Cloud project, billing configuration, Application Default
Credentials, and a globally unique private bucket name.

Copy `.env.example` to `.env`, then set at least:

```dotenv
GCP_PROJECT_ID=your-project-id
GCS_BUCKET=your-unique-private-bucket
```

Never commit `.env`, service-account JSON, Application Default Credentials, or
downloaded credential files.

## Manual Publish

```powershell
gcloud auth application-default login
retailguard cloud-plan
retailguard publish-cloud
retailguard cloud-status
```

Review `cloud-plan` before running the mutating command. Existing controls cap
BigQuery bytes per query, keep the bucket private, expire uploaded objects after
30 days, and publish only protected Silver Parquet.

## Rollback and Shutdown

Stop using the cloud path by removing the optional cloud values from `.env` and
revoking local Application Default Credentials:

```powershell
gcloud auth application-default revoke
```

Resource deletion is destructive and must be an explicit operator decision.
Use the provider console or documented `gcloud` commands to remove the dataset,
bucket contents/bucket, budget, or project after preserving any evidence needed.
See [Cloud Cost Guardrails](cloud_cost_guardrails.md) for the historical controls.
