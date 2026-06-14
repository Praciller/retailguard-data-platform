# Cloud Cost Guardrails

## Active Guardrails

| Control | Value |
|---|---|
| Project | `retailguard-data-platform` |
| Region | `asia-southeast1` |
| Monthly budget | THB 90 |
| Budget basis | Gross cost before credits |
| Alerts | 25%, 50%, 75%, 90%, 100% |
| BigQuery per-query cap | 100 MiB billed |
| GCS lifecycle | Delete objects after 30 days |
| Cloud compute | None |

The project uses only Cloud Storage, BigQuery, and Looker Studio. PostgreSQL,
PySpark, DuckDB, and Airflow run locally.

## Important Limitation

Google Cloud budgets notify; they do not automatically stop usage. The no-charge
policy therefore depends on all of these controls:

1. Do not upgrade the Free Trial billing account.
2. Do not add Compute Engine, Cloud SQL, Dataflow, Dataproc, or Composer.
3. Keep cloud publication manual.
4. Delete the project before the Free Trial expires on September 13, 2026 if it is
   no longer needed.

## Spend Check

Review Billing > Reports with credits excluded and group by project. The current
project should remain far below the THB 90 alert because the uploaded dataset is
under 100 KiB and every query is capped at 100 MiB.

## Shutdown

The strongest shutdown is deleting the project:

```powershell
gcloud projects delete retailguard-data-platform
```

Project deletion is destructive and should be run only after the portfolio evidence,
dashboard screenshots, and any required exports are complete.
