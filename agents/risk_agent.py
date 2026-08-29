"""
Agent 3: Risk Scorer Agent
Computes a deterministic 0–100 risk score based on transaction profile and signal data,
assigns an action recommendation, and optionally generates an LLM explanation narrative.

Uses rule registry with frozen dataclass definitions, IntFlag bitmask for triggered rules tracking,
singleton Gemini client for narrative generation, and dispatch dict for message formatting.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntFlag, StrEnum, auto
from string import Template
from typing import Any

from core.clients import get_gemini_client
from core.config import settings


class RuleName(StrEnum):
    """Type-safe rule identifiers for bitmask positions and dispatch."""
    SERIAL_RETURNER = "serial_returner"
    RETURN_VELOCITY_SPIKE = "return_velocity_spike"
    HIGH_VALUE_NEW_CUSTOMER = "high_value_new_customer"
    COD_HIGH_VALUE = "cod_high_value"
    HIGH_RTO_PINCODE = "high_rto_pincode"
    HIGH_COMPLAINT_HISTORY = "high_complaint_history"
    NEGATIVE_SOCIAL_SIGNALS = "negative_social_signals"
    BRAND_NEW_ACCOUNT = "brand_new_account"
    HIGH_RTO_CATEGORY = "high_rto_category"


class TriggeredRules(IntFlag):
    """Type-safe bitmask for triggered rules. Position matches rule registry index."""
    NONE = 0
    SERIAL_RETURNER = auto()           # 1 << 0
    RETURN_VELOCITY_SPIKE = auto()     # 1 << 1
    HIGH_VALUE_NEW_CUSTOMER = auto()   # 1 << 2
    COD_HIGH_VALUE = auto()            # 1 << 3
    HIGH_RTO_PINCODE = auto()          # 1 << 4
    HIGH_COMPLAINT_HISTORY = auto()    # 1 << 5
    NEGATIVE_SOCIAL_SIGNALS = auto()   # 1 << 6
    BRAND_NEW_ACCOUNT = auto()         # 1 << 7
    HIGH_RTO_CATEGORY = auto()         # 1 << 8


@dataclass(frozen=True, slots=True)
class RiskRule:
    """Immutable rule definition with condition, weight, and message template."""
    name: RuleName
    condition: Callable[[dict[str, Any], dict[str, Any]], bool]
    weight: float
    message_template: str
    threshold_key: str | None = None


@dataclass(frozen=True, slots=True)
class RiskThresholds:
    """Deterministic recommendation thresholds from config."""
    auto_approve_max: float
    manual_review_max: float
    max_score: float = 100.0


# Threshold keys map to settings for single source of truth
THRESHOLD_KEYS = {
    RuleName.SERIAL_RETURNER: "SERIAL_RETURNER_THRESHOLD",
    RuleName.RETURN_VELOCITY_SPIKE: None,  # Uses hardcoded > 3
    RuleName.HIGH_VALUE_NEW_CUSTOMER: "HIGH_VALUE_THRESHOLD",
    RuleName.COD_HIGH_VALUE: "COD_HIGH_VALUE_THRESHOLD",
    RuleName.HIGH_RTO_PINCODE: "HIGH_RTO_PINCODE_THRESHOLD",
    RuleName.HIGH_COMPLAINT_HISTORY: "HIGH_COMPLAINT_THRESHOLD",
    RuleName.NEGATIVE_SOCIAL_SIGNALS: "HOSTILE_SENTIMENT_THRESHOLD",
    RuleName.BRAND_NEW_ACCOUNT: "NEW_ACCOUNT_DAYS",
    RuleName.HIGH_RTO_CATEGORY: "HIGH_CATEGORY_RTO_THRESHOLD",
}


DEFAULT_NARRATIVE = "Risk assessment based on transaction history and delivery signals."


# Rule Registry - Single source of truth for all 9 deterministic rules
# Order defines bitmask position (matches TriggeredRules enum)
RISK_RULES = [
    RiskRule(
        name=RuleName.SERIAL_RETURNER,
        condition=lambda tp, sd: tp.get("return_rate") is not None and tp["return_rate"] > settings.SERIAL_RETURNER_THRESHOLD,
        weight=30.0,
        message_template="Serial returner (rate: {rate:.0%})",
        threshold_key="SERIAL_RETURNER_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.RETURN_VELOCITY_SPIKE,
        condition=lambda tp, sd: tp.get("recent_returns_30d") is not None and tp["recent_returns_30d"] > 3,
        weight=25.0,
        message_template="Return velocity spike ({count} in 30d)",
        threshold_key=None,
    ),
    RiskRule(
        name=RuleName.HIGH_VALUE_NEW_CUSTOMER,
        condition=lambda tp, sd: (
            tp.get("order_value") is not None and tp["order_value"] > settings.HIGH_VALUE_THRESHOLD
            and tp.get("total_orders") is not None and tp["total_orders"] < 3
        ),
        weight=20.0,
        message_template="High-value new customer",
        threshold_key="HIGH_VALUE_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.COD_HIGH_VALUE,
        condition=lambda tp, sd: (
            tp.get("payment_method") is not None and str(tp["payment_method"]).lower() == "cod"
            and tp.get("order_value") is not None and tp["order_value"] > settings.COD_HIGH_VALUE_THRESHOLD
        ),
        weight=15.0,
        message_template="COD high-value order",
        threshold_key="COD_HIGH_VALUE_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.HIGH_RTO_PINCODE,
        condition=lambda tp, sd: sd.get("pincode_rto_rate") is not None and sd["pincode_rto_rate"] > settings.HIGH_RTO_PINCODE_THRESHOLD,
        weight=15.0,
        message_template="High-RTO delivery pincode ({rate:.0%})",
        threshold_key="HIGH_RTO_PINCODE_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.HIGH_COMPLAINT_HISTORY,
        condition=lambda tp, sd: sd.get("complaint_score") is not None and sd["complaint_score"] > settings.HIGH_COMPLAINT_THRESHOLD,
        weight=15.0,
        message_template="High complaint history",
        threshold_key="HIGH_COMPLAINT_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.NEGATIVE_SOCIAL_SIGNALS,
        condition=lambda tp, sd: sd.get("social_sentiment") is not None and sd["social_sentiment"] < settings.HOSTILE_SENTIMENT_THRESHOLD,
        weight=10.0,
        message_template="Negative social signals",
        threshold_key="HOSTILE_SENTIMENT_THRESHOLD",
    ),
    RiskRule(
        name=RuleName.BRAND_NEW_ACCOUNT,
        condition=lambda tp, sd: tp.get("account_age_days") is not None and tp["account_age_days"] < settings.NEW_ACCOUNT_DAYS,
        weight=15.0,
        message_template="Brand new account",
        threshold_key="NEW_ACCOUNT_DAYS",
    ),
    RiskRule(
        name=RuleName.HIGH_RTO_CATEGORY,
        condition=lambda tp, sd: sd.get("category_return_rate") is not None and sd["category_return_rate"] > settings.HIGH_CATEGORY_RTO_THRESHOLD,
        weight=10.0,
        message_template="High-RTO category ({rate:.0%})",
        threshold_key="HIGH_CATEGORY_RTO_THRESHOLD",
    ),
]


THRESHOLDS = RiskThresholds(
    auto_approve_max=settings.AUTO_APPROVE_MAX_SCORE,
    manual_review_max=settings.MANUAL_REVIEW_MAX_SCORE,
    max_score=100.0,
)


def _evaluate_rules(transaction_profile: dict[str, Any], signal_data: dict[str, Any]) -> tuple[float, list[str], "TriggeredRules"]:
    """
    Evaluate all risk rules against transaction profile and signal data.
    Returns: (raw_score, triggered_factors, triggered_bitmask)
    Early exits when score reaches 100 (no need to evaluate remaining rules).
    """

    # Dispatch dict for message formatting - O(1) lookup
    def _fmt_serial_returner(tp: dict, sd: dict) -> str:
        rate_val = tp.get("return_rate")
        return f"Serial returner (rate: {rate_val:.0%})" if rate_val is not None else "Serial returner"

    def _fmt_velocity_spike(tp: dict, sd: dict) -> str:
        count_val = tp.get("recent_returns_30d")
        return f"Return velocity spike ({count_val} in 30d)" if count_val is not None else "Return velocity spike"

    def _fmt_high_value_new(tp: dict, sd: dict) -> str:
        return "High-value new customer"

    def _fmt_cod_high(tp: dict, sd: dict) -> str:
        return "COD high-value order"

    def _fmt_high_rto_pincode(tp: dict, sd: dict) -> str:
        rate_val = sd.get("pincode_rto_rate")
        return f"High-RTO delivery pincode ({rate_val:.0%})" if rate_val is not None else "High-RTO delivery pincode"

    def _fmt_high_complaint(tp: dict, sd: dict) -> str:
        return "High complaint history"

    def _fmt_negative_social(tp: dict, sd: dict) -> str:
        return "Negative social signals"

    def _fmt_brand_new(tp: dict, sd: dict) -> str:
        return "Brand new account"

    def _fmt_high_rto_category(tp: dict, sd: dict) -> str:
        rate_val = sd.get("category_return_rate")
        return f"High-RTO category ({rate_val:.0%})" if rate_val is not None else "High-RTO category"

    # Dispatch dict: O(1) formatter lookup by rule name
    formatters = {
        "serial_returner": lambda tp, sd: f"Serial returner (rate: {tp.get('return_rate'):.0%})" if tp.get("return_rate") is not None else "Serial returner",
        "return_velocity_spike": lambda tp, sd: f"Return velocity spike ({tp.get('recent_returns_30d')} in 30d)" if tp.get("recent_returns_30d") is not None else "Return velocity spike",
        "high_value_new_customer": lambda tp, sd: "High-value new customer",
        "cod_high_value": lambda tp, sd: "COD high-value order",
        "high_rto_pincode": lambda tp, sd: f"High-RTO delivery pincode ({sd.get('pincode_rto_rate'):.0%})" if sd.get("pincode_rto_rate") is not None else "High-RTO delivery pincode",
        "high_complaint_history": lambda tp, sd: "High complaint history",
        "negative_social_signals": lambda tp, sd: "Negative social signals",
        "brand_new_account": lambda tp, sd: "Brand new account",
        "high_rto_category": lambda tp, sd: f"High-RTO category ({sd.get('category_return_rate'):.0%})" if sd.get("category_return_rate") is not None else "High-RTO category",
    }

    # Map rule name to bitmask flag

    raw_score = 0.0
    triggered_factors: list[str] = []
    bitmask = 0

    for i, rule in enumerate(RISK_RULES):
        # Early exit: if score already >= 100, no need to evaluate more rules
        if raw_score >= 100.0:
            break

        if rule.condition(transaction_profile, signal_data):
            raw_score += rule.weight
            bitmask |= (1 << i)

            # Use dispatch dict for O(1) formatting
            formatter = formatters.get(rule.name.value)
            if formatter:
                triggered_factors.append(formatter(transaction_profile, signal_data))
            else:
                triggered_factors.append(rule.message_template)

    return raw_score, triggered_factors, bitmask


def _compute_recommendation(risk_score: float) -> str:
    """Deterministic recommendation based on risk score thresholds."""
    if risk_score <= THRESHOLDS.auto_approve_max:
        return "Auto-Approve"
    elif risk_score <= THRESHOLDS.manual_review_max:
        return "Manual Review"
    else:
        return "Auto-Reject"


def _generate_llm_narrative(
    risk_score: float,
    recommendation: str,
    triggered_factors: list[str],
    transaction_profile: dict[str, Any],
    signal_data: dict[str, Any],
    errors: list[str],
) -> str:
    """
    Generate LLM narrative using singleton Gemini client.
    Uses string.Template for safe prompt construction (prevents injection).
    Returns fallback narrative on any failure.
    """
    client = get_gemini_client()
    if client is None:
        return DEFAULT_NARRATIVE

    # Sanitize inputs for prompt - only include safe summary fields
    def _safe_summary(d: dict) -> str:
        """Extract only safe, non-PII fields for prompt."""
        safe_keys = {"return_rate", "recent_returns_30d", "total_orders", "account_age_days",
                     "order_value", "category", "payment_method", "pincode_rto_rate",
                     "complaint_score", "social_sentiment", "category_return_rate"}
        return "{" + ", ".join(f"{k}: {d[k]}" for k in safe_keys if k in d) + "}"

    safe_profile = _safe_summary(transaction_profile)
    safe_signals = _safe_summary(signal_data)

    # Use Template for safe prompt construction (prevents injection)
    prompt = Template(
        "DO NOT RECOMPUTE scores or invent new quantitative flags.\n"
        "Write 2–3 sentences explaining the risk assessment to a merchant.\n\n"
        "Computed Risk Score: $risk_score\n"
        "Recommendation: $recommendation\n"
        "Triggered Risk Factors: $factors\n"
        "Transaction Profile: $profile\n"
        "Signal Data: $signals\n"
    ).substitute(
        risk_score=risk_score,
        recommendation=recommendation,
        factors=', '.join(triggered_factors) if triggered_factors else 'None',
        profile=safe_profile,
        signals=safe_signals,
    )

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        if response and response.text and response.text.strip():
            return response.text.strip()

    except Exception as e:
        errors.append(f"LLM narrative generation failed: {str(e)}")

    return DEFAULT_NARRATIVE


DEFAULT_NARRATIVE = "Risk assessment based on transaction history and delivery signals."


def run_risk_agent(state: dict[str, Any]) -> dict[str, Any]:
    """
    Agent 3: Risk Scorer Agent
    Computes deterministic 0–100 risk score from transaction profile and signals.
    Pure Python rules — no LLM involvement in scoring.
    """
    transaction_profile = state.get("transaction_profile") or {}
    signal_data = state.get("signal_data") or {}
    errors = list(state.get("errors", []))

    # Extract order_value from state (request), NOT from profile
    # PRD: order_value is a critical input field from the request
    order_value = state.get("order_value")
    payment_method = state.get("payment_method")

    # Prepare evaluation data - merge profile + signals + request fields
    eval_profile = dict(transaction_profile)
    if order_value is not None:
        eval_profile["order_value"] = order_value
    if payment_method is not None:
        eval_profile["payment_method"] = payment_method

    # Evaluate all rules using registry
    raw_score, triggered_factors, triggered_bitmask = _evaluate_rules(eval_profile, signal_data)

    # Score calculation clamped to 100.0
    risk_score = min(THRESHOLDS.max_score, float(raw_score))

    # Deterministic recommendation
    recommendation = _compute_recommendation(risk_score)

    # LLM Narrative Generation (optional, never changes score)
    risk_narrative = _generate_llm_narrative(
        risk_score=risk_score,
        recommendation=recommendation,
        triggered_factors=triggered_factors,
        transaction_profile=transaction_profile,
        signal_data=signal_data,
        errors=[],
    )

    risk_data = {
        "risk_score": float(risk_score),
        "risk_factors": triggered_factors,
        "risk_narrative": risk_narrative,
        "recommendation": recommendation,
        # Optional: include bitmask for debugging/analytics
        "_triggered_bitmask": triggered_bitmask,
    }

    state["risk_data"] = risk_data
    state["errors"] = errors
    # confidence_score is explicitly preserved without docking (deterministic)

    return state
