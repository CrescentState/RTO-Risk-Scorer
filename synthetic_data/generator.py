"""
Synthetic data generator for RTO Risk Scorer.
Creates realistic customer profiles, order history, and external signals
with ground truth labels for evaluation.
"""

import csv
import random
import uuid
from pathlib import Path
from typing import Literal

# ── Configuration ──
SEED = 42
random.seed(SEED)

CATEGORIES = ["fashion", "electronics", "home", "beauty"]
CATEGORY_WEIGHTS = [0.40, 0.30, 0.20, 0.10]

PAYMENT_METHODS = ["cod", "upi", "card", "wallet"]
PAYMENT_WEIGHTS = [0.60, 0.20, 0.15, 0.05]

PINCODES = [
    ("110001", 0.15),   # Delhi - low RTO
    ("110002", 0.22),
    ("400001", 0.18),   # Mumbai - low RTO
    ("400002", 0.25),
    ("560001", 0.35),   # Bangalore - medium RTO
    ("560002", 0.28),
    ("600001", 0.42),   # Chennai - high RTO
    ("600002", 0.38),
    ("700001", 0.45),   # Kolkata - high RTO
    ("700002", 0.50),   # Kolkata - very high RTO
    ("500001", 0.30),   # Hyderabad - medium
    ("500002", 0.33),
    ("380001", 0.25),   # Ahmedabad - low-medium
    ("380002", 0.28),
    ("302001", 0.32),   # Jaipur - medium
    ("302002", 0.35),
    ("226001", 0.40),   # Lucknow - high
    ("226002", 0.44),
    ("160001", 0.20),   # Chandigarh - low
    ("160002", 0.23),
]

CATEGORY_RTO_RATES = {
    "fashion": 0.35,
    "electronics": 0.18,
    "home": 0.22,
    "beauty": 0.28,
}

CustomerType = Literal["good", "occasional_returner", "serial_returner", "fraudster"]


def _generate_customer_id() -> str:
    """Generate a random customer ID."""
    return f"CUST_{random.randint(10000, 99999)}"


def _generate_order_id() -> str:
    """Generate a random order ID."""
    return f"ORD_{random.randint(100000, 999999)}"


def _generate_customer_type() -> CustomerType:
    """Weighted random customer type."""
    return random.choices(
        ["good", "occasional_returner", "serial_returner", "fraudster"],
        weights=[0.60, 0.25, 0.10, 0.05],
    )[0]


