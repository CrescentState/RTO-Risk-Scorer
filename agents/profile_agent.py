import os
import pandas as pd
from typing import Dict, Any, Optional
from functools import lru_cache
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


def run_profile_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    customer_id = state.get("customer_id")
    order_id = state.get("order_id")
    order_value = state.get("order_value")
    category = state.get("category")
    payment_method = state.get("payment_method")
    delivery_pincode = state.get("delivery_pincode")

    # Preserve error chain and initialize confidence
    errors = list(state.get("errors", []))
    confidence_score = float(state.get("confidence_score", 1.0))

    cache_key = f"{customer_id}_profile"
    cached_data = get_cached_response(cache_key)

    if cached_data and _is_valid_cached_profile(cached_data):
        state["transaction_profile"] = cached_data
        state["company_name"] = cached_data.get("company_name", f"Customer_{customer_id}")
        state["errors"] = errors
        state["confidence_score"] = confidence_score
        return state
    elif cached_data:
        errors.append("Cache hit but profile data incomplete; re-querying database.")

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
            pincode_rto_rate = _compute_pincode_rto_rate(orders_df, delivery_pincode)

            # Compute recent_returns_30d from orders
            recent_returns_30d = _compute_recent_returns_30d(orders_df, customer_id)

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
                set_cached_response(cache_key, profile)

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


@lru_cache(maxsize=64)
def _load_customers_df() -> pd.DataFrame:
    """Load customers CSV with LRU cache."""
    return pd.read_csv(CUSTOMERS_CSV)


@lru_cache(maxsize=64)
def _load_orders_df() -> pd.DataFrame:
    """Load orders CSV with LRU cache."""
    return pd.read_csv(ORDERS_CSV) if os.path.exists(ORDERS_CSV) else pd.DataFrame()


def _clear_profile_cache() -> None:
    """Clear LRU caches for testing purposes."""
    _load_customers_df.cache_clear()
    _load_orders_df.cache_clear()
    _compute_pincode_rto_rate.cache_clear()
    _compute_recent_returns_30d.cache_clear()


def _compute_pincode_rto_rate(orders_df: pd.DataFrame, delivery_pincode: str) -> Optional[float]:
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


def _safe_get(row: pd.Series, col: str, default=None):
    """Safely extract value from pandas Series with NaN handling."""
    if col not in row.index:
        return default
    val = row[col]
    return val if pd.notna(val) else default


def _is_valid_cached_profile(data: Dict) -> bool:
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
    if data["total_orders"] < 0:
        return False
    return True


def _build_default_profile(order_value, category, payment_method, delivery_pincode, data_available=False):
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