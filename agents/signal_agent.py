import contextlib
import csv
import os
from collections import deque
from typing import Any

from core.cache import get_cached_response, set_cached_response
from core.config import settings

# Use config setting for CSV path
SIGNALS_CSV = settings.SIGNALS_CSV

# Category defaults: RTO rates (for pincode fallback) and Return rates (for category fallback)
DEFAULT_CATEGORY_RTO_RATES = {
    "fashion": 0.35,
    "electronics": 0.18,
    "home": 0.22,
    "beauty": 0.28,
}

DEFAULT_CATEGORY_RETURN_RATES = {
    "fashion": 0.35,
    "electronics": 0.18,
    "home": 0.22,
    "beauty": 0.28,
}

# Required fields for valid cached signal data
REQUIRED_SIGNAL_FIELDS = {
    "pincode_rto_rate", "category_return_rate", "complaint_score",
    "social_sentiment", "recent_events", "account_age_days", "signals_available"
}


def run_signal_agent(state: dict[str, Any]) -> dict[str, Any]:
    """
    Agent 2: Gathers external risk signals from cache or synthetic signals DB.
    Validates schemas, applies fallback decisions, and docks confidence scores.
    Uses LRU cache for parsed signals and deque for event processing.
    """
    customer_id = state.get("customer_id", "")
    order_id = state.get("order_id", "")
    delivery_pincode = str(state.get("delivery_pincode", ""))
    category = state.get("category", "")

    # Inherit existing state context
    confidence_score = float(state.get("confidence_score", 1.0))
    errors = list(state.get("errors", []))

    transaction_profile = state.get("transaction_profile", {})
    profile_account_age = transaction_profile.get("account_age_days")

    # Track initial error count to identify signal agent's own errors
    initial_error_count = len(state.get("errors", []))
    signal_start_confidence = confidence_score

    # Step 1: Cache Check (24hr TTL, versioned key scoped to one exact order)
    cache_key = f"v1:{customer_id}_{order_id}_{delivery_pincode}_{category}_signals"
    cached_signals = get_cached_response(cache_key)

    if cached_signals and isinstance(cached_signals, dict):
        # Validate cached data completeness
        if _is_valid_cached_signal(cached_signals):
            # Reapply stored deduction/warnings so warm hits match cold runs.
            # Only signal agent's own warnings are restored, never profile errors.
            meta = cached_signals.get("_cache_meta", {}) if isinstance(cached_signals, dict) else {}
            try:
                deduction = float(meta.get("deduction", 0.0))
            except (TypeError, ValueError):
                deduction = 0.0
            warnings = meta.get("warnings", cached_signals.get("_cached_errors", []))
            if isinstance(warnings, list):
                for warning in warnings:
                    if isinstance(warning, str) and warning not in errors:
                        errors.append(warning)
            confidence_score = max(0.0, min(1.0, confidence_score - max(0.0, deduction)))
            state["signal_data"] = {
                k: v for k, v in cached_signals.items() if k not in ("_cached_errors", "_cache_meta")
            }
            state["errors"] = errors
            state["confidence_score"] = confidence_score
            return state
        else:
            cache_error = "Cache hit but data incomplete; re-querying signals DB."
            if cache_error not in errors:
                errors.append(cache_error)

    # Step 2: Query Synthetic Signal Database scoped to this exact order
    try:
        matched_row = _query_signals_db(customer_id, order_id, delivery_pincode)
    except Exception as e:
        db_error = f"Signal database timeout/error: {str(e)}"
        if db_error not in errors:
            errors.append(db_error)
        confidence_score -= 0.1
        signals_available = False

        # Return early with defaults on DB error
        signal_data = {
            "pincode_rto_rate": DEFAULT_CATEGORY_RTO_RATES.get(category, 0.25),
            "category_return_rate": DEFAULT_CATEGORY_RETURN_RATES.get(category, 0.25),
            "complaint_score": 0.0,
            "social_sentiment": 0.0,
            "recent_events": ["None"],
            "account_age_days": profile_account_age if profile_account_age is not None else 0,
            "signals_available": False
        }

        state["signal_data"] = signal_data
        state["confidence_score"] = round(max(0.0, min(1.0, confidence_score)), 4)
        state["errors"] = errors
        return state

    signals_available = True
    raw_pincode_rate = None
    raw_cat_rate = None
    raw_complaint = None
    raw_sentiment = None
    recent_events: list[str] = ["None"]
    signal_account_age = profile_account_age if profile_account_age is not None else 0

    if matched_row is None:
        no_signal_error = f"No external signals found for customer {customer_id} / order {order_id}."
        if no_signal_error not in errors:
            errors.append(no_signal_error)
        confidence_score -= 0.1
        signals_available = False
    else:
        raw_pincode_rate = matched_row.get("pincode_rto_rate")
        raw_cat_rate = matched_row.get("category_return_rate")
        raw_complaint = matched_row.get("complaint_score")
        raw_sentiment = matched_row.get("social_sentiment")

        # Parse events list using deque for efficient processing
        events_str = str(matched_row.get("recent_events", "None"))
        recent_events = _parse_events(events_str)

        if matched_row.get("account_age_days") is not None:
            with contextlib.suppress(ValueError):
                signal_account_age = int(matched_row["account_age_days"])

    # Step 3: Parse Signals & Apply Fail-Open Defaults
    fallback_rto = DEFAULT_CATEGORY_RTO_RATES.get(category, 0.25)
    fallback_return = DEFAULT_CATEGORY_RETURN_RATES.get(category, 0.25)

    pincode_rto_rate = _parse_float(raw_pincode_rate, fallback_rto)
    category_return_rate = _parse_float(raw_cat_rate, fallback_return)
    complaint_score = _parse_float(raw_complaint, 0.0)
    social_sentiment = _parse_float(raw_sentiment, 0.0)

    # Step 4: Schema Validation & Retry logic using stack for retry tracking
    retry_stack: list[tuple[float, float]] = []  # Stack to track validation attempts
    max_retries = 1

    while len(retry_stack) <= max_retries:
        valid_schema = (0.0 <= complaint_score <= 1.0) and (-1.0 <= social_sentiment <= 1.0)
        if valid_schema:
            break

        # Push current invalid state to stack for potential rollback
        retry_stack.append((complaint_score, social_sentiment))

        # Retry logic: enforce schema bounds clamping
        complaint_score = max(0.0, min(1.0, complaint_score))
        social_sentiment = max(-1.0, min(1.0, social_sentiment))

    if len(retry_stack) > max_retries:
        validation_error = "LLM/Signal validation failed after retry."
        if validation_error not in errors:
            errors.append(validation_error)
        confidence_score -= 0.1
        signals_available = False

    # Step 5: Docking Rules Check
    # Hostile signals detected (complaint_score > 0.7)
    if complaint_score > 0.7:
        confidence_score -= 0.05

    # Critical signal mismatch (profile says new <= 7 days, signals say old > 30 days)
    if (
        profile_account_age is not None
        and signals_available
        and profile_account_age <= 7
        and signal_account_age > 30
    ):
        mismatch_error = "Critical signal mismatch: profile account age vs signal account age."
        if mismatch_error not in errors:
            errors.append(mismatch_error)
        confidence_score -= 0.1

    # Clamp final confidence score to [0.0, 1.0]
    confidence_score = max(0.0, min(1.0, confidence_score))

    signal_data = {
        "pincode_rto_rate": float(pincode_rto_rate),
        "category_return_rate": float(category_return_rate),
        "complaint_score": float(complaint_score),
        "social_sentiment": float(social_sentiment),
        "recent_events": recent_events,
        "account_age_days": int(signal_account_age),
        "signals_available": signals_available
    }

    # Store in cache on success
    if signals_available:
        cache_data = signal_data.copy()
        # Only store signal agent's own errors (added after initial_error_count), not profile agent's validation errors
        signal_agent_errors = errors[initial_error_count:]
        deduction = round(max(0.0, signal_start_confidence - confidence_score), 4)
        cache_data["_cached_errors"] = signal_agent_errors
        cache_data["_cache_meta"] = {"deduction": deduction, "warnings": signal_agent_errors}
        set_cached_response(cache_key, cache_data)

    state["signal_data"] = signal_data
    state["confidence_score"] = round(confidence_score, 4)
    state["errors"] = errors

    return state


