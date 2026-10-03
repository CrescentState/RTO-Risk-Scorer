import pytest

from evaluation.metrics import compute_benchmark_metrics


# 1. Missing dataset raises a clear service error (no mock fallback)
def test_compute_benchmark_metrics_default():
    with pytest.raises(ValueError, match="Benchmark data unavailable"):
        compute_benchmark_metrics()

# 2. Perfect Performance Metrics (Precision = 1.0, Recall = 1.0)
def test_compute_benchmark_metrics_perfect_scores():
    perfect_dataset = [
        {"risk_score": 80.0, "actual_is_rto": True},   # TP
        {"risk_score": 10.0, "actual_is_rto": False},  # TN
    ]
    metrics = compute_benchmark_metrics(perfect_dataset)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1_score"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["auto_approval_rate"] == 0.5

# 3. All False Positives Handling (Precision = 0.0)
def test_compute_benchmark_metrics_all_fp():
    dataset = [
        {"risk_score": 70.0, "actual_is_rto": False},  # FP
        {"risk_score": 80.0, "actual_is_rto": False},  # FP
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1_score"] == 0.0
    assert metrics["false_positive_rate"] == 1.0

# 4. All False Negatives Handling (Recall = 0.0)
def test_compute_benchmark_metrics_all_fn():
    dataset = [
        {"risk_score": 10.0, "actual_is_rto": True},  # FN
        {"risk_score": 15.0, "actual_is_rto": True},  # FN
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1_score"] == 0.0
    assert metrics["auto_approval_rate"] == 1.0

# 5. Empty Dataset Boundary (clear service error, no mock fallback)
def test_compute_benchmark_metrics_empty_dataset_handling():
    with pytest.raises(ValueError, match="Benchmark data unavailable"):
        compute_benchmark_metrics([])

# 6. Auto-Approve Boundary Condition (risk_score = 25.0 vs 25.1)
def test_compute_benchmark_metrics_auto_approve_boundary():
    dataset = [
        {"risk_score": 25.0, "actual_is_rto": False},  # Score <= 25.0 -> Auto-Approved (TN)
        {"risk_score": 25.1, "actual_is_rto": False},  # Score > 25.0 -> Flagged (FP)
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["auto_approval_rate"] == 0.5
    assert metrics["true_negatives"] == 1
    assert metrics["false_positives"] == 1

# 7. Money Saved Calculation Logic Formula Verification
def test_compute_benchmark_metrics_money_saved():
    # Formula: (TP * 100.0) - (FP * 50.0)
    dataset = [
        {"risk_score": 80.0, "actual_is_rto": True},   # TP (+100)
        {"risk_score": 80.0, "actual_is_rto": True},   # TP (+100)
        {"risk_score": 80.0, "actual_is_rto": False},  # FP (-50)
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["estimated_money_saved_inr"] == 150.00  # (200 - 50)

# 8. Negative Net Saved Money Handling
def test_compute_benchmark_metrics_negative_money_saved():
    dataset = [
        {"risk_score": 80.0, "actual_is_rto": False},  # FP (-50)
        {"risk_score": 80.0, "actual_is_rto": False},  # FP (-50)
        {"risk_score": 80.0, "actual_is_rto": False},  # FP (-50)
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["estimated_money_saved_inr"] == -150.00

# 9. FPR Boundary Safety when FP + TN = 0
def test_compute_benchmark_metrics_fpr_zero_division_safety():
    dataset = [
        {"risk_score": 80.0, "actual_is_rto": True},  # TP
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["false_positive_rate"] == 0.0

# 10. Large Mixed Dataset Aggregation Test
def test_compute_benchmark_metrics_mixed_aggregation():
    dataset = [
        {"risk_score": 80.0, "actual_is_rto": True},   # TP
        {"risk_score": 75.0, "actual_is_rto": False},  # FP
        {"risk_score": 10.0, "actual_is_rto": True},   # FN
        {"risk_score": 15.0, "actual_is_rto": False},  # TN
    ]
    metrics = compute_benchmark_metrics(dataset)
    assert metrics["total_orders"] == 4
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["true_negatives"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1_score"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["auto_approval_rate"] == 0.5
    assert metrics["estimated_money_saved_inr"] == 50.00
