"""
Full benchmark runner for RTO Risk Scorer.
Runs the complete pipeline on the held-out test set and computes all
metrics using evaluation.metrics. LLM narratives are always disabled
during benchmark computation.
"""

import asyncio
from typing import Any

import pandas as pd

from core.config import settings
from core.orchestrator import run_pipeline_async
from evaluation.metrics import compute_benchmark_metrics


async def run_benchmark_async(
    customers_csv: str | None = None,
    orders_csv: str | None = None,
) -> dict[str, Any]:
    """
    Run full benchmark on held-out test set.
    Returns complete benchmark report matching PRD output format.
    Raises ValueError when benchmark data is unavailable or invalid.
    """
    from synthetic_data.generator import generate_dataset

    customers_csv = customers_csv or settings.CUSTOMERS_CSV
    orders_csv = orders_csv or settings.ORDERS_CSV

    # Generate synthetic data if files don't exist
    import os

    if not os.path.exists(customers_csv) or not os.path.exists(orders_csv):
        generate_dataset(num_customers=500)

    # Load all data
    customers_df = pd.read_csv(customers_csv)
    orders_df = pd.read_csv(orders_csv)

    # Filter to test set only (held-out test customers)
    if "split" not in customers_df.columns or "split" not in orders_df.columns:
        raise ValueError("Benchmark data invalid: missing 'split' column")
    test_customers = customers_df[customers_df["split"] == "test"]
    test_customer_ids = set(test_customers["customer_id"])

    # Get test orders for these customers
    test_orders = orders_df[
        (orders_df["customer_id"].isin(test_customer_ids)) &
        (orders_df["split"] == "test")
    ]

    if len(test_orders) == 0:
        raise ValueError("Benchmark data unavailable: no held-out test orders")

    # Disable LLM narratives for benchmark speed and determinism
    original_llm_setting = settings.ENABLE_LLM_NARRATIVES
    settings.ENABLE_LLM_NARRATIVES = False
    try:
        dataset: list[dict[str, Any]] = []

        for _, order in test_orders.iterrows():
            result = await run_pipeline_async(
                order_id=order["order_id"],
                customer_id=order["customer_id"],
                order_value=float(order["order_value"]),
                category=order["category"],
                payment_method=order["payment_method"],
                delivery_pincode=str(order["delivery_pincode"]),
            )

            dataset.append({
                "risk_score": result["risk_data"]["risk_score"],
                "actual_is_rto": order["ground_truth"] == "rto",
            })
    finally:
        settings.ENABLE_LLM_NARRATIVES = original_llm_setting

    # Compute metrics using evaluation module
    metrics = compute_benchmark_metrics(dataset)

    # Add benchmark metadata
    metrics["benchmark_info"] = {
        "total_customers": len(test_customers),
        "total_test_orders": len(test_orders),
        "rto_rate_in_test": round(sum(1 for d in dataset if d["actual_is_rto"]) / len(dataset), 4),
    }

    return metrics


def run_benchmark(
    customers_csv: str | None = None,
    orders_csv: str | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for CLI usage. Fails clearly inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_benchmark_async(customers_csv, orders_csv))
    raise RuntimeError("run_benchmark() cannot be called from a running event loop; use await run_benchmark_async() instead")


def run_benchmark_cli() -> None:
    """CLI entry point for running benchmark."""
    import json
    results = run_benchmark()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run_benchmark_cli()
