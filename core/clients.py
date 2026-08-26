"""
Singleton clients for external services.
Initialized once at import time and reused across all agents.
"""

import httpx
from google import genai
from core.config import settings


# ── HTTP Client ──
# Shared async client for all HTTP requests (RSS, external APIs)
http_client: httpx.AsyncClient = httpx.AsyncClient(
    timeout=httpx.Timeout(5.0, connect=2.0),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    headers={"User-Agent": "RTO-Risk-Scorer/0.1.0"},
)


# ── Gemini Client ──
# Singleton genai client used by ALL agents (news, risk, synthesis)
# Do NOT create separate client instances in individual agents.
gemini_client: genai.Client | None = None

if settings.GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as e:
        # Log but don't crash — agents will handle missing client gracefully
        print(f"[WARNING] Gemini client initialization failed: {e}")
        gemini_client = None
else:
    print("[WARNING] GEMINI_API_KEY not set. LLM-dependent agents will run in degraded mode.")


def get_gemini_client() -> genai.Client | None:
    """Accessor — returns None if API key was missing or invalid."""
    return gemini_client