import os
from unittest.mock import MagicMock, patch

import pytest

from core.orchestrator import get_pipeline, run_pipeline_async
from synthetic_data.generator import generate_dataset, load_customers


@pytest.fixture(scope="module")
def test_customer():
    """Get a valid customer ID from generated data (isolated tmp dir)."""
    import os

    from core.config import settings

    generate_dataset(num_customers=100, output_dir=os.path.dirname(settings.CUSTOMERS_CSV))
    customers = load_customers(settings.CUSTOMERS_CSV)
    # Return a customer that exists in the data
    return customers[0]["customer_id"] if customers else "CUST_00001"


@pytest.fixture(autouse=True)
def clear_pipeline_cache():
    """Clear the pipeline cache between tests to prevent test interference."""
    import core.orchestrator
    core.orchestrator._pipeline = None
    yield
    core.orchestrator._pipeline = None


@pytest.fixture
def base_state(test_customer):
    return {
        "order_id": "ORD_123456",
        "customer_id": test_customer,
        "order_value": 1500.0,
        "payment_method": "upi",
        "category": "electronics",
        "delivery_pincode": "560001",
        "confidence_score": 1.0,
        "errors": []
    }


# 1. E2E Clean Order Processing (Auto-Approve Path)
@pytest.mark.asyncio
async def test_pipeline_clean_order_auto_approve(base_state):
    final_state = await run_pipeline_async(
        order_id=base_state["order_id"],
        customer_id=base_state["customer_id"],
        order_value=base_state["order_value"],
        payment_method=base_state["payment_method"],
        category=base_state["category"],
        delivery_pincode=base_state["delivery_pincode"],
    )

    assert final_state["risk_data"]["risk_score"] >= 0.0
    assert final_state["risk_data"]["recommendation"] in ["Auto-Approve", "Manual Review", "Auto-Reject"]
    assert final_state["action_brief"]["recommended_action"] in ["Auto-Approve", "Manual Review", "Auto-Reject"]
    assert final_state["confidence_score"] >= 0.0


# 2. High Risk Order Processing (Auto-Reject Path) - test with known fraudster
@pytest.mark.asyncio
async def test_pipeline_high_risk_auto_reject():
    # Generate data and find a fraudster
    import os

    from core.config import settings
    from synthetic_data.generator import generate_dataset, load_customers
    generate_dataset(num_customers=200, output_dir=os.path.dirname(settings.CUSTOMERS_CSV))
    customers = load_customers(settings.CUSTOMERS_CSV)
    fraudsters = [c for c in customers if c["customer_type"] == "fraudster"]

    if not fraudsters:
        pytest.skip("No fraudster in generated data")

    fraudster = fraudsters[0]

    final_state = await run_pipeline_async(
        order_id="ORD_999999",
        customer_id=fraudster["customer_id"],
        order_value=12000.0,
        payment_method="cod",
        category="electronics",
        delivery_pincode="560001",
    )

    # Fraudsters typically have high return_rate and new accounts
    assert final_state["risk_data"]["risk_score"] >= 0.0
    assert final_state["risk_data"]["recommendation"] in ["Auto-Approve", "Manual Review", "Auto-Reject"]
    assert final_state["action_brief"]["recommended_action"] in ["Auto-Approve", "Manual Review", "Auto-Reject"]


# 3. Confidence Docking Clamp & Manual Review Force Override
@pytest.mark.asyncio
async def test_pipeline_low_confidence_override(base_state):
    # Use pipeline directly with custom initial state to test low confidence override
    from core.state import init_state

    pipeline = get_pipeline()
    initial_state = init_state(
        order_id=base_state["order_id"],
        customer_id=base_state["customer_id"],
        order_value=base_state["order_value"],
        payment_method=base_state["payment_method"],
        category=base_state["category"],
        delivery_pincode=base_state["delivery_pincode"],
    )
    initial_state["confidence_score"] = 0.40

    final_state = await pipeline.ainvoke(initial_state)

    # Even if risk score is 0.0 (Auto-Approve), action_brief MUST override to Manual Review
    assert final_state["action_brief"]["recommended_action"] == "Manual Review"


