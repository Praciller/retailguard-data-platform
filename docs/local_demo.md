# Local Demo

## Docker Path (Recommended)

Prerequisite: Docker Desktop is running.

```powershell
docker compose config --quiet
docker compose up -d postgres mock-api
docker compose --profile tools build pipeline
docker compose --profile tools run --rm pipeline demo
Get-Content .\data\evidence\local_portfolio_report.md
```

Expected final JSON fields:

```text
status: passed
idempotency.passed: true
bad_data_gate.status: failed
bad_data_gate.warehouse_load_attempted: false
local_evidence: /app/data/evidence/local_portfolio_report.md
```

The container path maps to
`.\data\evidence\local_portfolio_report.md` on Windows.

## Native Python Path

Prerequisites: Python 3.11, Java 17, and the local source services.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,spark]"
docker compose up -d postgres mock-api
retailguard demo
Get-Content .\data\evidence\local_portfolio_report.md
```

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp
docker compose config --quiet
```

`--basetemp=.pytest-tmp` avoids stale or inaccessible global Pytest temp
directories on Windows. The path is ignored by Git.

## Troubleshooting

| Symptom | Check |
|---|---|
| Docker daemon unavailable | Start Docker Desktop, then run `docker info` |
| PostgreSQL not healthy | Run `docker compose ps` and `docker compose logs postgres` |
| Mock API not healthy | Run `docker compose logs mock-api` |
| PySpark cannot find Java | Confirm `java -version` reports Java 17 |
| Port 5432 or 8000 in use | Override `POSTGRES_PORT` or stop the conflicting local process |
| Pytest temp permission error | Add `--basetemp=.pytest-tmp` |

Stop local services without deleting their named volumes:

```powershell
docker compose down
```
