from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from retailguard.timeutils import UTC

BASE_TIMESTAMP = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
ORDER_STATUSES = ("pending", "paid", "shipped", "completed", "cancelled")
PAYMENT_METHODS = ("card", "promptpay", "bank_transfer", "wallet")
CHANNELS = ("email", "social", "search", "affiliate")


@dataclass(frozen=True)
class SyntheticDataset:
    customers: list[dict[str, Any]]
    products: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    order_items: list[dict[str, Any]]
    payments: list[dict[str, Any]]


def generate_retail_dataset(
    *,
    seed: int = 2026,
    customer_count: int = 100,
    product_count: int = 50,
    order_count: int = 500,
) -> SyntheticDataset:
    rng = random.Random(seed)
    first_names = (
        "Anan",
        "Araya",
        "Chai",
        "Dao",
        "Kanya",
        "Krit",
        "Mali",
        "Narin",
        "Nok",
        "Pim",
    )
    last_names = (
        "Sukjai",
        "Deechai",
        "Poomdee",
        "Saelim",
        "Wongsa",
        "Kaew",
        "Meechai",
        "Thong",
        "Boonmee",
        "Raksri",
    )
    cities = ("Bangkok", "Chiang Mai", "Khon Kaen", "Phuket", "Chonburi")
    segments = ("new", "regular", "loyal", "vip")
    categories = ("Electronics", "Home", "Beauty", "Sports", "Books")

    customers: list[dict[str, Any]] = []
    for number in range(1, customer_count + 1):
        created_at = BASE_TIMESTAMP + timedelta(hours=number)
        customers.append(
            {
                "customer_id": f"CUST{number:04d}",
                "full_name": f"{first_names[(number - 1) % len(first_names)]} "
                f"{last_names[((number - 1) // len(first_names)) % len(last_names)]}",
                "email": f"customer{number:04d}@example.com",
                "phone": f"+66-02-555-{number:04d}",
                "address": f"{100 + number} Demo Road, Synthetic District",
                "city": cities[(number - 1) % len(cities)],
                "customer_segment": segments[(number - 1) % len(segments)],
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    products: list[dict[str, Any]] = []
    for number in range(1, product_count + 1):
        category = categories[(number - 1) % len(categories)]
        created_at = BASE_TIMESTAMP + timedelta(minutes=number)
        products.append(
            {
                "product_id": f"PROD{number:04d}",
                "product_name": f"{category} Product {number:02d}",
                "category": category,
                "unit_price": Decimal(str(99 + number * 17)).quantize(Decimal("0.01")),
                "is_active": number % 13 != 0,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    orders: list[dict[str, Any]] = []
    order_items: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    item_number = 1

    status_population = ("pending", "paid", "shipped", "completed", "cancelled")
    status_weights = (5, 20, 25, 45, 5)

    for number in range(1, order_count + 1):
        order_timestamp = BASE_TIMESTAMP + timedelta(
            days=rng.randint(0, 42),
            minutes=rng.randint(0, 1_439),
        )
        order_id = f"ORD{number:06d}"
        customer_id = f"CUST{rng.randint(1, customer_count):04d}"
        order_status = rng.choices(status_population, weights=status_weights, k=1)[0]
        updated_at = order_timestamp + timedelta(hours=rng.randint(1, 24))
        orders.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "order_status": order_status,
                "order_timestamp": order_timestamp,
                "updated_at": updated_at,
            }
        )

        order_total = Decimal("0")
        product_numbers = rng.sample(range(1, product_count + 1), rng.randint(1, 4))
        for product_number in product_numbers:
            product = products[product_number - 1]
            quantity = rng.randint(1, 4)
            unit_price = product["unit_price"]
            order_total += unit_price * quantity
            order_items.append(
                {
                    "order_item_id": f"ITEM{item_number:07d}",
                    "order_id": order_id,
                    "product_id": product["product_id"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "updated_at": updated_at,
                }
            )
            item_number += 1

        payments.append(
            {
                "payment_id": f"PAY{number:06d}",
                "order_id": order_id,
                "payment_method": rng.choice(PAYMENT_METHODS),
                "payment_amount": order_total.quantize(Decimal("0.01")),
                "payment_timestamp": order_timestamp + timedelta(minutes=rng.randint(1, 90)),
                "updated_at": updated_at,
            }
        )

    return SyntheticDataset(
        customers=customers,
        products=products,
        orders=orders,
        order_items=order_items,
        payments=payments,
    )


def generate_campaign_events(*, seed: int = 2026, count: int = 300) -> list[dict[str, Any]]:
    rng = random.Random(seed + 91)
    campaigns = ("summer-launch", "loyalty-week", "new-arrivals", "weekend-sale")
    events: list[dict[str, Any]] = []

    for number in range(1, count + 1):
        event_timestamp = BASE_TIMESTAMP + timedelta(
            days=rng.randint(0, 42),
            minutes=rng.randint(0, 1_439),
        )
        event_type = "conversion" if number % 4 == 0 else "click"
        events.append(
            {
                "event_id": f"EVT{number:06d}",
                "campaign_id": campaigns[(number - 1) % len(campaigns)],
                "channel": CHANNELS[(number - 1) % len(CHANNELS)],
                "customer_id": f"CUST{rng.randint(1, 100):04d}",
                "event_type": event_type,
                "revenue": round(rng.uniform(199, 4_999), 2) if event_type == "conversion" else 0.0,
                "event_timestamp": event_timestamp.isoformat(),
                "updated_at": (event_timestamp + timedelta(minutes=5)).isoformat(),
            }
        )

    return sorted(events, key=lambda row: (row["updated_at"], row["event_id"]))
