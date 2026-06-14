from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine

from retailguard.config import Settings
from retailguard.paths import DataPaths
from retailguard.state import read_json, write_json
from retailguard.timeutils import UTC

SOURCE_TABLES = ("customers", "products", "orders", "order_items", "payments")
EPOCH_WATERMARK = "1970-01-01T00:00:00+00:00"


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if column.endswith("_at") or column.endswith("_timestamp"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def _write_bronze(
    frame: pd.DataFrame,
    *,
    source_name: str,
    paths: DataPaths,
    run_id: str,
) -> Path | None:
    if frame.empty:
        return None
    partition = (
        paths.bronze
        / source_name
        / f"ingested_date={datetime.now(UTC).date().isoformat()}"
        / f"run_id={run_id}"
    )
    partition.mkdir(parents=True, exist_ok=True)
    output = partition / "part-00000.parquet"
    frame.to_parquet(
        output,
        index=False,
        coerce_timestamps="us",
        allow_truncated_timestamps=True,
    )
    return output


def extract_postgres_table(
    engine: Engine,
    table_name: str,
    *,
    paths: DataPaths,
    run_id: str,
) -> dict[str, Any]:
    if table_name not in SOURCE_TABLES:
        raise ValueError(f"Unsupported source table: {table_name}")

    watermark_path = paths.state / "watermarks.json"
    watermarks = read_json(watermark_path)
    watermark = str(watermarks.get(table_name, EPOCH_WATERMARK))
    query = text(
        f"SELECT * FROM {table_name} "
        "WHERE updated_at > :updated_after "
        "ORDER BY updated_at"
    )
    with engine.connect() as connection:
        result = connection.execute(query, {"updated_after": watermark})
        frame = pd.DataFrame(result.fetchall(), columns=result.keys())
    frame = _normalise_frame(frame)
    output = _write_bronze(frame, source_name=table_name, paths=paths, run_id=run_id)

    next_watermark = watermark
    if not frame.empty:
        next_watermark = pd.Timestamp(frame["updated_at"].max()).isoformat()
        watermarks[table_name] = next_watermark
        write_json(watermark_path, watermarks)

    return {
        "source": table_name,
        "rows": int(len(frame)),
        "watermark_before": watermark,
        "watermark_after": next_watermark,
        "output": str(output) if output else None,
    }


def extract_campaign_events(
    settings: Settings,
    *,
    paths: DataPaths,
    run_id: str,
    page_size: int = 100,
) -> dict[str, Any]:
    source_name = "campaign_events"
    watermark_path = paths.state / "watermarks.json"
    watermarks = read_json(watermark_path)
    watermark = str(watermarks.get(source_name, EPOCH_WATERMARK))
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        response = requests.get(
            f"{settings.mock_api_url.rstrip('/')}/campaign-events",
            params={
                "updated_after": watermark,
                "offset": offset,
                "limit": page_size,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload["items"]
        rows.extend(items)
        if not payload["has_more"]:
            break
        offset += page_size

    frame = _normalise_frame(pd.DataFrame(rows))
    output = _write_bronze(frame, source_name=source_name, paths=paths, run_id=run_id)
    next_watermark = watermark
    if not frame.empty:
        next_watermark = pd.Timestamp(frame["updated_at"].max()).isoformat()
        watermarks[source_name] = next_watermark
        write_json(watermark_path, watermarks)

    return {
        "source": source_name,
        "rows": int(len(frame)),
        "watermark_before": watermark,
        "watermark_after": next_watermark,
        "output": str(output) if output else None,
    }


def extract_all(
    engine: Engine,
    settings: Settings,
    paths: DataPaths,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or new_run_id()
    results = [
        extract_postgres_table(engine, table_name, paths=paths, run_id=run_id)
        for table_name in SOURCE_TABLES
    ]
    results.append(extract_campaign_events(settings, paths=paths, run_id=run_id))
    manifest = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "sources": results,
        "total_rows": sum(item["rows"] for item in results),
    }
    write_json(paths.state / "last_extract.json", manifest)
    return manifest


def reset_ingestion_state(paths: DataPaths) -> None:
    for path in (paths.state / "watermarks.json", paths.state / "last_extract.json"):
        path.unlink(missing_ok=True)
