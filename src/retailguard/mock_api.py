from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, Query

from retailguard.synthetic import generate_campaign_events

app = FastAPI(
    title="RetailGuard Synthetic Campaign API",
    version="0.1.0",
    description="Deterministic synthetic API used by the RetailGuard ingestion pipeline.",
)

CAMPAIGN_EVENTS = generate_campaign_events()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/campaign-events")
def campaign_events(
    updated_after: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    rows = CAMPAIGN_EVENTS
    if updated_after is not None:
        rows = [
            row
            for row in rows
            if datetime.fromisoformat(str(row["updated_at"])) > updated_after
        ]
    page = rows[offset : offset + limit]
    return {
        "items": page,
        "offset": offset,
        "limit": limit,
        "total": len(rows),
        "has_more": offset + limit < len(rows),
    }
