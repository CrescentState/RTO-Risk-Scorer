import os
from unittest.mock import patch

import pandas as pd
import pytest

from agents.profile_agent import run_profile_agent
from core.cache import clear_cache, get_cached_response, set_cached_response
from synthetic_data.generator import generate_dataset, load_customers

# ---------------------------------------------------------------------------
# Test Setup & Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def setup_synthetic_data():
    """Ensure synthetic data exists before running tests."""
    os.makedirs("synthetic_data", exist_ok=True)
    generate_dataset(num_customers=50)

@pytest.fixture(autouse=True)
def clear_cache_fixture():
    """Clear cache before each test to prevent cross-test contamination."""
    clear_cache()
    yield
    clear_cache()

@pytest.fixture
def test_customer_id():
    """Get a valid customer ID from generated data."""
    customers = load_customers()
    return customers[0]["customer_id"] if customers else "CUST_00001"

@pytest.fixture
def base_state(test_customer_id):
    return {
        "order_id": "ORD_000001",
        "customer_id": test_customer_id,
        "order_value": 4500.0,
        "category": "fashion",
        "payment_method": "cod",
        "delivery_pincode": "560001",
        "confidence_score": 1.0,
        "errors": []
    }

# ---------------------------------------------------------------------------
# 1. Successful Data Retrieval & Schema Verification
# ---------------------------------------------------------------------------

def test_profile_agent_success(base_state):
    res = run_profile_agent(base_state)

    profile = res["transaction_profile"]
    assert profile["data_available"] is True
    assert res["confidence_score"] >= 0.95  # May be docked 0.05 for missing pincode_rto_rate
    assert "company_name" in res
    assert res["company_name"].startswith("Customer_")
    assert profile["order_value"] == 4500.0  # From request, not CSV
    assert profile["category"] == "fashion"

def test_profile_agent_derived_fields(base_state):
    res = run_profile_agent(base_state)
    profile = res["transaction_profile"]

    assert "total_orders" in profile
    assert "return_rate" in profile
    assert "avg_order_value" in profile
    assert "days_since_first_order" in profile
    assert "recent_returns_30d" in profile
    assert "pincode_rto_rate" in profile

# ---------------------------------------------------------------------------
# 2. Cache Behavior (Hit, Miss, TTL, Atomic Read)
# ---------------------------------------------------------------------------

def test_profile_agent_cache_hit(base_state):
    cache_key = f"{base_state['customer_id']}_profile"
    mock_cached_profile = {
        "total_orders": 99,
        "return_rate": 0.05,
        "avg_order_value": 1200.0,
        "days_since_first_order": 500,
        "recent_returns_30d": 0,
        "order_value": 4500.0,
        "category": "fashion",
        "payment_method": "cod",
        "delivery_pincode": "560001",
        "pincode_rto_rate": 0.1,
        "account_age_days": 500,
        "data_available": True,
        "company_name": "Cached Merchant"
    }
    clear_cache()
    set_cached_response(cache_key, mock_cached_profile)

    res = run_profile_agent(base_state)
    assert res["transaction_profile"]["total_orders"] == 99
    assert res["company_name"] == "Cached Merchant"
    clear_cache()

def test_profile_agent_cache_miss_queries_db(base_state):
    base_state["customer_id"] = "CUST_00002"
    cache_key = "CUST_00002_profile"

    clear_cache()
    res = run_profile_agent(base_state)
    assert res["transaction_profile"]["data_available"] is True
    assert get_cached_response(cache_key) is not None
    clear_cache()

# ---------------------------------------------------------------------------
# 3. Invalid Customer & Missing Critical Fields (-0.4 Docking)
# ---------------------------------------------------------------------------

def test_profile_agent_invalid_customer_id(base_state):
    base_state["customer_id"] = "CUST_99999"  # Non-existent

    res = run_profile_agent(base_state)
    assert res["transaction_profile"]["data_available"] is False
    assert res["confidence_score"] == 0.6  # 1.0 - 0.4
    assert len(res["errors"]) == 1
    assert "Invalid customer_id" in res["errors"][0]

def test_profile_agent_missing_critical_order_value():
    # Test with order_value = None in a minimal state
    state = {
        "order_id": "ORD_000001",
        "customer_id": "CUST_99999",
        "order_value": None,
        "category": "fashion",
        "payment_method": "cod",
        "delivery_pincode": "560001",
        "confidence_score": 1.0,
        "errors": []
    }

    res = run_profile_agent(state)
    assert res["transaction_profile"]["data_available"] is False
    assert res["confidence_score"] == 0.6  # Docked 0.4 for missing critical field

# ---------------------------------------------------------------------------
# 4. Missing Secondary Fields (-0.05 Docking Each)
# ---------------------------------------------------------------------------

