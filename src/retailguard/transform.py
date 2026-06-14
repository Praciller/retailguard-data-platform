from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from retailguard.config import Settings
from retailguard.paths import DataPaths
from retailguard.state import write_json
from retailguard.timeutils import UTC


def _ensure_java_home() -> None:
    if os.environ.get("JAVA_HOME"):
        return
    candidates = sorted(
        Path("C:/Program Files/Eclipse Adoptium").glob("jdk-17*"),
        reverse=True,
    )
    if candidates:
        os.environ["JAVA_HOME"] = str(candidates[0])
        os.environ["PATH"] = f"{candidates[0] / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"


def _spark_session() -> Any:
    _ensure_java_home()
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.master("local[2]")
        .appName("RetailGuard Bronze to Silver")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .getOrCreate()
    )


def _read_bronze(spark: Any, bronze_root: Path, source: str) -> Any:
    source_path = bronze_root / source
    if not list(source_path.rglob("*.parquet")):
        raise FileNotFoundError(f"No Bronze files found for {source}: {source_path}")
    return (
        spark.read.option("recursiveFileLookup", "true")
        .option("pathGlobFilter", "*.parquet")
        .parquet(str(source_path))
    )


def transform_bronze_to_silver(
    settings: Settings,
    paths: DataPaths,
    *,
    run_id: str,
) -> dict[str, Any]:
    from pyspark.sql import functions as F
    from pyspark.sql.types import DecimalType, IntegerType

    spark = _spark_session()
    spark.sparkContext.setLogLevel("WARN")
    decimal = DecimalType(12, 2)

    try:
        customers = (
            _read_bronze(spark, paths.bronze, "customers")
            .dropDuplicates(["customer_id"])
            .select(
                "customer_id",
                F.sha2(
                    F.concat_ws(":", F.col("email"), F.lit(settings.pii_hash_salt)),
                    256,
                ).alias("email_hash"),
                F.concat(F.lit("***-***-"), F.substring("phone", -4, 4)).alias(
                    "phone_masked"
                ),
                F.col("city").alias("customer_city"),
                "customer_segment",
                F.col("created_at").cast("timestamp").alias("created_at"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
        )

        products = (
            _read_bronze(spark, paths.bronze, "products")
            .dropDuplicates(["product_id"])
            .select(
                "product_id",
                "product_name",
                "category",
                F.col("unit_price").cast(decimal).alias("unit_price"),
                F.col("is_active").cast("boolean").alias("is_active"),
                F.col("created_at").cast("timestamp").alias("created_at"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
        )

        orders = (
            _read_bronze(spark, paths.bronze, "orders")
            .dropDuplicates(["order_id"])
            .select(
                "order_id",
                "customer_id",
                F.lower(F.trim("order_status")).alias("order_status"),
                F.col("order_timestamp").cast("timestamp").alias("order_timestamp"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
        )

        order_items = (
            _read_bronze(spark, paths.bronze, "order_items")
            .dropDuplicates(["order_item_id"])
            .select(
                "order_item_id",
                "order_id",
                "product_id",
                F.col("quantity").cast(IntegerType()).alias("quantity"),
                F.col("unit_price").cast(decimal).alias("unit_price"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
            .withColumn(
                "line_amount",
                (F.col("quantity") * F.col("unit_price")).cast(decimal),
            )
        )

        payments = (
            _read_bronze(spark, paths.bronze, "payments")
            .dropDuplicates(["payment_id"])
            .select(
                "payment_id",
                "order_id",
                F.lower(F.trim("payment_method")).alias("payment_method"),
                F.col("payment_amount").cast(decimal).alias("payment_amount"),
                F.col("payment_timestamp").cast("timestamp").alias("payment_timestamp"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
        )

        campaign_events = (
            _read_bronze(spark, paths.bronze, "campaign_events")
            .dropDuplicates(["event_id"])
            .select(
                "event_id",
                "campaign_id",
                F.lower(F.trim("channel")).alias("channel"),
                "customer_id",
                F.lower(F.trim("event_type")).alias("event_type"),
                F.col("revenue").cast(decimal).alias("revenue"),
                F.col("event_timestamp").cast("timestamp").alias("event_timestamp"),
                F.col("updated_at").cast("timestamp").alias("updated_at"),
            )
        )

        frames = {
            "customers": customers,
            "products": products,
            "orders": orders,
            "order_items": order_items,
            "payments": payments,
            "campaign_events": campaign_events,
        }
        counts: dict[str, int] = {}
        for name, frame in frames.items():
            counts[name] = frame.count()
            frame.write.mode("overwrite").parquet(str(paths.silver / name))

        report = {
            "run_id": run_id,
            "completed_at": datetime.now(UTC).isoformat(),
            "counts": counts,
            "pii_removed_from_silver": ["full_name", "email", "address"],
        }
        write_json(paths.state / "last_transform.json", report)
        return report
    finally:
        spark.stop()
