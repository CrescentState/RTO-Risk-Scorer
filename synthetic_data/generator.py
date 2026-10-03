"""
Synthetic data generator for RTO Risk Scorer.
Creates realistic customer profiles, order history, and external signals
with ground truth labels for evaluation.
"""

import csv
import random
from pathlib import Path
from typing import Any, Literal

import numpy as np

# ── Configuration ──
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

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

CustomerType = Literal["good", "occasional_returner", "serial_returner", "fraudster"]


def _generate_customer_id(idx: int) -> str:
    """Generate deterministic customer ID."""
    return f"CUST_{idx:05d}"


def _generate_order_id(idx: int) -> str:
    """Generate deterministic order ID."""
    return f"ORD_{idx:06d}"


def _generate_customer_type() -> CustomerType:
    """Weighted random customer type strictly matching PRD weights."""
    return random.choices(
        ["good", "occasional_returner", "serial_returner", "fraudster"],
        weights=[0.60, 0.25, 0.10, 0.05],
    )[0]  # type: ignore[return-value]


def _generate_customer_profile(customer_id: str, customer_type: CustomerType) -> dict:
    """Generate customer profile strictly adhering to PRD specifications."""
    if customer_type == "good":
        total_orders = random.randint(5, 50)
        return_rate = round(random.uniform(0.0, 0.10), 4)
        account_age_days = random.randint(60, 730)
        complaint_score = round(random.uniform(0.0, 0.20), 4)
        social_sentiment = round(random.uniform(0.30, 1.0), 4)

    elif customer_type == "occasional_returner":
        total_orders = random.randint(3, 30)
        return_rate = round(random.uniform(0.10, 0.30), 4)
        account_age_days = random.randint(30, 365)
        complaint_score = round(random.uniform(0.10, 0.40), 4)
        social_sentiment = round(random.uniform(-0.10, 0.50), 4)

    elif customer_type == "serial_returner":
        total_orders = random.randint(10, 40)
        return_rate = round(random.uniform(0.50, 0.90), 4)
        account_age_days = random.randint(14, 180)
        complaint_score = round(random.uniform(0.40, 0.80), 4)
        social_sentiment = round(random.uniform(-0.60, 0.10), 4)

    else:  # fraudster
        total_orders = random.randint(1, 15)
        return_rate = round(random.uniform(0.51, 1.0), 4)
        account_age_days = random.randint(1, 14)
        complaint_score = round(random.uniform(0.70, 1.0), 4)
        social_sentiment = round(random.uniform(-1.0, -0.40), 4)

    returns = int(total_orders * return_rate)

    # Log-normal distribution for avg_order_value (clamped ₹500 - ₹25,000)
    # mean=6.5 → e^6.5 ≈ 665, mean=7.5 → e^7.5 ≈ 1800, mean=8.0 → e^8 ≈ 2980
    # Use mean=7.5 for realistic average around ₹1500-2000
    raw_aov = np.random.lognormal(mean=7.5, sigma=0.6)
    avg_order_value = round(float(np.clip(raw_aov, 500.0, 25000.0)), 2)

    return {
        "customer_id": customer_id,
        "company_name": f"Customer_{customer_id}",
        "customer_type": customer_type,
        "total_orders": total_orders,
        "returns": returns,
        "return_rate": return_rate,
        "avg_order_value": avg_order_value,
        "account_age_days": account_age_days,
        "complaint_score": complaint_score,
        "social_sentiment": social_sentiment,
    }


