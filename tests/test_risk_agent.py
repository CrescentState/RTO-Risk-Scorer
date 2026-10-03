import os
from unittest.mock import MagicMock, patch

import pytest

from agents.risk_agent import run_risk_agent


@pytest.fixture
def base_state():
    return {
        "order_value": 1000.0,
        "payment_method": "upi",
        "category": "electronics",
        "confidence_score": 1.0,
        "errors": [],
        "transaction_profile": {
            "return_rate": 0.10,
            "recent_returns_30d": 1,
            "total_orders": 10,
            "account_age_days": 100,
            "avg_order_value": 1000.0,
            "order_value": 1000.0,
            "category": "electronics",
            "payment_method": "upi",
        },
        "signal_data": {
            "pincode_rto_rate": 0.15,
            "complaint_score": 0.10,
            "social_sentiment": 0.20,
            "category_return_rate": 0.18,
            "signals_available": True,
        }
    }

# 1. Base Score & Auto-Approve Verification
@pytest.mark.asyncio
async def test_risk_agent_clean_profile(base_state):
    res = await run_risk_agent(base_state)
    r_data = res["risk_data"]
    assert r_data["risk_score"] == 0.0
    assert r_data["risk_factors"] == []
    assert r_data["recommendation"] == "Auto-Approve"

# 2. Return Rate Boundary Testing (0.50 vs 0.501)
@pytest.mark.asyncio
async def test_risk_agent_return_rate_boundary(base_state):
    # Exclusive boundary 0.50 -> Should NOT trigger
    base_state["transaction_profile"]["return_rate"] = 0.50
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    # > 0.50 -> Triggers +30
    base_state["transaction_profile"]["return_rate"] = 0.501
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 30.0
    assert any("Serial returner" in factor for factor in res2["risk_data"]["risk_factors"])

# 3. Recent Returns 30d Boundary (3 vs 4)
@pytest.mark.asyncio
async def test_risk_agent_recent_returns_boundary(base_state):
    base_state["transaction_profile"]["recent_returns_30d"] = 3
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["transaction_profile"]["recent_returns_30d"] = 4
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 25.0

# 4. High-Value New Customer Boundary (10000 & total_orders 3 vs 2)
@pytest.mark.asyncio
async def test_risk_agent_high_value_new_customer(base_state):
    # Canonical order fields live on the transaction profile (no request override).
    base_state["order_value"] = 10000.0
    base_state["transaction_profile"]["order_value"] = 10000.0
    base_state["transaction_profile"]["total_orders"] = 2
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0  # order_value must be strictly > 10000

    base_state["order_value"] = 10001.0
    base_state["transaction_profile"]["order_value"] = 10001.0
    base_state["transaction_profile"]["total_orders"] = 3
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 0.0  # total_orders must be strictly < 3

    base_state["order_value"] = 10001.0
    base_state["transaction_profile"]["order_value"] = 10001.0
    base_state["transaction_profile"]["total_orders"] = 2
    res3 = await run_risk_agent(base_state)
    assert res3["risk_data"]["risk_score"] == 20.0

# 5. COD High-Value Order Boundary (5000 vs 5001)
@pytest.mark.asyncio
async def test_risk_agent_cod_high_value(base_state):
    base_state["payment_method"] = "cod"
    base_state["transaction_profile"]["payment_method"] = "cod"
    base_state["order_value"] = 5000.0
    base_state["transaction_profile"]["order_value"] = 5000.0
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["order_value"] = 5001.0
    base_state["transaction_profile"]["order_value"] = 5001.0
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 15.0

# 6. Pincode RTO Rate Boundary (0.35 vs 0.351)
@pytest.mark.asyncio
async def test_risk_agent_pincode_rto_boundary(base_state):
    base_state["signal_data"]["pincode_rto_rate"] = 0.35
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["signal_data"]["pincode_rto_rate"] = 0.351
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 15.0

# 7. Complaint Score Boundary (0.70 vs 0.701)
@pytest.mark.asyncio
async def test_risk_agent_complaint_score_boundary(base_state):
    base_state["signal_data"]["complaint_score"] = 0.70
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["signal_data"]["complaint_score"] = 0.701
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 15.0

# 8. Social Sentiment Boundary (-0.40 vs -0.401)
@pytest.mark.asyncio
async def test_risk_agent_social_sentiment_boundary(base_state):
    base_state["signal_data"]["social_sentiment"] = -0.40
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["signal_data"]["social_sentiment"] = -0.401
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 10.0

# 9. Brand New Account Boundary (7 vs 6 days)
@pytest.mark.asyncio
async def test_risk_agent_account_age_boundary(base_state):
    base_state["transaction_profile"]["account_age_days"] = 7
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["transaction_profile"]["account_age_days"] = 6
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 15.0