def _generate_customer_profile(customer_type: CustomerType) -> dict:
    """Generate a customer profile based on type."""
    if customer_type == "good":
        total_orders = random.randint(5, 50)
        returns = random.randint(0, max(1, total_orders // 10))
        account_age_days = random.randint(60, 365)
        complaint_score = random.uniform(0.0, 0.3)
        social_sentiment = random.uniform(0.0, 0.5)

    elif customer_type == "occasional_returner":
        total_orders = random.randint(3, 30)
        returns = random.randint(1, max(2, total_orders // 5))
        account_age_days = random.randint(30, 180)
        complaint_score = random.uniform(0.1, 0.4)
        social_sentiment = random.uniform(-0.2, 0.3)

    elif customer_type == "serial_returner":
        total_orders = random.randint(10, 40)
        returns = random.randint(total_orders // 2, total_orders - 1)
        account_age_days = random.randint(14, 120)
        complaint_score = random.uniform(0.3, 0.7)
        social_sentiment = random.uniform(-0.5, 0.1)

    else:  # fraudster
        total_orders = random.randint(1, 15)
        returns = random.randint(max(1, total_orders // 2), total_orders)
        account_age_days = random.randint(1, 14)
        complaint_score = random.uniform(0.5, 1.0)
        social_sentiment = random.uniform(-1.0, -0.3)

    return_rate = returns / total_orders if total_orders > 0 else 0.0
    avg_order_value = random.randint(500, 15000)

    return {
        "customer_id": _generate_customer_id(),
        "customer_type": customer_type,
        "total_orders": total_orders,
        "returns": returns,
        "return_rate": round(return_rate, 4),
        "avg_order_value": avg_order_value,
        "account_age_days": account_age_days,
        "complaint_score": round(complaint_score, 4),
        "social_sentiment": round(social_sentiment, 4),
    }


def _generate_order(customer: dict) -> dict:
    """Generate a single order for a customer."""
    category = random.choices(CATEGORIES, weights=CATEGORY_WEIGHTS)[0]
    payment_method = random.choices(PAYMENT_METHODS, weights=PAYMENT_WEIGHTS)[0]
    pincode, pincode_rto_rate = random.choice(PINCODES)

    # Order value varies around customer's average
    order_value = int(random.gauss(customer["avg_order_value"], customer["avg_order_value"] * 0.3))
    order_value = max(500, min(25000, order_value))

    # Recent returns in last 30 days (subset of total returns)
    recent_returns_30d = min(
        customer["returns"],
        random.randint(0, max(0, customer["returns"] - random.randint(0, 3)))
    )

    # Determine if this order will RTO (ground truth)
    # Higher probability for: fraudsters, serial returners, COD, high RTO pincode
    rto_probability = 0.05  # Base rate

    if customer["customer_type"] == "fraudster":
        rto_probability += 0.70
    elif customer["customer_type"] == "serial_returner":
        rto_probability += 0.50
    elif customer["customer_type"] == "occasional_returner":
        rto_probability += 0.20

    if payment_method == "cod":
        rto_probability += 0.15
    if pincode_rto_rate > 0.35:
        rto_probability += 0.10
    if customer["return_rate"] > 0.5:
        rto_probability += 0.15
    if order_value > 10000:
        rto_probability += 0.05

    rto_probability = min(0.95, rto_probability)
    will_rto = random.random() < rto_probability

    return {
        "order_id": _generate_order_id(),
        "customer_id": customer["customer_id"],
        "order_value": order_value,
        "category": category,
        "payment_method": payment_method,
        "delivery_pincode": pincode,
        "pincode_rto_rate": pincode_rto_rate,
        "recent_returns_30d": recent_returns_30d,
        "ground_truth": "rto" if will_rto else "legit",
        "rto_probability": round(rto_probability, 4),
    }


def _generate_signals(order: dict, customer: dict) -> dict:
    """Generate external signals for an order."""
    category = order["category"]
    category_return_rate = CATEGORY_RTO_RATES[category]

    # Recent events based on context
    events = ["None"]
    if order["pincode_rto_rate"] > 0.35:
        events.append("High RTO pincode")
    if customer["complaint_score"] > 0.5:
        events.append("Customer complaints detected")
    if customer["social_sentiment"] < -0.3:
        events.append("Negative social mentions")
    if random.random() < 0.1:
        events.append("Festive season peak")

    # Pick 1-2 events
    recent_events = random.sample(events[1:], min(2, len(events) - 1)) if len(events) > 1 else ["None"]

    return {
        "customer_id": customer["customer_id"],
        "order_id": order["order_id"],
        "pincode_rto_rate": order["pincode_rto_rate"],
        "category_return_rate": category_return_rate,
        "complaint_score": customer["complaint_score"],
        "social_sentiment": customer["social_sentiment"],
        "recent_events": "|".join(recent_events),
        "account_age_days": customer["account_age_days"],
    }


def generate_dataset(
    num_customers: int = 500,
    output_dir: str = "synthetic_data",
    train_ratio: float = 0.8,
) -> tuple[Path, Path, Path]:
    """
    Generate complete synthetic dataset.
    Returns paths to (customers_csv, orders_csv, signals_csv).
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    customers: list[dict] = []
    orders: list[dict] = []
    signals: list[dict] = []

    for _ in range(num_customers):
        customer_type = _generate_customer_type()
        customer = _generate_customer_profile(customer_type)
        customers.append(customer)

        # Generate 1-3 orders per customer
        num_orders = random.choices([1, 2, 3], weights=[0.7, 0.2, 0.1])[0]
        for _ in range(num_orders):
            order = _generate_order(customer)
            orders.append(order)

            signal = _generate_signals(order, customer)
            signals.append(signal)

    # Write customers.csv
    customers_file = output_path / "customers.csv"
    with open(customers_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "customer_id", "customer_type", "total_orders", "returns",
            "return_rate", "avg_order_value", "account_age_days",
            "complaint_score", "social_sentiment",
        ])
        writer.writeheader()
        writer.writerows(customers)

    # Write orders.csv
    orders_file = output_path / "orders.csv"
    with open(orders_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "customer_id", "order_value", "category",
            "payment_method", "delivery_pincode", "pincode_rto_rate",
            "recent_returns_30d", "ground_truth", "rto_probability",
        ])
        writer.writeheader()
        writer.writerows(orders)

    # Write signals.csv
    signals_file = output_path / "signals.csv"
    with open(signals_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "customer_id", "order_id", "pincode_rto_rate",
            "category_return_rate", "complaint_score", "social_sentiment",
            "recent_events", "account_age_days",
        ])
        writer.writeheader()
        writer.writerows(signals)

    # Print stats
    rto_count = sum(1 for o in orders if o["ground_truth"] == "rto")
    print(f"Generated {len(customers)} customers, {len(orders)} orders")
    print(f"  RTO rate: {rto_count}/{len(orders)} = {rto_count/len(orders):.1%}")
    print(f"  Files: {customers_file}, {orders_file}, {signals_file}")

    return customers_file, orders_file, signals_file


def load_customers(path: str = "synthetic_data/customers.csv") -> list[dict]:
    """Load customer profiles from CSV."""
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def load_orders(path: str = "synthetic_data/orders.csv") -> list[dict]:
    """Load orders from CSV."""
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def load_signals(path: str = "synthetic_data/signals.csv") -> list[dict]:
    """Load signals from CSV."""
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


if __name__ == "__main__":
    generate_dataset(num_customers=500)