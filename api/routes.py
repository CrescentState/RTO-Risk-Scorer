import math
import time
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from agents.risk_agent import THRESHOLDS, compute_recommendation, evaluate_rules
from agents.signal_agent import DEFAULT_CATEGORY_RETURN_RATES, DEFAULT_CATEGORY_RTO_RATES
from core.orchestrator import run_pipeline_async
from core.orders import (
    check_order_fields_match,
    datasets_exist,
    first_order_for_customer,
    get_customer,
    get_order,
    get_signal,
    list_test_case_customers,
)

router = APIRouter()


def _conflict(code: str, message: str, mismatches: list[dict[str, Any]] | None = None) -> HTTPException:
    detail: dict[str, Any] = {"message": message, "code": code, "mismatches": mismatches or []}
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


class AnalyzeRequest(BaseModel):
    order_id: str = Field(..., pattern=r"^ORD_[0-9]{6}$")
    customer_id: str = Field(..., pattern=r"^CUST_[A-Z0-9_]{5,}$")
    order_value: float = Field(..., gt=0)
    category: str = Field(..., pattern=r"^(fashion|electronics|home|beauty)$")
    payment_method: str = Field(..., pattern=r"^(cod|upi|card|wallet)$")
    delivery_pincode: str = Field(..., pattern=r"^[0-9]{6}$")

    @field_validator("category", "payment_method", mode="before")
    @classmethod
    def normalize_lowercase(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("order_id", "customer_id", "delivery_pincode", mode="before")
    @classmethod
    def normalize_strip(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("order_value", mode="before")
    @classmethod
    def validate_order_value(cls, v: Any) -> float:
        if isinstance(v, str):
            v = v.strip()
        try:
            val = float(v)
            if not math.isfinite(val) or val <= 0:
                raise ValueError
            return val
        except (TypeError, ValueError):
            raise ValueError("order_value must be a positive finite number") from None


class RiskDataResponse(BaseModel):
    risk_score: float
    risk_factors: list[str] = []
    risk_narrative: str = ""
    recommendation: str = "Manual Review"


class AnalyzeResponse(BaseModel):
    order_id: str
    customer_id: str
    company_name: str = ""
    risk_score: float
    recommendation: str
    confidence_score: float
    risk_data: RiskDataResponse
    action_brief: dict[str, Any]
    audit_trail: list[str]
    processing_time_ms: int


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "RTO Risk Scorer"}


@router.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze_order(payload: AnalyzeRequest) -> AnalyzeResponse:
    if not datasets_exist():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Synthetic data not generated. Run: python -m synthetic_data.generator",
        )

    # Order-integrity gate: reject altered order details before any pipeline runs.
    customer = get_customer(payload.customer_id)
    if customer is None:
        raise _conflict("CUSTOMER_NOT_FOUND", f"Customer ID {payload.customer_id} not found in database")
    order_info = get_order(payload.order_id)
    if order_info is None:
        raise _conflict("ORDER_NOT_FOUND", f"Order ID {payload.order_id} not found in database")
    if order_info.get("customer_id") != payload.customer_id:
        raise _conflict(
            "CUSTOMER_MISMATCH",
            f"Order ID {payload.order_id} does not belong to customer {payload.customer_id}",
        )
    mismatches = check_order_fields_match(
        order_info,
        payload.order_value,
        payload.category,
        payload.payment_method,
        payload.delivery_pincode,
    )
    if mismatches:
        raise _conflict("ORDER_FIELD_MISMATCH", "Order details do not match the stored record", mismatches)

    start_time = time.perf_counter()

    try:
        final_state = await run_pipeline_async(
            order_id=payload.order_id,
            customer_id=payload.customer_id,
            order_value=payload.order_value,
            category=payload.category,
            payment_method=payload.payment_method,
            delivery_pincode=payload.delivery_pincode,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution error: {str(e)}",
        ) from e

    end_time = time.perf_counter()
    processing_time_ms = int((end_time - start_time) * 1000)

    raw_risk = final_state.get("risk_data") or {}
    action_brief: dict[str, Any] = dict(final_state.get("action_brief") or {})
    public_risk = RiskDataResponse(
        risk_score=float(raw_risk.get("risk_score", 0.0)),
        risk_factors=list(raw_risk.get("risk_factors", [])),
        risk_narrative=str(raw_risk.get("risk_narrative", "")),
        recommendation=str(raw_risk.get("recommendation", "Manual Review")),
    )

    return AnalyzeResponse(
        order_id=payload.order_id,
        customer_id=payload.customer_id,
        company_name=str(final_state.get("company_name", "")),
        risk_score=public_risk.risk_score,
        recommendation=str(action_brief.get("recommended_action", "Manual Review")),
        confidence_score=float(final_state.get("confidence_score", 0.0)),
        risk_data=public_risk,
        action_brief=action_brief,
        audit_trail=final_state.get("errors", []),
        processing_time_ms=processing_time_ms,
    )


@router.get("/api/v1/metrics")
async def get_metrics() -> dict[str, Any]:
    from evaluation.service import get_benchmark_metrics

    try:
        return await get_benchmark_metrics()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.get("/api/v1/benchmark")