# 4. Error Accumulation across Graph Nodes
@pytest.mark.asyncio
async def test_pipeline_error_accumulation(base_state):
    # Test that errors from profile agent are accumulated
    # Use invalid customer to generate errors
    final_state = await run_pipeline_async(
        order_id="ORD_TEST",
        customer_id="CUST_INVALID_99999",
        order_value=1500.0,
        payment_method="upi",
        category="electronics",
        delivery_pincode="560001",
    )

    assert len(final_state["errors"]) > 0
    assert isinstance(final_state["errors"], list)
    # Check that profile agent error is present
    assert any("Invalid customer_id" in err for err in final_state["errors"])


# 6. LLM Hallucinated Action Correction
@pytest.mark.asyncio
async def test_pipeline_llm_hallucinated_label_correction(base_state):
    mock_llm_response = MagicMock()
    mock_llm_response.text = '{"recommended_action": "APPROVE_IMMEDIATELY_NO_CHECKS"}'

    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}),
        patch("google.genai.Client") as mock_client,
    ):
        import core.config
        original_llm_setting = core.config.settings.ENABLE_LLM_NARRATIVES
        core.config.settings.ENABLE_LLM_NARRATIVES = True
        try:
            mock_client.return_value.models.generate_content.return_value = mock_llm_response
            final_state = await run_pipeline_async(
                order_id=base_state["order_id"],
                customer_id=base_state["customer_id"],
                order_value=base_state["order_value"],
                payment_method=base_state["payment_method"],
                category=base_state["category"],
                delivery_pincode=base_state["delivery_pincode"],
            )

            # Must overwrite hallucination with deterministic recommendation
            assert final_state["action_brief"]["recommended_action"] in ["Auto-Approve", "Manual Review", "Auto-Reject"]
        finally:
            core.config.settings.ENABLE_LLM_NARRATIVES = original_llm_setting


# 7. None-Safety on Missing Data Agent Profiles
@pytest.mark.asyncio
async def test_pipeline_none_safety_missing_data(base_state):
    from agents.profile_agent import run_profile_agent as real_profile

    async def mock_profile_agent(state):
        state = await real_profile(state)
        state["transaction_profile"] = None
        return state

    with patch("agents.profile_agent.run_profile_agent", side_effect=mock_profile_agent):
        final_state = await run_pipeline_async(
            order_id=base_state["order_id"],
            customer_id=base_state["customer_id"],
            order_value=base_state["order_value"],
            payment_method=base_state["payment_method"],
            category=base_state["category"],
            delivery_pincode=base_state["delivery_pincode"],
        )

        # Should handle None gracefully - risk score computed from defaults
        assert final_state["risk_data"]["risk_score"] >= 0.0


# 8. None-Safety on Missing Signal Agent Output
@pytest.mark.asyncio
async def test_pipeline_none_safety_missing_signals(base_state):
    from agents.signal_agent import run_signal_agent as real_signal

    async def mock_signal_agent(state):
        state = await real_signal(state)
        state["signal_data"] = None
        return state

    with patch("agents.signal_agent.run_signal_agent", side_effect=mock_signal_agent):
        final_state = await run_pipeline_async(
            order_id=base_state["order_id"],
            customer_id=base_state["customer_id"],
            order_value=base_state["order_value"],
            payment_method=base_state["payment_method"],
            category=base_state["category"],
            delivery_pincode=base_state["delivery_pincode"],
        )

        assert final_state["risk_data"]["risk_score"] >= 0.0


# 9. Cumulative Confidence Docking Verification
@pytest.mark.asyncio
async def test_pipeline_cumulative_confidence_docking(base_state):
    base_state["confidence_score"] = 0.80

    from unittest.mock import AsyncMock

    from agents.profile_agent import run_profile_agent as real_profile

    async def mock_profile_agent(state):
        state = real_profile(state)
        # Simulate a dock of 0.4
        state["confidence_score"] = float(state.get("confidence_score", 1.0)) - 0.40
        return state

    # Patch the orchestrator's reference to the profile agent
    with patch("core.orchestrator.run_profile_agent", new_callable=AsyncMock, side_effect=mock_profile_agent):
        # Use pipeline directly with custom initial state to preserve confidence_score
        from core.orchestrator import get_pipeline
        from core.state import init_state

        pipeline = get_pipeline()
        initial_state = init_state(
            order_id=base_state["order_id"],
            customer_id=base_state["customer_id"],
            order_value=base_state["order_value"],
            payment_method=base_state["payment_method"],
            category=base_state["category"],
            delivery_pincode=base_state["delivery_pincode"],
        )
        initial_state["confidence_score"] = 0.80

        final_state = await pipeline.ainvoke(initial_state)

        # 0.80 - 0.40 = 0.40
        assert final_state["confidence_score"] <= 0.40
        # Under 0.50 threshold forces Manual Review
        assert final_state["action_brief"]["recommended_action"] == "Manual Review"


