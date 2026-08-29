import csv
import os
from unittest.mock import patch

import pytest

from agents.signal_agent import run_signal_agent
from core.cache import clear_cache, get_cached_response, set_cached_response

TEST_SIGNALS_CSV = "synthetic_data/signals.csv"

@pytest.fixture(autouse=True)
def setup_teardown_csv():
    """Setup a controlled synthetic signal database for reproducible unit testing."""
    os.makedirs("synthetic_data", exist_ok=True)
    clear_cache()

    headers = [
        "customer_id", "order_id", "delivery_pincode", "pincode_rto_rate",
        "category_return_rate", "complaint_score", "social_sentiment",
        "recent_events", "account_age_days"
    ]
    rows = [
        ["CUST_00001", "ORD_0001", "110001", "0.15", "0.35", "0.20", "0.40", "None", "100"],
        ["CUST_00002", "ORD_0002", "700002", "0.50", "0.18", "0.85", "-0.50", "High RTO pincode|Negative social mentions", "45"],
        ["CUST_00003", "ORD_0003", "560001", "0.35", "0.22", "0.70", "-0.40", "None", "10"],
        ["CUST_00004", "ORD_0004", "110002", "0.22", "0.28", "0.10", "0.10", "None", "120"],
    ]

    with open(TEST_SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    yield

@pytest.fixture
def base_state():
    return {
        "company_name": "Customer_CUST_00001",
        "customer_id": "CUST_00001",
        "delivery_pincode": "110001",
        "category": "fashion",
        "confidence_score": 1.0,
        "errors": [],
        "transaction_profile": {
            "account_age_days": 100
        }
    }

# 1. Standard Signal Data Retrieval
def test_signal_agent_success(base_state):
    res = run_signal_agent(base_state)
    sig = res["signal_data"]
    assert sig["signals_available"] is True
    assert sig["pincode_rto_rate"] == 0.15
    assert sig["category_return_rate"] == 0.35
    assert sig["complaint_score"] == 0.20
    assert sig["social_sentiment"] == 0.40
    assert sig["recent_events"] == ["None"]
    assert res["confidence_score"] == 1.0

# 2. Parsing Pipe-Separated Events
def test_signal_agent_parse_multiple_events(base_state):
    base_state["customer_id"] = "CUST_00002"
    base_state["delivery_pincode"] = "700002"
    res = run_signal_agent(base_state)
    sig = res["signal_data"]
    assert sig["recent_events"] == ["High RTO pincode", "Negative social mentions"]

# 3. Cache Hit Execution Path
def test_signal_agent_cache_hit(base_state):
    cache_key = f"{base_state['customer_id']}_{base_state['delivery_pincode']}_signals"
    cached_payload = {
        "pincode_rto_rate": 0.10,
        "category_return_rate": 0.20,
        "complaint_score": 0.05,
        "social_sentiment": 0.90,
        "recent_events": ["Festive season"],
        "account_age_days": 100,
        "signals_available": True
    }
    set_cached_response(cache_key, cached_payload)

    res = run_signal_agent(base_state)
    assert res["signal_data"]["social_sentiment"] == 0.90
    assert res["signal_data"]["recent_events"] == ["Festive season"]

# 4. Cache Miss Handling
def test_signal_agent_cache_miss(base_state):
    cache_key = f"{base_state['customer_id']}_{base_state['delivery_pincode']}_signals"
    assert get_cached_response(cache_key) is None
    res = run_signal_agent(base_state)
    assert res["signal_data"]["signals_available"] is True
    assert get_cached_response(cache_key) is not None

# 5. Missing Signals (-0.1 Docking)
def test_signal_agent_missing_customer(base_state):
    base_state["customer_id"] = "CUST_99999"
    res = run_signal_agent(base_state)
    assert res["signal_data"]["signals_available"] is False
    assert res["confidence_score"] == 0.9
    assert any("No external signals found" in err for err in res["errors"])

# 6. Fail-Open Pincode Rate Fallback
def test_signal_agent_fail_open_pincode(base_state):
    base_state["customer_id"] = "CUST_99999"
    base_state["category"] = "electronics"
    res = run_signal_agent(base_state)
    assert res["signal_data"]["pincode_rto_rate"] == 0.18

# 7. Fail-Open Neutral Defaults for Complaint & Sentiment
def test_signal_agent_fail_open_neutral_defaults(base_state):
    base_state["customer_id"] = "CUST_99999"
    res = run_signal_agent(base_state)
    assert res["signal_data"]["complaint_score"] == 0.0
    assert res["signal_data"]["social_sentiment"] == 0.0

# 8. Hostile Signals Docking (complaint_score > 0.7)
def test_signal_agent_hostile_signals_docking(base_state):
    base_state["customer_id"] = "CUST_00002"
    base_state["delivery_pincode"] = "700002"
    base_state["transaction_profile"]["account_age_days"] = 45
    res = run_signal_agent(base_state)
    assert res["signal_data"]["complaint_score"] == 0.85
    assert res["confidence_score"] == 0.95  # 1.0 - 0.05

# 9. Boundary Test: Complaint Score Exact Threshold 0.70
def test_signal_agent_hostile_boundary_exact(base_state):
    base_state["customer_id"] = "CUST_00003"
    base_state["delivery_pincode"] = "560001"
    base_state["transaction_profile"]["account_age_days"] = 10
    res = run_signal_agent(base_state)
    assert res["signal_data"]["complaint_score"] == 0.70
    assert res["confidence_score"] == 1.0  # Threshold is strictly > 0.70

# 10. Boundary Test: Social Sentiment Threshold -0.40
def test_signal_agent_sentiment_boundary(base_state):
    base_state["customer_id"] = "CUST_00003"
    base_state["delivery_pincode"] = "560001"
    res = run_signal_agent(base_state)
    assert res["signal_data"]["social_sentiment"] == -0.40

# 11. Critical Mismatch Docking (Profile <=7 days, Signals >30 days)
def test_signal_agent_critical_mismatch(base_state):
    base_state["transaction_profile"]["account_age_days"] = 5  # New profile
    res = run_signal_agent(base_state)  # CUST_00001 has 100 days in signals
    assert res["confidence_score"] == 0.9  # 1.0 - 0.1
    assert any("Critical signal mismatch" in err for err in res["errors"])

# 12. No Mismatch When Profile Age > 7 Days
def test_signal_agent_no_mismatch_older_profile(base_state):
    base_state["transaction_profile"]["account_age_days"] = 15
    res = run_signal_agent(base_state)
    assert res["confidence_score"] == 1.0

# 13. Database Read Error / Timeout Handling
def test_signal_agent_db_timeout(base_state):
    from agents.signal_agent import _clear_signal_cache
    _clear_signal_cache()
    from core.cache import clear_cache
    clear_cache()
    with patch("agents.signal_agent._query_signals_db", side_effect=OSError("Disk Timeout")):
        res = run_signal_agent(base_state)
        assert res["signal_data"]["signals_available"] is False
        assert res["confidence_score"] == 0.9
        assert any("Signal database timeout" in err for err in res["errors"])

# 14. Schema Bounds Clamping & Retry Test
def test_signal_agent_schema_clamping(base_state):
    with patch("agents.signal_agent._query_signals_db") as mock_query:
        mock_query.return_value = ({
            "customer_id": "CUST_00001", "delivery_pincode": "110001",
            "pincode_rto_rate": "0.2", "category_return_rate": "0.2",
            "complaint_score": "1.5", "social_sentiment": "-2.5",
            "recent_events": "None", "account_age_days": "100"
        }, None)
        res = run_signal_agent(base_state)
        assert res["signal_data"]["complaint_score"] == 1.0
        assert res["signal_data"]["social_sentiment"] == -1.0

# 15. Cumulative Confidence Docking
def test_signal_agent_cumulative_docking(base_state):
    base_state["customer_id"] = "CUST_00002"  # Hostile signals (-0.05)
    base_state["delivery_pincode"] = "700002"
    base_state["transaction_profile"]["account_age_days"] = 3  # Mismatch (-0.1)

    with patch("agents.signal_agent._query_signals_db") as mock_query:
        mock_query.return_value = ({
            "customer_id": "CUST_00002", "delivery_pincode": "700002",
            "pincode_rto_rate": "0.50", "category_return_rate": "0.18",
            "complaint_score": "0.85", "social_sentiment": "-0.50",
            "recent_events": "High RTO pincode|Negative social mentions", "account_age_days": "45"
        }, None)

        res = run_signal_agent(base_state)
        # 1.0 - 0.05 (hostile) - 0.1 (mismatch) = 0.85
        assert res["confidence_score"] == 0.85

# 16. Confidence Floor Clamping at 0.0
def test_signal_agent_confidence_clamping(base_state):
    base_state["confidence_score"] = 0.05
    base_state["customer_id"] = "CUST_99999"  # Missing signals (-0.1)
    res = run_signal_agent(base_state)
    assert res["confidence_score"] == 0.0

# 17. Preserving Prior Errors
def test_signal_agent_error_preservation(base_state):
    base_state["errors"] = ["Prior agent failure"]
    base_state["customer_id"] = "CUST_99999"
    res = run_signal_agent(base_state)
    assert len(res["errors"]) == 2
    assert res["errors"][0] == "Prior agent failure"

# 18. None-Safety on Missing State Fields
def test_signal_agent_none_safety():
    res = run_signal_agent({})
    assert "signal_data" in res
    assert res["signal_data"]["signals_available"] is False
    assert res["confidence_score"] == 0.9

# 19. None-Safety on Missing Account Age in Profile
def test_signal_agent_none_profile_account_age(base_state):
    base_state["transaction_profile"] = {}
    res = run_signal_agent(base_state)
    assert res["signal_data"]["signals_available"] is True
    assert res["confidence_score"] == 1.0

# 20. Corrupted Numeric Data Handling
def test_signal_agent_corrupted_numeric_data(base_state):
    with patch("agents.signal_agent._query_signals_db") as mock_query:
        mock_query.return_value = ({
            "customer_id": "CUST_00001", "delivery_pincode": "110001",
            "pincode_rto_rate": "invalid_number", "category_return_rate": "invalid",
            "complaint_score": "corrupt", "social_sentiment": "bad",
            "recent_events": "None", "account_age_days": "n/a"
        }, None)
        res = run_signal_agent(base_state)
        # Defaults applied gracefully
        assert res["signal_data"]["pincode_rto_rate"] == 0.35
        assert res["signal_data"]["complaint_score"] == 0.0
        assert res["signal_data"]["social_sentiment"] == 0.0
