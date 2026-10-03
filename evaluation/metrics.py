from typing import Any


def compute_benchmark_metrics(dataset: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    Computes precision, recall, F1 score, FPR, auto-approval rate,
    and estimated monetary savings from RTO prevention.
    Raises ValueError when no measured dataset is provided.
    """
    if not dataset:
        raise ValueError("Benchmark data unavailable: empty or missing dataset")

    tp = 0  # Flagged as RTO (> 60.0 score or Manual/Reject) + Actually RTO
    fp = 0  # Flagged as RTO + Actually legit
    fn = 0  # Not flagged (<= 25.0 Auto-Approve) + Actually RTO
    tn = 0  # Not flagged + Actually legit

    auto_approved_count = 0
    total_orders = len(dataset)

    for item in dataset:
        score = item["risk_score"]
        actual_rto = item["actual_is_rto"]

        is_flagged = score > 25.0  # Non-auto-approved orders (Manual Review / Auto-Reject)

        if score <= 25.0:
            auto_approved_count += 1

        if is_flagged and actual_rto:
            tp += 1
        elif is_flagged and not actual_rto:
            fp += 1
        elif not is_flagged and actual_rto:
            fn += 1
        elif not is_flagged and not actual_rto:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    auto_approval_rate = auto_approved_count / total_orders if total_orders > 0 else 0.0

    # Business impact calculation:
    # (Prevented RTOs * ₹100 avg cost) - (FP * ₹50 review cost)
    estimated_money_saved = (tp * 100.0) - (fp * 50.0)

    return {
        "total_orders": total_orders,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1_score, 4),
        "false_positive_rate": round(fpr, 4),
        "auto_approval_rate": round(auto_approval_rate, 4),
        "estimated_money_saved_inr": round(estimated_money_saved, 2)
    }
