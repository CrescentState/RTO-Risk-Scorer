"""
Shared order repository.

Single lookup implementation used by verification, analysis, and
test-case endpoints so all three observe identical records.
Paths are read from settings on every call so tests can redirect
them to tmp_path fixtures.
"""

import csv
import os
from typing import Any

from core.config import settings

ORDER_VALUE_TOLERANCE = 0.01


def _read_rows(path: str) -> list[dict[str, str]]:
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def data_signature() -> str:
    """Fingerprint of the three CSV datasets for cache invalidation."""
    parts = []
    for path in (settings.CUSTOMERS_CSV, settings.ORDERS_CSV, settings.SIGNALS_CSV):
        try:
            st = os.stat(path)
            parts.append(f"{path}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{path}:missing")
    return "|".join(parts)


def datasets_exist() -> bool:
    return os.path.exists(settings.CUSTOMERS_CSV) and os.path.exists(settings.ORDERS_CSV)


def get_customer(customer_id: str) -> dict[str, str] | None:
    for row in _read_rows(settings.CUSTOMERS_CSV):
        if row.get("customer_id") == customer_id:
            return row
    return None


def get_order(order_id: str) -> dict[str, str] | None:
    for row in _read_rows(settings.ORDERS_CSV):
        if row.get("order_id") == order_id:
            return row
    return None


def get_order_for_customer(order_id: str, customer_id: str) -> dict[str, str] | None:
    for row in _read_rows(settings.ORDERS_CSV):
        if row.get("order_id") == order_id and row.get("customer_id") == customer_id:
            return row
    return None


def get_signal(customer_id: str, order_id: str) -> dict[str, str] | None:
    """Fetch the signal row scoped to one exact order. Never falls back to another order."""
    for row in _read_rows(settings.SIGNALS_CSV):
        if row.get("customer_id") == customer_id and row.get("order_id") == order_id:
            return row
    return None


def list_test_case_customers() -> list[dict[str, str]]:
    prefixes = ("CUST_GOOD", "CUST_SERIAL", "CUST_FRAUD", "CUST_OCCASIONAL", "CUST_NEW")
    return [r for r in _read_rows(settings.CUSTOMERS_CSV) if (r.get("customer_id") or "").startswith(prefixes)]


def first_order_for_customer(customer_id: str) -> dict[str, str] | None:
    for row in _read_rows(settings.ORDERS_CSV):
        if row.get("customer_id") == customer_id:
            return row
    return None


def check_order_fields_match(
    order_row: dict[str, Any],
    order_value: Any,
    category: Any,
    payment_method: Any,
    delivery_pincode: Any,
    tolerance: float = ORDER_VALUE_TOLERANCE,
) -> list[dict[str, Any]]:
    """Compare request fields against the canonical stored order row."""
    mismatches: list[dict[str, Any]] = []
    if order_value is not None:
        try:
            stored_value = float(order_row["order_value"])
            if abs(stored_value - float(order_value)) > tolerance:
                mismatches.append({"field": "order_value", "expected": stored_value, "actual": float(order_value)})
        except (TypeError, ValueError, KeyError):
            mismatches.append({"field": "order_value", "expected": order_row.get("order_value"), "actual": order_value})
    if category is not None:
        stored_category = str(order_row.get("category", ""))
        if stored_category.lower() != str(category).lower():
            mismatches.append({"field": "category", "expected": stored_category, "actual": category})
    if payment_method is not None:
        stored_payment = str(order_row.get("payment_method", ""))
        if stored_payment.lower() != str(payment_method).lower():
            mismatches.append({"field": "payment_method", "expected": stored_payment, "actual": payment_method})
    if delivery_pincode is not None:
        stored_pincode = str(order_row.get("delivery_pincode", ""))
        if stored_pincode != str(delivery_pincode):
            mismatches.append({"field": "delivery_pincode", "expected": stored_pincode, "actual": delivery_pincode})
    return mismatches
