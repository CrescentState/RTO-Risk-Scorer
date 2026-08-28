"""
Full benchmark runner for RTO Risk Scorer.
Runs the complete pipeline on the held-out test set (100 test customers)
and computes all metrics using evaluation.metrics.
"""

import pandas as pd
from typing import List, Dict, Any

from core.orchestrator import run_pipeline
from synthetic_data.generator import load_customers, load_orders
from evaluation.metrics import compute_benchmark_metrics


def run_benchmark(
    customers_csv: str = "synthetic_data/customers.csv",
    orders_csv: str = "synthetic_data/orders.csv",
) -> Dict[str, Any]:
    """
    Run full benchmark on held-out test set.
    Returns complete benchmark report matching PRD output format.
    """
    # Load all data
    customers_df = pd.read_csv(customers_csv)
    orders_df = pd.read_csv(orders_csv)

    # Filter to test set only (100 test customers)
    test_customers = customers_df[customers_df["split"] == "test"]
    test_customer_ids = set(test_customers["customer_id"])

    # Get test orders for these customers
    test_orders = orders_df[
        (orders_df["customer_id"].isin(test_customer_ids)) &
        (orders_df["split"] == "test")
    ]

    # Build dataset for evaluation
    dataset: List[Dict[str, Any]] = []

    for _, order in test_orders.iterrows():
        result = run_pipeline(
            order_id=order["order_id"],
            customer_id=order["customer_id"],
            order_value=order["order_value"],
            category=order["category"],
            payment_method=order["payment_method"],
            delivery_pincode=order["delivery_pincode"],
        )

        dataset.append({
            "risk_score": result["risk_data"]["risk_score"],
            "actual_is_rto": order["ground_truth"] == "rto",
        })

    # Compute metrics using evaluation module
    metrics = compute_benchmark_metrics(dataset)

    # Add benchmark metadata
    metrics["benchmark_info"] = {
        "total_customers": len(test_customers),
        "total_test_orders": len(test_orders),
        "rto_rate_in_test": round(sum(1 for d in dataset if d["actual_is_rto"]) / len(dataset), 4),
    }

    return metrics


def run_benchmark_cli() -> None:
    """CLI entry point for running benchmark."""
    import json
    results = run_benchmark()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run_benchmark_cli()