def test_profile_agent_missing_secondary_pincode_rate(base_state):

    # Mock the internal cached functions
    with patch("agents.profile_agent._load_customers_df") as mock_cust, \
         patch("agents.profile_agent._load_orders_df") as mock_orders:

        cust_df = pd.DataFrame([{
            "customer_id": base_state["customer_id"],
            "total_orders": 10,
            "return_rate": 0.1,
            "avg_order_value": 1000.0,
            "account_age_days": 100,
            "recent_returns_30d": 1,
            "company_name": "Test Cust"
        }])
        mock_cust.return_value = cust_df
        mock_orders.return_value = pd.DataFrame()

        res = run_profile_agent(base_state)
        # 1.0 - 0.05 (missing pincode_rto_rate) = 0.95
        assert res["confidence_score"] == 0.95
        assert res["transaction_profile"]["pincode_rto_rate"] == 0.0

def test_profile_agent_missing_secondary_account_age(base_state):

    with patch("agents.profile_agent._load_customers_df") as mock_cust, \
         patch("agents.profile_agent._load_orders_df") as mock_orders:

        cust_df = pd.DataFrame([{
            "customer_id": base_state["customer_id"],
            "total_orders": 10,
            "return_rate": 0.1,
            "avg_order_value": 1000.0,
            "account_age_days": None,  # Missing secondary
            "recent_returns_30d": 1,
            "company_name": "Test Cust"
        }])
        mock_cust.return_value = cust_df
        mock_orders.return_value = pd.DataFrame()

        res = run_profile_agent(base_state)
        # 1.0 - 0.05 (missing account_age) - 0.05 (missing pincode_rto) = 0.90
        assert round(res["confidence_score"], 2) == 0.90
        assert res["transaction_profile"]["account_age_days"] == 0

# ---------------------------------------------------------------------------
# 5. DB Fallback & Corruption (-0.3 Docking)
# ---------------------------------------------------------------------------

def test_profile_agent_db_exception_fallback(base_state):
    base_state["customer_id"] = "CUST_NOCACHE"

    with patch("agents.profile_agent._load_customers_df", side_effect=Exception("Database connection timeout")):
        res = run_profile_agent(base_state)

        assert res["transaction_profile"]["data_available"] is False
        assert res["confidence_score"] == 0.7  # 1.0 - 0.3
        assert any("Database error" in err for err in res["errors"])

# ---------------------------------------------------------------------------
# 6. Cumulative Confidence Docking & Clamping [0.0, 1.0]
# ---------------------------------------------------------------------------

def test_profile_agent_confidence_clamping_low(base_state):
    base_state["confidence_score"] = 0.2
    base_state["customer_id"] = "CUST_99999"  # Missing customer (-0.4)

    res = run_profile_agent(base_state)
    # 0.2 - 0.4 = -0.2 -> clamped to 0.0
    assert res["confidence_score"] == 0.0

def test_profile_agent_confidence_clamping_high():
    # Test with a unique customer ID to avoid cache
    state = {
        "order_id": "ORD_000001",
        "customer_id": "CUST_CLAMP_HIGH",
        "order_value": 4500.0,
        "category": "fashion",
        "payment_method": "cod",
        "delivery_pincode": "560001",
        "confidence_score": 1.5,  # Malformed incoming state > 1.0
        "errors": []
    }

    res = run_profile_agent(state)
    # Should be clamped to 1.0
    assert res["confidence_score"] == 1.0

# ---------------------------------------------------------------------------
# 7. Error Accumulation Pattern
# ---------------------------------------------------------------------------

def test_profile_agent_error_accumulation(base_state):
    base_state["errors"] = ["Prior agent error: Validation warning"]
    base_state["customer_id"] = "CUST_99999"

    res = run_profile_agent(base_state)
    assert len(res["errors"]) == 2
    assert res["errors"][0] == "Prior agent error: Validation warning"
    assert "Invalid customer_id" in res["errors"][1]

# ---------------------------------------------------------------------------
# 8. None-Safety Tests
# ---------------------------------------------------------------------------

def test_profile_agent_none_inputs_safety():
    empty_state = {
        "order_id": None,
        "customer_id": None,
        "order_value": None,
        "category": None,
        "payment_method": None,
        "delivery_pincode": None,
        "confidence_score": 1.0,
        "errors": []
    }

    # Must not crash, should return safely degraded profile
    res = run_profile_agent(empty_state)
    assert res["transaction_profile"]["data_available"] is False
    assert res["confidence_score"] == 0.6  # Docked for missing critical fields
    assert isinstance(res["errors"], list)

def test_profile_agent_empty_dict_state():
    # Extreme edge case: bare empty dict
    res = run_profile_agent({})
    assert "transaction_profile" in res
    assert res["transaction_profile"]["data_available"] is False
    assert res["confidence_score"] == 0.6
