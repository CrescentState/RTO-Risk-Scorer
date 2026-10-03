import os
from unittest.mock import MagicMock, patch

import pytest

from agents.synthesis_agent import run_synthesis_agent


@pytest.fixture
def base_state():
    return {
        "order_value": 8500.0,
        "payment_method": "cod",
        "category": "fashion",
        "confidence_score": 1.0,
        "errors": [],
        "transaction_profile": {
            "return_rate": 0.80,
            "recent_returns_30d": 4,
            "total_orders": 10,
            "account_age_days": 120,
        },
        "signal_data": {
            "pincode_rto_rate": 0.42,
            "complaint_score": 0.80,
            "social_sentiment": -0.50,
            "recent_events": ["High RTO pincode"],
        },
        "risk_data": {
            "risk_score": 85.0,
            "risk_factors": ["Serial returner", "COD high-value order"],
            "risk_narrative": "High risk profile.",
            "recommendation": "Auto-Reject",
        }
    }

# 1. Standard Recommendation Pass-Through
@pytest.mark.asyncio
async def test_synthesis_agent_standard_recommendation(base_state):
    res = await run_synthesis_agent(base_state)
    assert res["action_brief"]["recommended_action"] == "Auto-Reject"

# 2. Low Confidence Override (< 0.5 forces "Manual Review")
@pytest.mark.asyncio
async def test_synthesis_agent_low_confidence_override(base_state):
    base_state["confidence_score"] = 0.45
    base_state["risk_data"]["recommendation"] = "Auto-Reject"

    res = await run_synthesis_agent(base_state)
    # Must override Auto-Reject to Manual Review
    assert res["action_brief"]["recommended_action"] == "Manual Review"

# 3. Confidence Boundary Test (exact 0.50 retains risk recommendation)
@pytest.mark.asyncio
async def test_synthesis_agent_confidence_boundary(base_state):
    base_state["confidence_score"] = 0.50
    base_state["risk_data"]["recommendation"] = "Auto-Approve"

    res = await run_synthesis_agent(base_state)
    assert res["action_brief"]["recommended_action"] == "Auto-Approve"

# 4. Programmatic Correction of LLM Hallucinated Recommendation
@pytest.mark.asyncio
async def test_synthesis_agent_llm_hallucinated_label_correction(base_state):
    # Mock LLM returning a hallucinated recommendation field ("MUST SHIP IMMEDIATELY!!!")
    mock_llm_response = MagicMock()
    mock_llm_response.text = '''
    {
        "order_summary": "Summary text",
        "risk_assessment": "Risk assessment text",
        "market_context": "Market text",
        "mitigation_suggestions": ["Step 1"],
        "key_concerns": ["Concern 1"],
        "recommended_action": "MUST SHIP IMMEDIATELY!!!"
    }
    '''
    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}),
        patch("google.genai.Client") as mock_client,
    ):
        mock_client.return_value.models.generate_content.return_value = mock_llm_response
        res = await run_synthesis_agent(base_state)

        # Must overwrite hallucination with state's deterministic recommendation
        assert res["action_brief"]["recommended_action"] == "Auto-Reject"

# 5. Malformed JSON Fallback Handling
@pytest.mark.asyncio
async def test_synthesis_agent_malformed_json_fallback(base_state):
    mock_llm_response = MagicMock()
    mock_llm_response.text = "NOT_VALID_JSON_STRING"

    import core.clients
    import core.config
    original_client = core.clients._gemini_client
    core.config.settings.ENABLE_LLM_NARRATIVES = True
    core.clients._gemini_client = None  # Force re-initialization

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(text="NOT_VALID_JSON_STRING")

    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}),
        patch("agents.synthesis_agent.get_gemini_client", return_value=mock_client),
    ):
        try:
            res = await run_synthesis_agent(base_state)

            assert res["action_brief"]["order_summary"] == "Order analysis pending due to system error."
            assert res["action_brief"]["recommended_action"] == "Auto-Reject"
            assert any("Synthesis LLM error" in err for err in res["errors"])
        finally:
            core.config.settings.ENABLE_LLM_NARRATIVES = False
            core.clients._gemini_client = original_client

# 6. Fallback Payload Structure without API Key
@pytest.mark.asyncio
async def test_synthesis_agent_fallback_no_api_key(base_state):
    with patch.dict(os.environ, {}, clear=True):
        # Also clear cached client
        import core.clients
        original_client = core.clients._gemini_client
        original_warned = core.clients._gemini_warned
        core.clients._gemini_client = None
        core.clients._gemini_warned = False
        try:
            res = await run_synthesis_agent(base_state)
            brief = res["action_brief"]
            assert brief["order_summary"] == "Order analysis pending due to system error."
            assert brief["recommended_action"] == "Auto-Reject"
            assert isinstance(brief["mitigation_suggestions"], list)
        finally:
            core.clients._gemini_client = original_client
            core.clients._gemini_warned = original_warned

# 7. Error Accumulation & Preservation
@pytest.mark.asyncio
async def test_synthesis_agent_error_accumulation(base_state):
    base_state["errors"] = ["Upstream agent failure"]
    with patch.dict(os.environ, {}, clear=True):
        # Also patch the settings to have no API key
        import core.config
        original_key = core.config.settings.GEMINI_API_KEY
        # Also clear the cached client
        import core.clients
        original_client = core.clients._gemini_client
        original_warned = core.clients._gemini_warned
        core.config.settings.GEMINI_API_KEY = ""
        core.clients._gemini_client = None
        core.clients._gemini_warned = False
        try:
            res = await run_synthesis_agent(base_state)
            assert len(res["errors"]) == 1
            assert res["errors"][0] == "Upstream agent failure"
        finally:
            core.config.settings.GEMINI_API_KEY = original_key
            core.clients._gemini_client = original_client
            core.clients._gemini_warned = original_warned

# 8. None-Safety on Empty Input State
@pytest.mark.asyncio
async def test_synthesis_agent_none_safety():
    res = await run_synthesis_agent({})
    brief = res["action_brief"]
    assert brief["recommended_action"] == "Manual Review"  # Confidence default (1.0) with empty risk_data defaults to Manual Review
    assert brief["order_summary"] == "Order analysis pending due to system error."