def _query_signals_db(customer_id: str, order_id: str, delivery_pincode: str) -> dict | None:
    """
    Query signals CSV for one exact order (customer_id + order_id).
    Validates that the signal row pincode matches the request pincode.
    Never reuses another order's signals. Returns None on any mismatch.
    No caching - reads fresh each time to pick up data changes.
    """
    signals_csv = settings.SIGNALS_CSV
    if not os.path.exists(signals_csv):
        return None

    try:
        with open(signals_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("customer_id") == customer_id and row.get("order_id") == order_id:
                    if str(row.get("delivery_pincode", "")) != str(delivery_pincode):
                        return None
                    return dict(row)
    except Exception:
        pass  # Return None on error

    return None


def _clear_signal_cache() -> None:
    """Clear LRU caches for testing purposes. Kept for compatibility."""
    pass


def _parse_events(events_str: str) -> list[str]:
    """Parse pipe-separated events using deque for efficient appends."""
    events_deque: deque[str] = deque()
    for e in events_str.split("|"):
        e = e.strip()
        if e:
            events_deque.append(e)
    return list(events_deque) if events_deque else ["None"]


def _parse_float(val: Any, default: float) -> float:
    """Parse float with graceful degradation."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _is_valid_cached_signal(data: dict) -> bool:
    """Validate cached signal data has all required fields with valid types."""
    if not isinstance(data, dict):
        return False
    # Check all required fields present
    if not REQUIRED_SIGNAL_FIELDS.issubset(data.keys()):
        return False
    # Validate types
    try:
        float(data["pincode_rto_rate"])
        float(data["category_return_rate"])
        float(data["complaint_score"])
        float(data["social_sentiment"])
        list(data["recent_events"])
        int(data["account_age_days"])
        bool(data["signals_available"])
    except (ValueError, TypeError, KeyError):
        return False
    # Validate ranges
    if not (0.0 <= data["complaint_score"] <= 1.0):
        return False
    return bool(-1.0 <= data["social_sentiment"] <= 1.0)
