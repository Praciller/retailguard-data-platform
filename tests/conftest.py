from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from retailguard.config import Settings
from retailguard.paths import DataPaths
from retailguard.synthetic import generate_campaign_events, generate_retail_dataset


@pytest.fixture()
def silver_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths.from_settings(Settings(retailguard_data_root=tmp_path / "data"))
    dataset = generate_retail_dataset()

    customers = pd.DataFrame(dataset.customers)
    customers["email_hash"] = customers["email"].map(
        lambda value: hashlib.sha256(f"{value}:test-salt".encode()).hexdigest()
    )
    customers["phone_masked"] = customers["phone"].str[-4:].map(
        lambda value: f"***-***-{value}"
    )
    customers = customers.rename(columns={"city": "customer_city"})[
        [
            "customer_id",
            "email_hash",
            "phone_masked",
            "customer_city",
            "customer_segment",
            "created_at",
            "updated_at",
        ]
    ]

    products = pd.DataFrame(dataset.products)
    orders = pd.DataFrame(dataset.orders)
    order_items = pd.DataFrame(dataset.order_items)
    order_items["line_amount"] = order_items["quantity"] * order_items["unit_price"]
    payments = pd.DataFrame(dataset.payments)
    campaign_events = pd.DataFrame(generate_campaign_events())
    for column in ("event_timestamp", "updated_at"):
        campaign_events[column] = pd.to_datetime(campaign_events[column], utc=True)

    frames = {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
        "campaign_events": campaign_events,
    }
    for name, frame in frames.items():
        output = paths.silver / name
        output.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(
            output / "part-00000.parquet",
            index=False,
            coerce_timestamps="us",
            allow_truncated_timestamps=True,
        )

    return paths
