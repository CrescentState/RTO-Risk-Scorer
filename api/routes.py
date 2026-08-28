import time
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.orchestrator import run_pipeline_async
from evaluation.metrics import compute_benchmark_metrics

router = APIRouter()


class AnalyzeRequest(BaseModel):
    order_id: str = Field(..., pattern=r"^ORD_[0-9]{6}$")
    customer_id: str = Field(..., pattern=r"^CUST_[0-9]{5}$")
    order_value: float = Field(..., gt=0)
    category: str = Field(..., pattern=r"^(fashion|electronics|home|beauty)$")
    payment_method: str = Field(..., pattern=r"^(cod|upi|card|wallet)$")
    delivery_pincode: str = Field(..., pattern=r"^[0-9]{6}$")


class AnalyzeResponse(BaseModel):
    order_id: str
    customer_id: str
    risk_score: float
    recommendation: str
    confidence_score: float
    action_brief: Dict[str, Any]
    audit_trail: List[str]
    processing_time_ms: int


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "RTO Risk Scorer"}


@router.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze_order(payload: AnalyzeRequest) -> AnalyzeResponse:
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
        )

    end_time = time.perf_counter()
    processing_time_ms = int((end_time - start_time) * 1000)

    risk_data = final_state.get("risk_data") or {}
    action_brief = final_state.get("action_brief") or {}

    return AnalyzeResponse(
        order_id=payload.order_id,
        customer_id=payload.customer_id,
        risk_score=float(risk_data.get("risk_score", 0.0)),
        recommendation=str(action_brief.get("recommended_action", "Manual Review")),
        confidence_score=float(final_state.get("confidence_score", 0.0)),
        action_brief=action_brief,
        audit_trail=final_state.get("errors", []),
        processing_time_ms=processing_time_ms,
    )


@router.get("/api/v1/metrics")
async def get_metrics() -> Dict[str, Any]:
    metrics_data = compute_benchmark_metrics()
    return {
        "precision": metrics_data["precision"],
        "recall": metrics_data["recall"],
        "f1_score": metrics_data["f1_score"],
        "false_positive_rate": metrics_data["false_positive_rate"],
        "auto_approval_rate": metrics_data["auto_approval_rate"],
        "estimated_money_saved_inr": metrics_data["estimated_money_saved_inr"],
    }


@router.get("/api/v1/benchmark")
async def get_benchmark_report() -> Dict[str, Any]:
    from evaluation.benchmark import run_benchmark
    return run_benchmark()