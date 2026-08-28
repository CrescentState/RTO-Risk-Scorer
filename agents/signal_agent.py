import os
import csv
from typing import Dict, Any, List, Optional, Tuple
from collections import deque
from functools import lru_cache
from core.cache import get_cached_response, set_cached_response

SIGNALS_CSV = "synthetic_data/signals.csv"

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


def run_signal_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agent 2: Gathers external risk signals from cache or synthetic signals DB.
    Validates schemas, applies fallback decisions, and docks confidence scores.
    Uses LRU cache for parsed signals and deque for event processing.
    """
    customer_id = state.get("customer_id", "")
    delivery_pincode = str(state.get("delivery_pincode", ""))
    category = state.get("category", "")
    
    # Inherit existing state context
    confidence_score = float(state.get("confidence_score", 1.0))
    errors = list(state.get("errors", []))
    
    transaction_profile = state.get("transaction_profile", {})
    profile_account_age = transaction_profile.get("account_age_days")

    # Step 1: Cache Check (24hr TTL, key: "{customer_id}_{pincode}_signals")
    cache_key = f"{customer_id}_{delivery_pincode}_signals"
    cached_signals = get_cached_response(cache_key)

    if cached_signals and isinstance(cached_signals, dict):
        # Validate cached data completeness
        if _is_valid_cached_signal(cached_signals):
            state["signal_data"] = cached_signals
            state["errors"] = errors
            state["confidence_score"] = confidence_score
            return state
        else:
            errors.append("Cache hit but data incomplete; re-querying signals DB.")

    # Step 2: Query Synthetic Signal Database with memoized CSV parsing
    try:
        exact_match, fallback_match = _query_signals_db(customer_id, delivery_pincode)
    except Exception as e:
        errors.append(f"Signal database timeout/error: {str(e)}")
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
    recent_events: List[str] = ["None"]
    signal_account_age = profile_account_age if profile_account_age is not None else 0
    pincode_matched = False

    if exact_match:
        matched_row = exact_match
        pincode_matched = True
    elif fallback_match:
        matched_row = fallback_match
        pincode_matched = False
    else:
        matched_row = None

    if matched_row is None:
        errors.append(f"No external signals found for customer {customer_id} / pincode {delivery_pincode}.")
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
            try:
                signal_account_age = int(matched_row["account_age_days"])
            except ValueError:
                pass

    # If pincode didn't match exactly, apply pincode penalty
    if not pincode_matched and signals_available:
        raw_pincode_rate = None  # Force category fallback
        confidence_score -= 0.1
        errors.append(f"Pincode {delivery_pincode} not found for customer; using category fallback.")

    # Step 3: Parse Signals & Apply Fail-Open Defaults
    fallback_rto = DEFAULT_CATEGORY_RTO_RATES.get(category, 0.25)
    fallback_return = DEFAULT_CATEGORY_RETURN_RATES.get(category, 0.25)
    
    pincode_rto_rate = _parse_float(raw_pincode_rate, fallback_rto)
    category_return_rate = _parse_float(raw_cat_rate, fallback_return)
    complaint_score = _parse_float(raw_complaint, 0.0)
    social_sentiment = _parse_float(raw_sentiment, 0.0)

    # Step 4: Schema Validation & Retry logic using stack for retry tracking
    retry_stack = []  # Stack to track validation attempts
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
        errors.append("LLM/Signal validation failed after retry.")
        confidence_score -= 0.1
        signals_available = False

    # Step 5: Docking Rules Check
    # Hostile signals detected (complaint_score > 0.7)
    if complaint_score > 0.7:
        confidence_score -= 0.05

    # Critical signal mismatch (profile says new <= 7 days, signals say old > 30 days)
    if profile_account_age is not None and signals_available:
        if profile_account_age <= 7 and signal_account_age > 30:
            errors.append("Critical signal mismatch: profile account age vs signal account age.")
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
        set_cached_response(cache_key, signal_data)

    state["signal_data"] = signal_data
    state["confidence_score"] = round(confidence_score, 4)
    state["errors"] = errors

    return state


@lru_cache(maxsize=128)
def _query_signals_db(customer_id: str, delivery_pincode: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Query signals CSV with LRU cache for repeated lookups.
    Returns (exact_match, fallback_match) tuple.
    """
    exact_match = None
    fallback_match = None
    
    if not os.path.exists(SIGNALS_CSV):
        return (None, None)
    
    try:
        with open(SIGNALS_CSV, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Exact pincode match
                if row.get("customer_id") == customer_id and row.get("delivery_pincode") == delivery_pincode:
                    exact_match = dict(row)
                    break  # Early exit on exact match
                # Fallback: first customer match (for account_age, complaint, sentiment)
                elif row.get("customer_id") == customer_id and fallback_match is None:
                    fallback_match = dict(row)
    except Exception:
        pass  # Return (None, None) on error
    
    return (exact_match, fallback_match)


def _parse_events(events_str: str) -> List[str]:
    """Parse pipe-separated events using deque for efficient appends."""
    events_deque = deque()
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


def _is_valid_cached_signal(data: Dict) -> bool:
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
    if not (-1.0 <= data["social_sentiment"] <= 1.0):
        return False
    return True


def _clear_signal_cache() -> None:
    """Clear LRU caches for testing purposes."""
    _query_signals_db.cache_clear()