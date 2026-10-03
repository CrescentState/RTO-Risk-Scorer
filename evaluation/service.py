"""
Shared benchmark service.

Computes the real benchmark report once, caches it for one hour, and
serves both /metrics and /benchmark from the same payload. An async
single-flight lock prevents concurrent recomputation. The cache is
invalidated when any dataset file metadata changes. LLM narratives are
always disabled during benchmark computation.
"""

import asyncio
import time
from typing import Any

from core.orders import data_signature
from evaluation.benchmark import run_benchmark_async

CACHE_TTL_SECONDS = 3600

_lock = asyncio.Lock()
_cached_report: dict[str, Any] | None = None
_cached_signature: str | None = None
_cached_at: float = 0.0


def _is_fresh(signature: str) -> bool:
    return (
        _cached_report is not None
        and _cached_signature == signature
        and (time.time() - _cached_at) < CACHE_TTL_SECONDS
    )


async def get_benchmark_report() -> dict[str, Any]:
    """Return the cached benchmark report, recomputing if stale or missing."""
    global _cached_report, _cached_signature, _cached_at
    signature = data_signature()
    if _is_fresh(signature):
        assert _cached_report is not None
        return _cached_report
    async with _lock:
        signature = data_signature()
        if _is_fresh(signature):
            assert _cached_report is not None
            return _cached_report
        report = await run_benchmark_async()
        _cached_report = report
        _cached_signature = signature
        _cached_at = time.time()
        return report


async def get_benchmark_metrics() -> dict[str, Any]:
    """Return the metrics subset of the shared benchmark report."""
    report = await get_benchmark_report()
    return {
        "precision": report["precision"],
        "recall": report["recall"],
        "f1_score": report["f1_score"],
        "false_positive_rate": report["false_positive_rate"],
        "auto_approval_rate": report["auto_approval_rate"],
        "estimated_money_saved_inr": report["estimated_money_saved_inr"],
    }


def invalidate_benchmark_cache() -> None:
    """Clear the cached report (used by tests)."""
    global _cached_report, _cached_signature, _cached_at
    _cached_report = None
    _cached_signature = None
    _cached_at = 0.0