# 10. High-RTO Category Boundary (0.30 vs 0.301)
@pytest.mark.asyncio
async def test_risk_agent_category_return_rate_boundary(base_state):
    base_state["signal_data"]["category_return_rate"] = 0.30
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 0.0

    base_state["signal_data"]["category_return_rate"] = 0.301
    res2 = await run_risk_agent(base_state)
    assert res2["risk_data"]["risk_score"] == 10.0

# 11. Score Cap at 100.0 & Recommendation Rules
@pytest.mark.asyncio
async def test_risk_agent_score_clamping_and_recommendation(base_state):
    # Trigger multiple heavy rules to exceed 100
    base_state["transaction_profile"]["return_rate"] = 0.80       # +30
    base_state["transaction_profile"]["recent_returns_30d"] = 5    # +25
    base_state["order_value"] = 15000.0
    base_state["transaction_profile"]["order_value"] = 15000.0
    base_state["payment_method"] = "cod"                           # +15 (COD high)
    base_state["transaction_profile"]["payment_method"] = "cod"
    base_state["transaction_profile"]["total_orders"] = 1         # +20 (High value new)
    base_state["signal_data"]["pincode_rto_rate"] = 0.50          # +15
    base_state["signal_data"]["complaint_score"] = 0.90           # +15

    # Total sum = 30 + 25 + 15 + 20 + 15 + 15 = 120 -> Clamped to 100.0
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 100.0
    assert res["risk_data"]["recommendation"] == "Auto-Reject"

# 12. Manual Review Recommendation Threshold (25 < score <= 60)
@pytest.mark.asyncio
async def test_risk_agent_manual_review_threshold(base_state):
    base_state["transaction_profile"]["return_rate"] = 0.60  # +30
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 30.0
    assert res["risk_data"]["recommendation"] == "Manual Review"

# 13. Auto-Approve Upper Threshold (score <= 25)
@pytest.mark.asyncio
async def test_risk_agent_auto_approve_upper_boundary(base_state):
    base_state["transaction_profile"]["recent_returns_30d"] = 4  # +25
    res = await run_risk_agent(base_state)
    assert res["risk_data"]["risk_score"] == 25.0
    assert res["risk_data"]["recommendation"] == "Auto-Approve"

# 14. None-Safety on Missing Nested Profiles
@pytest.mark.asyncio
async def test_risk_agent_none_safety():
    res = await run_risk_agent({})
    assert res["risk_data"]["risk_score"] == 0.0
    assert res["risk_data"]["risk_factors"] == []
    assert res["risk_data"]["recommendation"] == "Auto-Approve"

# 15. Partial None-Safety inside Profiles
@pytest.mark.asyncio
async def test_risk_agent_partial_none_fields():
    state = {
        "transaction_profile": {
            "return_rate": None,
            "recent_returns_30d": None,
            "total_orders": None,
        },
        "signal_data": {
            "pincode_rto_rate": None,
            "complaint_score": None,
        }
    }
    res = await run_risk_agent(state)
    assert res["risk_data"]["risk_score"] == 0.0

# 16. Error Preservation Through Pipeline
@pytest.mark.asyncio
async def test_risk_agent_preserves_errors(base_state):
    base_state["errors"] = ["Prior agent failure"]
    res = await run_risk_agent(base_state)
    assert "Prior agent failure" in res["errors"]

# 17. LLM Narrative Fallback on Missing Key / Exception
@pytest.mark.asyncio
async def test_risk_agent_llm_fallback_narrative(base_state):
    with patch.dict(os.environ, {}, clear=True):
        # Also clear the singleton client
        import core.clients
        original_client = core.clients._gemini_client
        core.clients._gemini_client = None
        try:
            res = await run_risk_agent(base_state)
            assert res["risk_data"]["risk_narrative"] == "Risk assessment based on transaction history and delivery signals."
        finally:
            core.clients._gemini_client = original_client

# 18. Successful LLM Narrative Generation
@pytest.mark.asyncio
async def test_risk_agent_llm_narrative_success(base_state):
    base_state["transaction_profile"]["return_rate"] = 0.60
    mock_response = MagicMock()
    mock_response.text = "Customer exhibits a high return rate. Caution is advised for high-value orders."

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        # Mock the singleton client getter and enable LLM narratives
        import core.clients
        import core.config
        original_client = core.clients._gemini_client
        original_llm_setting = core.config.settings.ENABLE_LLM_NARRATIVES
        core.config.settings.ENABLE_LLM_NARRATIVES = True
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        core.clients._gemini_client = mock_client
        try:
            res = await run_risk_agent(base_state)
            assert res["risk_data"]["risk_narrative"] == "Customer exhibits a high return rate. Caution is advised for high-value orders."
            assert res["risk_data"]["risk_score"] == 30.0  # Scores remain strictly deterministic
        finally:
            core.clients._gemini_client = original_client
            core.config.settings.ENABLE_LLM_NARRATIVES = original_llm_setting
