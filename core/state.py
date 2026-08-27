"""
SystemState definitions for the RTO Risk Scorer pipeline.
Uses TypedDict for LangGraph compatibility with operator.add reducer for errors.
"""

from typing import TypedDict, Annotated, List
import operator
import time


class TransactionProfile(TypedDict, total=False):
    """Output from Agent 1: Transaction Profile Agent."""
    total_orders: int
    return_rate: float
    avg_order_value: float
    days_since_first_order: int
    recent_returns_30d: int
    order_value: float
    category: str
    payment_method: str
    delivery_pincode: str
    pincode_rto_rate: float
    account_age_days: int
    data_available: bool


class SignalData(TypedDict, total=False):
    """Output from Agent 2: Signal Agent."""
    pincode_rto_rate: float
    category_return_rate: float
    complaint_score: float
    social_sentiment: float
    recent_events: List[str]
    account_age_days: int
    signals_available: bool


class RiskData(TypedDict, total=False):
    """Output from Agent 3: Risk Scorer Agent."""
    risk_score: float
    risk_factors: List[str]
    risk_narrative: str
    recommendation: str


class ActionBrief(TypedDict, total=False):
    """Output from Agent 4: Synthesis Agent."""
    order_summary: str
    risk_assessment: str
    market_context: str
    mitigation_suggestions: List[str]
    key_concerns: List[str]
    recommended_action: str


class SystemState(TypedDict, total=False):
    """
    Single source of truth flowing through the LangGraph pipeline.
    Each agent reads/writes its namespace plus cross-cutting fields.
    """
    # Input fields (from API request)
    order_id: str
    customer_id: str
    order_value: float
    category: str
    payment_method: str
    delivery_pincode: str

    # Agent 1 output
    transaction_profile: TransactionProfile
    company_name: str

    # Agent 2 output
    signal_data: SignalData

    # Agent 3 output
    risk_data: RiskData

    # Agent 4 output
    action_brief: ActionBrief

    # Cross-cutting
    confidence_score: float
    errors: Annotated[List[str], operator.add]


def init_state(
    order_id: str,
    customer_id: str,
    order_value: float,
    category: str,
    payment_method: str,
    delivery_pincode: str,
) -> SystemState:
    """
    Factory: Creates a fresh SystemState with all defaults.
    Called once at the start of every pipeline run.
    """
    return {
        # Input
        "order_id": order_id,
        "customer_id": customer_id,
        "order_value": order_value,
        "category": category,
        "payment_method": payment_method,
        "delivery_pincode": delivery_pincode,

        # Agent 1 defaults
        "transaction_profile": {
            "total_orders": 0,
            "return_rate": 0.0,
            "avg_order_value": 0.0,
            "days_since_first_order": 0,
            "recent_returns_30d": 0,
            "order_value": order_value,
            "category": category,
            "payment_method": payment_method,
            "delivery_pincode": delivery_pincode,
            "pincode_rto_rate": 0.0,
            "account_age_days": 0,
            "data_available": False,
        },
        "company_name": "",

        # Agent 2 defaults
        "signal_data": {
            "pincode_rto_rate": 0.0,
            "category_return_rate": 0.0,
            "complaint_score": 0.0,
            "social_sentiment": 0.0,
            "recent_events": [],
            "account_age_days": 0,
            "signals_available": False,
        },

        # Agent 3 defaults
        "risk_data": {
            "risk_score": 50.0,
            "risk_factors": [],
            "risk_narrative": "Risk assessment pending.",
            "recommendation": "Manual Review",
        },

        # Agent 4 defaults
        "action_brief": {
            "order_summary": "Order analysis pending.",
            "risk_assessment": "Risk assessment pending.",
            "market_context": "Market context pending.",
            "mitigation_suggestions": [],
            "key_concerns": [],
            "recommended_action": "Manual Review",
        },

        # Cross-cutting
        "confidence_score": 1.0,
        "errors": [],
    }