async def get_benchmark_report() -> dict[str, Any]:
    from evaluation.service import get_benchmark_report as get_cached_benchmark_report

    try:
        return await get_cached_benchmark_report()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


class TestCaseResponse(BaseModel):
    customer_id: str
    company_name: str
    customer_type: str
    order_id: str
    pincode: str
    category: str
    payment_method: str
    order_value: float
    expected_risk_level: str


class VerifyOrderRequest(BaseModel):
    order_id: str = Field(..., pattern=r"^ORD_[0-9]{6}$")
    customer_id: str = Field(..., pattern=r"^CUST_[A-Z0-9_]{5,}$")

    @field_validator("order_id", "customer_id", mode="before")
    @classmethod
    def normalize_strip(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v


class VerifyOrderResponse(BaseModel):
    order_id: str
    customer_id: str
    order_value: float
    category: str
    payment_method: str
    pincode: str
    order_data: dict


@router.post("/api/v1/verify-order", response_model=VerifyOrderResponse)
async def verify_order(payload: VerifyOrderRequest) -> VerifyOrderResponse:
    """Verify that order_id and customer_id match in the database.
    Returns canonical order data if valid, raises 409 with a stable code otherwise."""
    if not datasets_exist():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Synthetic data not generated. Run: python -m synthetic_data.generator",
        )

    customer = get_customer(payload.customer_id)
    if customer is None:
        raise _conflict("CUSTOMER_NOT_FOUND", f"Customer ID {payload.customer_id} not found in database")

    order_info = get_order(payload.order_id)
    if order_info is None:
        raise _conflict("ORDER_NOT_FOUND", f"Order ID {payload.order_id} not found in database")

    if order_info.get("customer_id") != payload.customer_id:
        raise _conflict(
            "CUSTOMER_MISMATCH",
            f"Order ID {payload.order_id} does not belong to customer {payload.customer_id}",
        )

    # Return order data for step 2
    return VerifyOrderResponse(
        order_id=order_info["order_id"],
        customer_id=order_info["customer_id"],
        order_value=float(order_info["order_value"]),
        category=order_info["category"],
        payment_method=order_info["payment_method"],
        pincode=order_info["delivery_pincode"],
        order_data={
            "order_id": order_info["order_id"],
            "customer_id": order_info["customer_id"],
            "order_value": float(order_info["order_value"]),
            "category": order_info["category"],
            "payment_method": order_info["payment_method"],
            "pincode": order_info["delivery_pincode"],
        },
    )


@router.get("/api/v1/test-cases", response_model=list[TestCaseResponse])
async def get_test_cases() -> list[TestCaseResponse]:
    """Return predictable test cases for manual testing."""
    if not datasets_exist():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Synthetic data not generated. Run: python -m synthetic_data.generator",
        )

    # Build response with order details
    result = []
    for cust in list_test_case_customers():
        order_info = first_order_for_customer(cust["customer_id"])

        if order_info:
            # Compute expected risk level using shared rule evaluation logic
            # Build transaction profile and signal data dicts matching risk_agent.py expectations
            transaction_profile = {
                "return_rate": float(cust.get("return_rate", 0.0)),
                "recent_returns_30d": int(order_info.get("recent_returns_30d", 0)),
                "order_value": float(order_info["order_value"]),
                "total_orders": int(cust.get("total_orders", 0)),
                "account_age_days": int(cust.get("account_age_days", 0)),
                "payment_method": order_info["payment_method"],
            }
            category = order_info["category"]
            signal_data = {
                "pincode_rto_rate": DEFAULT_CATEGORY_RTO_RATES.get(category, 0.25),
                "category_return_rate": DEFAULT_CATEGORY_RETURN_RATES.get(category, 0.25),
                "complaint_score": 0.0,
                "social_sentiment": 0.0,
            }

            # Get signal data scoped to this exact order; never reuse another order's signals
            sig_row = get_signal(cust["customer_id"], order_info["order_id"])
            if sig_row is not None:
                signal_data["pincode_rto_rate"] = float(sig_row.get("pincode_rto_rate", DEFAULT_CATEGORY_RTO_RATES.get(category, 0.25)))
                signal_data["category_return_rate"] = float(sig_row.get("category_return_rate", DEFAULT_CATEGORY_RETURN_RATES.get(category, 0.25)))
                signal_data["complaint_score"] = float(sig_row.get("complaint_score", 0.0))
                signal_data["social_sentiment"] = float(sig_row.get("social_sentiment", 0.0))

            # Use shared rule evaluation
            raw_score, _, _ = evaluate_rules(transaction_profile, signal_data)
            score = min(THRESHOLDS.max_score, float(raw_score))

            expected = compute_recommendation(score)

            ct = cust["customer_type"]

            result.append(TestCaseResponse(
                customer_id=cust["customer_id"],
                company_name=cust["company_name"],
                customer_type=ct,
                order_id=order_info["order_id"],
                pincode=order_info["delivery_pincode"],
                category=order_info["category"],
                payment_method=order_info["payment_method"],
                order_value=float(order_info["order_value"]),
                expected_risk_level=expected,
            ))

    return result