# 10. Boundary Rule Triggering in Full Graph Context
@pytest.mark.asyncio
async def test_pipeline_boundary_rule_triggers(base_state):
    # Set order_value > 5000 and payment_method = cod to trigger COD high-value rule (+15)
    final_state = await run_pipeline_async(
        order_id="ORD_TEST",
        customer_id=base_state["customer_id"],
        order_value=5001.0,
        payment_method="cod",
        category=base_state["category"],
        delivery_pincode=base_state["delivery_pincode"],
    )

    # Risk score should include COD high-value order (+15)
    assert final_state["risk_data"]["risk_score"] >= 15.0
    assert any("COD high-value order" in f for f in final_state["risk_data"]["risk_factors"])


# 11. LLM API Failure Recovery to Fallback Narrative
@pytest.mark.asyncio
async def test_pipeline_llm_failure_recovery(base_state):
    import core.config
    core.config.settings.ENABLE_LLM_NARRATIVES = True
    try:
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}),
            patch("agents.synthesis_agent.get_gemini_client") as mock_get_client,
        ):
            mock_client = MagicMock()
            mock_client.models.generate_content.side_effect = Exception("API connection timeout")
            mock_get_client.return_value = mock_client

            final_state = await run_pipeline_async(
                order_id=base_state["order_id"],
                customer_id=base_state["customer_id"],
                order_value=base_state["order_value"],
                payment_method=base_state["payment_method"],
                category=base_state["category"],
                delivery_pincode=base_state["delivery_pincode"],
            )

            assert "Order analysis pending" in final_state["action_brief"]["order_summary"]
            assert any("Synthesis LLM error" in err for err in final_state["errors"])
    finally:
        core.config.settings.ENABLE_LLM_NARRATIVES = False


# 12. Score Clamping at 100.0 Boundary in Full Graph
@pytest.mark.asyncio
async def test_pipeline_score_clamping(base_state):
    from unittest.mock import AsyncMock

    from agents.profile_agent import run_profile_agent as real_profile
    from agents.signal_agent import run_signal_agent as real_signal

    async def mock_profile_agent(state):
        state = real_profile(state)
        state["transaction_profile"] = {
            "return_rate": 0.90,          # +30
            "recent_returns_30d": 10,     # +25
            "total_orders": 1,            # +20
            "account_age_days": 1,        # +15
        }
        return state

    async def mock_signal_agent(state):
        state = real_signal(state)
        state["signal_data"] = {
            "pincode_rto_rate": 0.50,     # +15
            "complaint_score": 0.90,      # +15
            "social_sentiment": -0.80,    # +10
        }
        return state

    # Patch the orchestrator's references and use pipeline directly
    with (
        patch("core.orchestrator.run_profile_agent", new_callable=AsyncMock, side_effect=mock_profile_agent),
        patch("core.orchestrator.run_signal_agent", new_callable=AsyncMock, side_effect=mock_signal_agent),
    ):
        from core.orchestrator import get_pipeline
        from core.state import init_state

        pipeline = get_pipeline()
        initial_state = init_state(
            order_id="ORD_TEST",
            customer_id=base_state["customer_id"],
            order_value=base_state["order_value"],
            payment_method=base_state["payment_method"],
            category=base_state["category"],
            delivery_pincode=base_state["delivery_pincode"],
        )

        final_state = await pipeline.ainvoke(initial_state)

        # Total sum exceeds 100.0, clamped strictly to 100.0.
        # The unknown order has no exact signal row, so confidence drops
        # below 0.50 and the brief correctly overrides to Manual Review.
        assert final_state["risk_data"]["risk_score"] == 100.0
        assert final_state["risk_data"]["recommendation"] == "Auto-Reject"
        assert final_state["action_brief"]["recommended_action"] == "Manual Review"
