from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from retailguard.paths import DataPaths
from retailguard.state import write_json
from retailguard.timeutils import UTC


class QualityGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class QualityCheck:
    name: str
    failures: int
    blocking: bool = True
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.failures == 0


def _parquet_glob(path: Path) -> str:
    return (path / "**" / "*.parquet").resolve().as_posix().replace("'", "''")


def _create_silver_views(
    connection: duckdb.DuckDBPyConnection,
    paths: DataPaths,
    *,
    bad_fixture: Path | None = None,
) -> None:
    for table in ("customers", "products", "orders", "payments", "campaign_events"):
        connection.execute(
            f"CREATE VIEW {table} AS "
            f"SELECT * FROM read_parquet('{_parquet_glob(paths.silver / table)}')"
        )

    order_items_source = (
        f"SELECT * FROM read_parquet('{_parquet_glob(paths.silver / 'order_items')}')"
    )
    if bad_fixture is not None:
        fixture = bad_fixture.resolve().as_posix().replace("'", "''")
        order_items_source += (
            " UNION ALL BY NAME "
            f"SELECT * FROM read_csv_auto('{fixture}', header = true)"
        )
    connection.execute(f"CREATE VIEW order_items AS {order_items_source}")


def _count(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def run_quality_gate(
    paths: DataPaths,
    *,
    run_id: str,
    bad_fixture: Path | None = None,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        _create_silver_views(connection, paths, bad_fixture=bad_fixture)
        checks = [
            QualityCheck(
                "required_keys_not_null",
                _count(
                    connection,
                    """
                    SELECT
                        (SELECT COUNT(*) FROM customers WHERE customer_id IS NULL) +
                        (SELECT COUNT(*) FROM products WHERE product_id IS NULL) +
                        (SELECT COUNT(*) FROM orders
                         WHERE order_id IS NULL OR customer_id IS NULL) +
                        (SELECT COUNT(*) FROM order_items
                         WHERE order_item_id IS NULL OR order_id IS NULL OR product_id IS NULL) +
                        (SELECT COUNT(*) FROM payments
                         WHERE payment_id IS NULL OR order_id IS NULL)
                    """,
                ),
            ),
            QualityCheck(
                "primary_keys_unique",
                _count(
                    connection,
                    """
                    SELECT
                        (SELECT COUNT(*) - COUNT(DISTINCT customer_id) FROM customers) +
                        (SELECT COUNT(*) - COUNT(DISTINCT product_id) FROM products) +
                        (SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM orders) +
                        (SELECT COUNT(*) - COUNT(DISTINCT order_item_id) FROM order_items) +
                        (SELECT COUNT(*) - COUNT(DISTINCT payment_id) FROM payments) +
                        (SELECT COUNT(*) - COUNT(DISTINCT event_id) FROM campaign_events)
                    """,
                ),
            ),
            QualityCheck(
                "valid_business_statuses",
                _count(
                    connection,
                    """
                    SELECT
                        (SELECT COUNT(*) FROM orders
                         WHERE order_status NOT IN
                         ('pending', 'paid', 'shipped', 'completed', 'cancelled')) +
                        (SELECT COUNT(*) FROM payments
                         WHERE payment_method NOT IN
                         ('card', 'promptpay', 'bank_transfer', 'wallet')) +
                        (SELECT COUNT(*) FROM campaign_events
                         WHERE event_type NOT IN ('click', 'conversion'))
                    """,
                ),
            ),
            QualityCheck(
                "positive_amounts",
                _count(
                    connection,
                    """
                    SELECT
                        (SELECT COUNT(*) FROM products WHERE unit_price <= 0) +
                        (SELECT COUNT(*) FROM order_items
                         WHERE quantity <= 0 OR unit_price <= 0 OR line_amount <= 0) +
                        (SELECT COUNT(*) FROM payments WHERE payment_amount <= 0) +
                        (SELECT COUNT(*) FROM campaign_events WHERE revenue < 0)
                    """,
                ),
            ),
            QualityCheck(
                "referential_integrity",
                _count(
                    connection,
                    """
                    SELECT
                        (SELECT COUNT(*) FROM orders o
                         LEFT JOIN customers c USING (customer_id)
                         WHERE c.customer_id IS NULL) +
                        (SELECT COUNT(*) FROM order_items i
                         LEFT JOIN orders o USING (order_id)
                         WHERE o.order_id IS NULL) +
                        (SELECT COUNT(*) FROM order_items i
                         LEFT JOIN products p USING (product_id)
                         WHERE p.product_id IS NULL) +
                        (SELECT COUNT(*) FROM payments p
                         LEFT JOIN orders o USING (order_id)
                         WHERE o.order_id IS NULL) +
                        (SELECT COUNT(*) FROM campaign_events e
                         LEFT JOIN customers c USING (customer_id)
                         WHERE c.customer_id IS NULL)
                    """,
                ),
            ),
            QualityCheck(
                "payment_reconciles_to_items",
                _count(
                    connection,
                    """
                    WITH item_totals AS (
                        SELECT order_id, ROUND(SUM(line_amount), 2) AS item_total
                        FROM order_items
                        GROUP BY order_id
                    )
                    SELECT COUNT(*)
                    FROM payments p
                    JOIN item_totals i USING (order_id)
                    WHERE ABS(p.payment_amount - i.item_total) > 0.01
                    """,
                ),
            ),
            QualityCheck(
                "minimum_expected_volume",
                int(
                    _count(connection, "SELECT COUNT(*) < 100 FROM customers")
                    + _count(connection, "SELECT COUNT(*) < 50 FROM products")
                    + _count(connection, "SELECT COUNT(*) < 500 FROM orders")
                ),
            ),
        ]

        customer_columns = {
            str(row[0]).lower() for row in connection.execute("DESCRIBE customers").fetchall()
        }
        forbidden_pii = {"full_name", "email", "phone", "address"}
        checks.append(
            QualityCheck(
                "raw_pii_absent_from_silver",
                len(customer_columns & forbidden_pii),
                detail=f"Forbidden columns found: {sorted(customer_columns & forbidden_pii)}",
            )
        )

        failed = [check for check in checks if check.blocking and not check.passed]
        report = {
            "run_id": run_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "status": "failed" if failed else "passed",
            "fixture": str(bad_fixture) if bad_fixture else None,
            "checks": [{**asdict(check), "passed": check.passed} for check in checks],
            "blocking_failures": len(failed),
        }
        report_path = paths.quality / f"{run_id}.json"
        write_json(report_path, report)
        write_json(paths.quality / "latest.json", report)

        if failed and raise_on_failure:
            names = ", ".join(check.name for check in failed)
            raise QualityGateError(f"Quality gate failed: {names}. Report: {report_path}")
        return report
    finally:
        connection.close()