def _generate_order(order_id: str, customer: dict) -> dict:
    """Generate order attributes using log-normal distribution for order value."""
    category = random.choices(CATEGORIES, weights=CATEGORY_WEIGHTS)[0]
    payment_method = random.choices(PAYMENT_METHODS, weights=PAYMENT_WEIGHTS)[0]
    pincode, pincode_rto_rate = random.choice(PINCODES)

    # Order value: log-normal around customer's average (clamped ₹500 - ₹25,000)
    raw_val = np.random.lognormal(mean=np.log(customer["avg_order_value"]), sigma=0.3)
    order_value = round(float(np.clip(raw_val, 500.0, 25000.0)), 2)

    recent_returns_30d = min(
        customer["returns"],
        random.randint(0, max(0, int(customer["returns"] * 0.4)))
    )

    # Ground truth determination
    rto_probability = 0.05
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
    if customer["return_rate"] > 0.50:
        rto_probability += 0.15
    if order_value > 10000.0:
        rto_probability += 0.05

    rto_probability = min(0.95, rto_probability)
    will_rto = random.random() < rto_probability

    return {
        "order_id": order_id,
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
    """Generate signal data strictly mapping to Signal Agent requirements."""
    category_return_rates = {
        "fashion": round(random.uniform(0.25, 0.40), 4),
        "electronics": round(random.uniform(0.15, 0.25), 4),
        "home": round(random.uniform(0.15, 0.28), 4),
        "beauty": round(random.uniform(0.10, 0.20), 4),
    }

    events = []
    if order["pincode_rto_rate"] > 0.35:
        events.append("High RTO pincode")
    if customer["complaint_score"] > 0.5:
        events.append("Customer complaints detected")
    if customer["social_sentiment"] < -0.3:
        events.append("Negative social mentions")
    if random.random() < 0.1:
        events.append("Festive season peak")

    if not events:
        events = ["None"]

    return {
        "customer_id": customer["customer_id"],
        "order_id": order["order_id"],
        "delivery_pincode": order["delivery_pincode"],
        "pincode_rto_rate": order["pincode_rto_rate"],
        "category_return_rate": category_return_rates[order["category"]],
        "complaint_score": customer["complaint_score"],
        "social_sentiment": customer["social_sentiment"],
        "recent_events": "|".join(events),
        "account_age_days": customer["account_age_days"],
    }


# Predictable test cases for manual testing - appended after random generation
PREDICTABLE_TEST_CASES: list[dict[str, Any]] = [
    {
        "customer_id": "CUST_GOOD_01",
        "company_name": "Good Customer Inc",
        "customer_type": "good",
        "total_orders": 25,
        "returns": 1,
        "return_rate": 0.04,
        "avg_order_value": 1500.0,
        "account_age_days": 365,
        "complaint_score": 0.05,
        "social_sentiment": 0.80,
        "split": "test",
        "orders": [
            {
                "order_id": "ORD_000001",
                "customer_id": "CUST_GOOD_01",
                "order_value": 2000.0,
                "category": "electronics",
                "payment_method": "upi",
                "delivery_pincode": "110001",
                "pincode_rto_rate": 0.15,
                "recent_returns_30d": 0,
                "ground_truth": "legit",
                "rto_probability": 0.05,
                "split": "test",
            }
        ],
        "signals": {
            "pincode_rto_rate": 0.15,
            "category_return_rate": 0.18,
            "complaint_score": 0.05,
            "social_sentiment": 0.80,
            "recent_events": "None",
            "account_age_days": 365,
        }
    },
    {
        "customer_id": "CUST_SERIAL_01",
        "company_name": "Serial Returner Ltd",
        "customer_type": "serial_returner",
        "total_orders": 20,
        "returns": 14,
        "return_rate": 0.70,
        "avg_order_value": 3000.0,
        "account_age_days": 60,
        "complaint_score": 0.60,
        "social_sentiment": -0.20,
        "split": "test",
        "orders": [
            {
                "order_id": "ORD_000002",
                "customer_id": "CUST_SERIAL_01",
                "order_value": 8000.0,
                "category": "fashion",
                "payment_method": "cod",
                "delivery_pincode": "560001",
                "pincode_rto_rate": 0.35,
                "recent_returns_30d": 4,
                "ground_truth": "rto",
                "rto_probability": 0.85,
                "split": "test",
            }
        ],
        "signals": {
            "pincode_rto_rate": 0.35,
            "category_return_rate": 0.35,
            "complaint_score": 0.60,
            "social_sentiment": -0.20,
            "recent_events": "High RTO pincode|Customer complaints detected",
            "account_age_days": 60,
        }
    },
    {
        "customer_id": "CUST_FRAUD_01",
        "company_name": "Fraudster Corp",
        "customer_type": "fraudster",
        "total_orders": 5,
        "returns": 5,
        "return_rate": 1.0,
        "avg_order_value": 12000.0,
        "account_age_days": 3,
        "complaint_score": 0.90,
        "social_sentiment": -0.80,
        "split": "test",
        "orders": [
            {
                "order_id": "ORD_000003",
                "customer_id": "CUST_FRAUD_01",
                "order_value": 15000.0,
                "category": "electronics",
                "payment_method": "cod",
                "delivery_pincode": "700002",
                "pincode_rto_rate": 0.50,
                "recent_returns_30d": 3,
                "ground_truth": "rto",
                "rto_probability": 0.95,
                "split": "test",
            }
        ],
        "signals": {
            "pincode_rto_rate": 0.50,
            "category_return_rate": 0.18,
            "complaint_score": 0.90,
            "social_sentiment": -0.80,
            "recent_events": "High RTO pincode|Customer complaints detected|Negative social mentions",
            "account_age_days": 3,
        }
    },
    {
        "customer_id": "CUST_OCCASIONAL_01",
        "company_name": "Occasional Returner",
        "customer_type": "occasional_returner",
        "total_orders": 10,
        "returns": 2,
        "return_rate": 0.20,
        "avg_order_value": 2500.0,
        "account_age_days": 120,
        "complaint_score": 0.25,
        "social_sentiment": 0.30,
        "split": "test",
        "orders": [
            {
                "order_id": "ORD_000004",
                "customer_id": "CUST_OCCASIONAL_01",
                "order_value": 6000.0,
                "category": "home",
                "payment_method": "cod",
                "delivery_pincode": "400001",
                "pincode_rto_rate": 0.18,
                "recent_returns_30d": 1,
                "ground_truth": "legit",
                "rto_probability": 0.25,
                "split": "test",
            }
        ],
        "signals": {
            "pincode_rto_rate": 0.18,
            "category_return_rate": 0.22,
            "complaint_score": 0.25,
            "social_sentiment": 0.30,
            "recent_events": "None",
            "account_age_days": 120,
        }
    },
    {
        "customer_id": "CUST_NEW_COD_01",
        "company_name": "New COD Customer",
        "customer_type": "good",
        "total_orders": 1,
        "returns": 0,
        "return_rate": 0.0,
        "avg_order_value": 8000.0,
        "account_age_days": 5,
        "complaint_score": 0.10,
        "social_sentiment": 0.50,
        "split": "test",
        "orders": [
            {
                "order_id": "ORD_000005",
                "customer_id": "CUST_NEW_COD_01",
                "order_value": 8000.0,
                "category": "beauty",
                "payment_method": "cod",
                "delivery_pincode": "110001",
                "pincode_rto_rate": 0.15,
                "recent_returns_30d": 0,
                "ground_truth": "legit",
                "rto_probability": 0.15,
                "split": "test",
            }
        ],
        "signals": {
            "pincode_rto_rate": 0.15,
            "category_return_rate": 0.15,
            "complaint_score": 0.10,
            "social_sentiment": 0.50,
            "recent_events": "None",
            "account_age_days": 5,
        }
    },
]


def generate_dataset(
    num_customers: int = 500,
    output_dir: str = "synthetic_data",
) -> tuple[Path, Path, Path]:
    """Generate customers and orders with a train/test split.

    The documented 500-customer dataset uses a 400/100 split; any other
    size uses an 80/20 split.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    customers: list[dict] = []
    orders: list[dict] = []
    signals: list[dict] = []

    # Reserve order IDs 1-5 for predictable test cases (ORD_000001-ORD_000005)
    test_case_order_count = len(PREDICTABLE_TEST_CASES)
    order_counter = test_case_order_count + 1
    train_count = 400 if num_customers == 500 else int(num_customers * 0.8)
    for c_idx in range(1, num_customers + 1):
        cust_id = _generate_customer_id(c_idx)
        c_type = _generate_customer_type()
        customer = _generate_customer_profile(cust_id, c_type)

        # Mark dataset split: 400/100 for the documented 500-customer
        # dataset, otherwise an 80/20 split.
        customer["split"] = "train" if c_idx <= train_count else "test"
        customers.append(customer)

        # Generate orders per customer
        num_orders = random.choices([1, 2], weights=[0.85, 0.15])[0]
        for _ in range(num_orders):
            ord_id = _generate_order_id(order_counter)
            order_counter += 1

            order = _generate_order(ord_id, customer)
            order["split"] = customer["split"]
            orders.append(order)

            signal = _generate_signals(order, customer)
            signals.append(signal)

    # Append predictable test cases
    for tc in PREDICTABLE_TEST_CASES:
        customer_data = {k: v for k, v in tc.items() if k not in ("orders", "signals")}
        customers.append(customer_data)

        for order in tc["orders"]:
            orders.append(order)

        signal_data = tc["signals"].copy()
        signal_data["customer_id"] = tc["customer_id"]
        signal_data["order_id"] = tc["orders"][0]["order_id"]
        signal_data["delivery_pincode"] = tc["orders"][0]["delivery_pincode"]
        signals.append(signal_data)

    # Write customers.csv
    customers_file = output_path / "customers.csv"
    with open(customers_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "customer_id", "company_name", "customer_type", "total_orders", "returns",
            "return_rate", "avg_order_value", "account_age_days",
            "complaint_score", "social_sentiment", "split"
        ])
        writer.writeheader()
        writer.writerows(customers)

    # Write orders.csv
    orders_file = output_path / "orders.csv"
    with open(orders_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "customer_id", "order_value", "category",
            "payment_method", "delivery_pincode", "pincode_rto_rate",
            "recent_returns_30d", "ground_truth", "rto_probability", "split"
        ])
        writer.writeheader()
        writer.writerows(orders)

    # Write signals.csv
    signals_file = output_path / "signals.csv"
    with open(signals_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "customer_id", "order_id", "delivery_pincode", "pincode_rto_rate",
            "category_return_rate", "complaint_score", "social_sentiment",
            "recent_events", "account_age_days"
        ])
        writer.writeheader()
        writer.writerows(signals)

    rto_count = sum(1 for o in orders if o["ground_truth"] == "rto")
    test_orders = sum(1 for o in orders if o["split"] == "test")
    train_customers = sum(1 for c in customers if c["split"] == "train")
    test_customers = sum(1 for c in customers if c["split"] == "test")

    print(f"Generated {len(customers)} customers ({train_customers} train / {test_customers} test), {len(orders)} orders ({test_orders} test orders).")
    print(f"Overall RTO rate: {rto_count}/{len(orders)} ({rto_count/len(orders):.1%})")
    print(f"Files written to {output_path.resolve()}")

    # Clear agent caches so new data is picked up
    try:
        from agents.profile_agent import _clear_profile_cache
        _clear_profile_cache()
    except ImportError:
        pass
    try:
        from agents.signal_agent import _clear_signal_cache
        _clear_signal_cache()
    except ImportError:
        pass

    return customers_file, orders_file, signals_file


def load_customers(path: str = "synthetic_data/customers.csv") -> list[dict]:
    """Load customer profiles from CSV with proper type conversion."""
    import csv
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "customer_id": row["customer_id"],
                "company_name": row["company_name"],
                "customer_type": row["customer_type"],
                "total_orders": int(row["total_orders"]),
                "returns": int(row["returns"]),
                "return_rate": float(row["return_rate"]),
                "avg_order_value": float(row["avg_order_value"]),
                "account_age_days": int(row["account_age_days"]),
                "complaint_score": float(row["complaint_score"]),
                "social_sentiment": float(row["social_sentiment"]),
                "split": row["split"],
            })
        return rows


def load_orders(path: str = "synthetic_data/orders.csv") -> list[dict]:
    """Load orders from CSV with proper type conversion."""
    import csv
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "order_id": row["order_id"],
                "customer_id": row["customer_id"],
                "order_value": float(row["order_value"]),
                "category": row["category"],
                "payment_method": row["payment_method"],
                "delivery_pincode": row["delivery_pincode"],
                "pincode_rto_rate": float(row["pincode_rto_rate"]),
                "recent_returns_30d": int(row["recent_returns_30d"]),
                "ground_truth": row["ground_truth"],
                "rto_probability": float(row["rto_probability"]),
                "split": row["split"],
            })
        return rows


def load_signals(path: str = "synthetic_data/signals.csv") -> list[dict]:
    """Load signals from CSV with proper type conversion."""
    import csv
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "customer_id": row["customer_id"],
                "order_id": row["order_id"],
                "delivery_pincode": row["delivery_pincode"],
                "pincode_rto_rate": float(row["pincode_rto_rate"]),
                "category_return_rate": float(row["category_return_rate"]),
                "complaint_score": float(row["complaint_score"]),
                "social_sentiment": float(row["social_sentiment"]),
                "recent_events": row["recent_events"],
                "account_age_days": int(row["account_age_days"]),
            })
        return rows


if __name__ == "__main__":
    generate_dataset(num_customers=500)
