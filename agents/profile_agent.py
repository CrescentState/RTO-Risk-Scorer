import os
from typing import Any

import pandas as pd

from core.cache import get_cached_response, set_cached_response
from core.config import settings

CUSTOMERS_CSV = settings.CUSTOMERS_CSV
ORDERS_CSV = settings.ORDERS_CSV

# Required fields for valid cached profile data
REQUIRED_PROFILE_FIELDS = {
    "total_orders", "return_rate", "avg_order_value", "days_since_first_order",
    "recent_returns_30d", "order_value", "category", "payment_method",
    "delivery_pincode", "pincode_rto_rate", "account_age_days", "data_available",
    "company_name"
}


def run_profile_agent(state: dict[str, Any]) -> dict[str, Any]:
    customer_id = state.get("customer_id")
    order_id = state.get("order_id")
    order_value = state.get("order_value")
    category = state.get("category")
    payment_method = state.get("payment_method")
    delivery_pincode = state.get("delivery_pincode")

    # Initialize confidence; sequential pipeline carries the complete error list forward
    confidence_score = float(state.get("confidence_score", 1.0))
    errors: list[str] = list(state.get("errors", []))

    # Track which validations have been done for this order_id to avoid duplicates across pipeline calls
    validated_orders: set[str] = set(state.get("_validated_orders", []))
    validated_fields: set[str] = set(state.get("_validated_fields", []))

    # Validate order_id matches customer_id in orders CSV
    if order_id and customer_id:
        if order_id not in validated_orders:
            order_match_error = _validate_order_customer_match(order_id, customer_id)
            if order_match_error and order_match_error not in errors:
                errors.append(order_match_error)
                confidence_score -= 0.3

        # Validate all order fields match the order_id in orders CSV
        if order_id not in validated_fields:
            field_errors = _validate_order_fields_match(order_id, order_value, category, payment_method, delivery_pincode)
            for field_error in field_errors:
                if field_error not in errors:
                    errors.append(field_error)
                    confidence_score -= 0.15

        # Mark this order as validated
        validated_orders.add(order_id)
        validated_fields.add(order_id)
        state["_validated_orders"] = list(validated_orders)
        state["_validated_fields"] = list(validated_fields)
    else:
        # No order_id provided, skip validation
        pass

    cache_key = f"v1:{customer_id}_{order_id}_profile"
    cached_data = get_cached_response(cache_key)

    if cached_data and _is_valid_cached_profile(cached_data):
        # Reapply the data-phase deduction/warnings stored with the payload so
        # warm cache hits produce identical confidence and audit entries.
        meta = cached_data.get("_cache_meta", {}) if isinstance(cached_data, dict) else {}
        try:
            deduction = float(meta.get("deduction", 0.0))
        except (TypeError, ValueError):
            deduction = 0.0
        warnings = meta.get("warnings", [])
        if isinstance(warnings, list):
            for warning in warnings:
                if isinstance(warning, str) and warning not in errors:
                    errors.append(warning)
        confidence_score = max(0.0, min(1.0, confidence_score - max(0.0, deduction)))
        state["transaction_profile"] = {k: v for k, v in cached_data.items() if k != "_cache_meta"}
        state["company_name"] = cached_data.get("company_name", f"Customer_{customer_id}")
        state["errors"] = errors
        state["confidence_score"] = confidence_score
        return state
    elif cached_data:
        if "Cache hit but profile data incomplete; re-querying database." not in errors:
            errors.append("Cache hit but profile data incomplete; re-querying database.")

    data_phase_confidence = confidence_score
    data_phase_error_count = len(errors)

    profile = None
    company_name = f"Customer_{customer_id}"

    try:
        # Load synthetic datasets with memoized parsing
        customers_df = _load_customers_df()
        orders_df = _load_orders_df()

        cust_row = customers_df[customers_df["customer_id"] == customer_id]

        if cust_row.empty:
            errors.append(f"Invalid customer_id: {customer_id} not found in database.")
            confidence_score -= 0.4
            profile = _build_default_profile(order_value, category, payment_method, delivery_pincode, data_available=False)
        else:
            row = cust_row.iloc[0]

            # Compute historical Pincode RTO rate using memoized function
            pincode_rto_rate = _compute_pincode_rto_rate(orders_df, delivery_pincode or "")

            # Compute recent_returns_30d from orders
            recent_returns_30d = _compute_recent_returns_30d(orders_df, customer_id or "")

            # Extract fields safely
            total_orders = _safe_get(row, "total_orders")
            return_rate = _safe_get(row, "return_rate")
            avg_order_value = _safe_get(row, "avg_order_value")
            account_age_days = _safe_get(row, "account_age_days")

            company_name = str(row.get("company_name", f"Customer_{customer_id}"))

            # Check critical fields (total_orders, return_rate, order_value)
            critical_missing = any(v is None for v in [total_orders, return_rate, order_value])
            if critical_missing:
                confidence_score -= 0.4
                data_available = False
            else:
                data_available = True

            # Dock confidence for missing secondary fields
            if pincode_rto_rate is None:
                confidence_score -= 0.05
                pincode_rto_rate = 0.0

            if account_age_days is None:
                confidence_score -= 0.05
                account_age_days = 0

            profile = {
                "total_orders": int(total_orders) if total_orders is not None else 0,
                "return_rate": float(return_rate) if return_rate is not None else 0.0,
                "avg_order_value": float(avg_order_value) if avg_order_value is not None else 0.0,
                "days_since_first_order": int(account_age_days) if account_age_days is not None else 0,
                "recent_returns_30d": recent_returns_30d,
                "order_value": float(order_value) if order_value is not None else 0.0,
                "category": str(category) if category else "",
                "payment_method": str(payment_method) if payment_method else "",
                "delivery_pincode": str(delivery_pincode) if delivery_pincode else "",
                "pincode_rto_rate": float(pincode_rto_rate),
                "account_age_days": int(account_age_days) if account_age_days is not None else 0,
                "data_available": data_available,
                "company_name": company_name,
            }

            if data_available:
                deduction = round(max(0.0, data_phase_confidence - confidence_score), 4)
                payload = dict(profile)
                payload["_cache_meta"] = {
                    "deduction": deduction,
                    "warnings": errors[data_phase_error_count:],
                }
                set_cached_response(cache_key, payload)

    except Exception as e:
        errors.append(f"Database error / timeout in Profile Agent: {str(e)}")
        confidence_score -= 0.3
        profile = _build_default_profile(order_value, category, payment_method, delivery_pincode, data_available=False)

    # Clamp confidence score to range [0.0, 1.0]
    confidence_score = max(0.0, min(1.0, confidence_score))

    state["transaction_profile"] = profile
    state["company_name"] = company_name
    state["confidence_score"] = confidence_score
    state["errors"] = errors

    return state


