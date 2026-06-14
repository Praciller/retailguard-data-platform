from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from retailguard.config import Settings
from retailguard.synthetic import SyntheticDataset, generate_retail_dataset


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def wait_for_database(engine: Engine, *, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError:
            time.sleep(1)
    raise TimeoutError("PostgreSQL did not become ready before the timeout.")


def apply_schema(engine: Engine, schema_path: Path) -> None:
    statements = [
        statement.strip()
        for statement in schema_path.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _insert_rows(
    connection: Any,
    table_name: str,
    rows: Iterable[dict[str, Any]],
) -> None:
    payload = list(rows)
    if not payload:
        return
    columns = list(payload[0])
    column_sql = ", ".join(columns)
    value_sql = ", ".join(f":{column}" for column in columns)
    connection.execute(
        text(f"INSERT INTO {table_name} ({column_sql}) VALUES ({value_sql})"),
        payload,
    )


def seed_database(
    engine: Engine,
    dataset: SyntheticDataset | None = None,
    *,
    reset: bool = True,
) -> dict[str, int]:
    dataset = dataset or generate_retail_dataset()
    table_rows = {
        "customers": dataset.customers,
        "products": dataset.products,
        "orders": dataset.orders,
        "order_items": dataset.order_items,
        "payments": dataset.payments,
    }

    with engine.begin() as connection:
        if reset:
            connection.execute(
                text(
                    "TRUNCATE TABLE payments, order_items, orders, products, customers "
                    "RESTART IDENTITY CASCADE"
                )
            )
        for table_name, rows in table_rows.items():
            _insert_rows(connection, table_name, rows)

    return {table_name: len(rows) for table_name, rows in table_rows.items()}


def source_counts(engine: Engine) -> dict[str, int]:
    tables = ("customers", "products", "orders", "order_items", "payments")
    with engine.connect() as connection:
        return {
            table: int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            for table in tables
        }
