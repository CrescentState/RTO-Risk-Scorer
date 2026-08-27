"""
Singleton clients for external services.
Initialized once at import time and reused across all agents.
"""

import httpx
from google import genai
from core.config import settings


# ── HTTP Client ──
# Shared async client for all HTTP requests (RSS, external APIs)
_http_client: httpx.AsyncClient | None = None


# ── Gemini Client ──
# Singleton genai client used by ALL agents (news, risk, synthesis)
# Do NOT create separate client instances in individual agents.
_gemini_client: genai.Client | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "RTO-Risk-Scorer/0.1.0"},
        )
    return _http_client


def get_gemini_client() -> genai.Client | None:
    """Get or create the Gemini client."""
    global _gemini_client, _gemini_warned
    if _gemini_client is None and settings.GEMINI_API_KEY:
        try:
            _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            # Log but don't crash — agents will handle missing client gracefully
            print(f"[WARNING] Gemini client initialization failed: {e}")
            _gemini_client = None
    elif _gemini_client is None and not settings.GEMINI_API_KEY and not _gemini_warned:
        print("[WARNING] GEMINI_API_KEY not set. LLM-dependent agents will run in degraded mode.")
        _gemini_warned = True
    return _gemini_client


_gemini_warned = False


async def close_clients() -> None:
    """Close all client connections. Call on application shutdown."""
    global _http_client, _gemini_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    # Gemini client doesn't need explicit close