def _load_customers_df() -> pd.DataFrame:
    """Load customers CSV - reads fresh each time from configured path."""
    return pd.read_csv(settings.CUSTOMERS_CSV)


def _load_orders_df() -> pd.DataFrame:
    """Load orders CSV - reads fresh each time from configured path."""
    orders_csv = settings.ORDERS_CSV
    return pd.read_csv(orders_csv) if os.path.exists(orders_csv) else pd.DataFrame()


def _compute_pincode_rto_rate(orders_df: pd.DataFrame, delivery_pincode: str) -> float | None:
    """Compute pincode RTO rate from orders DataFrame. Returns None if not found."""
    if orders_df.empty or "delivery_pincode" not in orders_df.columns or "ground_truth" not in orders_df.columns:
        return None

    pincode_str = str(delivery_pincode)
    pincode_int = int(delivery_pincode) if str(delivery_pincode).isdigit() else None

    if pincode_int is not None:
        pincode_orders = orders_df[
            (orders_df["delivery_pincode"].astype(str) == pincode_str) |
            (orders_df["delivery_pincode"] == pincode_int)
        ]
    else:
        pincode_orders = orders_df[orders_df["delivery_pincode"].astype(str) == pincode_str]

    if pincode_orders.empty:
        return None

    rto_count = (pincode_orders["ground_truth"] == "rto").sum()
    return float(rto_count / len(pincode_orders))


def _compute_recent_returns_30d(orders_df: pd.DataFrame, customer_id: str) -> int:
    """Compute sum of recent_returns_30d for a customer."""
    if orders_df.empty or "customer_id" not in orders_df.columns:
        return 0

    cust_orders = orders_df[orders_df["customer_id"] == customer_id]
    if cust_orders.empty:
        return 0

    return int(cust_orders["recent_returns_30d"].sum())


