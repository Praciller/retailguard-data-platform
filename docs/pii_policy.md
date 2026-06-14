# PII Policy

## Scope

All records are synthetic. The pipeline still applies controls expected for a real
retail workload so the project demonstrates privacy-aware engineering.

## Bronze

Bronze is a restricted local landing zone and can contain source-shaped fields.
Bronze is excluded from Git and is never uploaded to Google Cloud.

## Silver

The customer transformation applies these controls:

| Source field | Silver treatment |
|---|---|
| `full_name` | Removed |
| `email` | Replaced with salted SHA-256 `email_hash` |
| `phone` | Replaced with last-four-only `phone_masked` |
| `address` | Removed |
| `city` | Retained as `customer_city` |

The blocking quality gate inspects the Silver schema and fails when `full_name`,
`email`, `phone`, or `address` is present.

## Cloud

Only Silver Parquet is uploaded. The bucket enforces uniform bucket-level access and
public access prevention. Objects expire after 30 days. No service-account keys or
credentials are stored in the repository.

## Salt

`PII_HASH_SALT` is configurable. The default exists only for synthetic demonstration
data. A real deployment must supply a secret-managed random value and rotate it
under an approved reprocessing plan.