def _clear_profile_cache() -> None:
    """Clear caches for testing purposes. No-op since we removed LRU caches."""
    pass


def _safe_get(row: pd.Series, col: str, default: Any = None) -> Any:
    """Safely extract value from pandas Series with NaN handling."""
    if col not in row.index:
        return default
    val = row[col]
    return val if pd.notna(val) else default


def _is_valid_cached_profile(data: dict) -> bool:
    """Validate cached profile data has all required fields with valid types."""
    if not isinstance(data, dict):
        return False
    if not REQUIRED_PROFILE_FIELDS.issubset(data.keys()):
        return False
    try:
        int(data["total_orders"])
        float(data["return_rate"])
        float(data["avg_order_value"])
        int(data["days_since_first_order"])
        int(data["recent_returns_30d"])
        float(data["order_value"])
        str(data["category"])
        str(data["payment_method"])
        str(data["delivery_pincode"])
        float(data["pincode_rto_rate"])
        int(data["account_age_days"])
        bool(data["data_available"])
        str(data["company_name"])
    except (ValueError, TypeError, KeyError):
        return False
    # Validate ranges
    if not (0.0 <= data["return_rate"] <= 1.0):
        return False
    return not data["total_orders"] < 0


def _build_default_profile(
    order_value: Any,
    category: Any,
    payment_method: Any,
    delivery_pincode: Any,
    data_available: bool = False,
) -> dict[str, Any]:
    return {
        "total_orders": 0,
        "return_rate": 0.0,
        "avg_order_value": 0.0,
        "days_since_first_order": 0,
        "recent_returns_30d": 0,
        "order_value": float(order_value) if order_value is not None else 0.0,
        "category": str(category) if category else "",
        "payment_method": str(payment_method) if payment_method else "",
        "delivery_pincode": str(delivery_pincode) if delivery_pincode else "",
        "pincode_rto_rate": 0.0,
        "account_age_days": 0,
        "data_available": data_available,
    }


def _validate_order_customer_match(order_id: str, customer_id: str) -> str | None:
    """Validate that order_id belongs to customer_id in orders CSV.
    Returns error message if mismatch, None if valid or validation not possible."""
    try:
        orders_df = _load_orders_df()
        if orders_df.empty:
            return None  # Cannot validate, skip
        match = orders_df[
            (orders_df["order_id"] == order_id) & (orders_df["customer_id"] == customer_id)
        ]
        if match.empty:
            return f"Order ID {order_id} does not belong to customer {customer_id}"
    except Exception:
        return None  # Skip validation on error
    return None


def _validate_order_fields_match(order_id: str, order_value: float | None, category: str | None,
                                  payment_method: str | None, delivery_pincode: str | None) -> list[str]:
    """Validate that order_id fields match the orders CSV.
    Returns list of error messages for mismatched fields, empty list if all match or validation not possible."""
    errors: list[str] = []
    try:
        orders_df = _load_orders_df()
        if orders_df.empty:
            return errors  # Cannot validate, skip

        match = orders_df[orders_df["order_id"] == order_id]
        if match.empty:
            return [f"Order ID {order_id} not found in database"]

        order_row = match.iloc[0]

        # Check order_value (allow small float tolerance)
        if order_value is not None:
            stored_value = float(order_row["order_value"])
            if abs(stored_value - order_value) > 0.01:  # 1 paisa tolerance
                errors.append(f"Order value mismatch: expected {stored_value}, got {order_value}")

        # Check category
        if category is not None:
            stored_category = str(order_row["category"])
            if stored_category != category:
                errors.append(f"Category mismatch: expected {stored_category}, got {category}")

        # Check payment_method
        if payment_method is not None:
            stored_payment = str(order_row["payment_method"])
            if stored_payment != payment_method:
                errors.append(f"Payment method mismatch: expected {stored_payment}, got {payment_method}")

        # Check delivery_pincode
        if delivery_pincode is not None:
            stored_pincode = str(order_row["delivery_pincode"])
            if stored_pincode != delivery_pincode:
                errors.append(f"Delivery pincode mismatch: expected {stored_pincode}, got {delivery_pincode}")

    except Exception:
        pass  # Skip validation on error
    return errors
