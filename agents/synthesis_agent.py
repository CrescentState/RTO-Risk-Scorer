"""
Agent 4: Synthesis Agent
Generates a structured merchant-facing action brief combining all prior agent outputs.
Programmatically overrides recommended_action with a deterministic label.

Uses Pydantic for response validation, string.Template for safe prompt construction,
singleton Gemini client, and decision table for deterministic override.
"""

import asyncio
from dataclasses import dataclass
from string import Template
from typing import Any

from core.clients import get_gemini_client
from core.config import settings


@dataclass(frozen=True, slots=True)
class ActionBrief:
    """Validated action brief structure."""
    order_summary: str
    risk_assessment: str
    market_context: str
    mitigation_suggestions: list[str]
    key_concerns: list[str]
    recommended_action: str


# Fallback constants
FALLBACK_BRIEF = {
    "order_summary": "Order analysis pending due to system error.",
    "risk_assessment": "Risk computed deterministically. Narrative unavailable.",
    "market_context": "System degradation detected.",
    "mitigation_suggestions": ["Review order manually."],
    "key_concerns": ["LLM synthesis pipeline error encountered."],
    "recommended_action": "Manual Review",
}


# Deterministic override decision table: (confidence < 0.5) -> Manual Review
def _compute_recommendation(state: dict[str, Any]) -> str:
    """
    Computes final recommendation with deterministic override logic.
    Low confidence (< MIN_CONFIDENCE_FOR_AUTO) always forces Manual Review.
    """
    confidence = float(state.get("confidence_score", 1.0))
    risk_data = state.get("risk_data") or {}

    # Override: low confidence (< MIN_CONFIDENCE_FOR_AUTO) always forces Manual Review
    if confidence < settings.MIN_CONFIDENCE_FOR_AUTO:
        return "Manual Review"

    return str(risk_data.get("recommendation", "Manual Review"))


def _safe_summary(d: dict, safe_keys: set | None = None) -> str:
    """Extract only safe, non-PII fields for prompt."""
    if safe_keys is None:
        safe_keys = {"return_rate", "recent_returns_30d", "total_orders", "account_age_days",
                     "order_value", "category", "payment_method", "pincode_rto_rate",
                     "complaint_score", "social_sentiment", "category_return_rate",
                     "risk_score", "recommendation"}
    parts: list[str] = [f"{k}: {d[k]}" for k in safe_keys if k in d]
    return "{" + ", ".join(parts) + "}"


def _build_prompt(state: dict[str, Any], deterministic_action: str) -> str:
    """Build safe prompt using Template to prevent injection."""
    _safe_summary(state.get("transaction_profile", {}))
    _safe_summary(state.get("signal_data", {}))
    _safe_summary(state.get("risk_data", {}))
    factors = state.get("risk_data", {}).get("risk_factors", [])

    prompt_template = Template(
        "You are a merchant risk analyst. Synthesize the following transaction context into a structured brief.\n"
        "Do NOT include a recommended_action field.\n"
        "Return ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "order_summary": "1-2 sentence order summary",\n'
        '  "risk_assessment": "1-2 sentence risk breakdown",\n'
        '  "market_context": "1-2 sentence market/geographic context",\n'
        '  "mitigation_suggestions": ["actionable step 1", "actionable step 2"],\n'
        '  "key_concerns": ["key risk factor 1", "key risk factor 2"]\n'
        "}\n\n"
        "Context Data:\n"
        "Order Value: $order_value\n"
        "Payment Method: $payment_method\n"
        "Category: $category\n"
        "Confidence Score: $confidence_score\n"
        "Deterministic Recommendation: $deterministic_action\n"
        "Risk Factors: $factors\n"
        "Transaction Profile: $profile\n"
        "Signal Data: $signals\n"
        "Risk Data: $risk\n"
    )

    return prompt_template.substitute(
        order_value=state.get("order_value", "N/A"),
        payment_method=state.get("payment_method", "N/A"),
        category=state.get("category", "N/A"),
        confidence_score=state.get("confidence_score", "N/A"),
        deterministic_action=deterministic_action,
        factors=', '.join(factors) if factors else "None",
        profile=_safe_summary(state.get("transaction_profile", {})),
        signals=_safe_summary(state.get("signal_data", {})),
        risk=_safe_summary(state.get("risk_data", {})),
    )


def _parse_llm_response(response_text: str, fallback: dict) -> tuple[dict[str, Any], str | None]:
    """Parse and validate LLM JSON response with fallbacks.
    Returns (parsed_dict, error_message) where error_message is None on success.
    """
    import json

    if not response_text or not response_text.strip():
        return fallback, "Empty LLM response"

    raw_text = response_text.strip()

    # Strip markdown code blocks
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]

    raw_text = raw_text.strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return fallback, f"LLM returned invalid JSON: {str(e)}"

    # Validate and coerce each field
    result: dict[str, Any] = {}
    result["order_summary"] = str(parsed.get("order_summary", fallback["order_summary"]))
    result["risk_assessment"] = str(parsed.get("risk_assessment", fallback["risk_assessment"]))
    result["market_context"] = str(parsed.get("market_context", fallback["market_context"]))

    # Coerce mitigation_suggestions to list of strings
    mitigations = parsed.get("mitigation_suggestions")
    if isinstance(mitigations, list):
        result["mitigation_suggestions"] = [str(m) for m in mitigations]
    else:
        result["mitigation_suggestions"] = fallback["mitigation_suggestions"]

    # Coerce key_concerns to list of strings
    concerns = parsed.get("key_concerns")
    if isinstance(concerns, list):
        result["key_concerns"] = [str(c) for c in concerns]
    else:
        result["key_concerns"] = fallback["key_concerns"]

    return result, None


async def run_synthesis_agent(state: dict[str, Any]) -> dict[str, Any]:
    """
    Agent 4: Synthesis Agent
    Generates a structured merchant-facing action brief combining all prior agent outputs.
    Programmatically overrides recommended_action with a deterministic label.
    """
    errors = list(state.get("errors", []))
    deterministic_action = _compute_recommendation(state)

    # Base fallback payload
    fallback = FALLBACK_BRIEF.copy()
    fallback["recommended_action"] = deterministic_action
    action_brief = fallback.copy()

    # Attempt LLM Narrative Synthesis if API key is present
    from core.config import settings

    # Skip LLM if narratives are disabled (fast processing mode)
    if not settings.ENABLE_LLM_NARRATIVES:
        action_brief = fallback.copy()
    else:
        client = get_gemini_client()
        if client is not None:
            try:
                prompt = _build_prompt(state, deterministic_action)

                async def _call_llm_async() -> Any:
                    return await asyncio.to_thread(
                        client.models.generate_content,
                        model=settings.GEMINI_MODEL,
                        contents=prompt,
                    )

                response = await asyncio.wait_for(_call_llm_async(), timeout=15.0)

                if response and response.text:
                    parsed, parse_error = _parse_llm_response(response.text, fallback)
                    if parse_error:
                        msg = f"Synthesis LLM error: {parse_error}"
                        if msg not in errors:
                            errors.append(msg)
                        action_brief = fallback.copy()
                    else:
                        action_brief.update(parsed)
                        # Ensure recommended_action is always deterministic
                        action_brief["recommended_action"] = deterministic_action

            except TimeoutError:
                if "Synthesis LLM timed out (15s)" not in errors:
                    errors.append("Synthesis LLM timed out (15s)")
                action_brief = fallback.copy()
            except Exception as e:
                msg = f"Synthesis LLM error: {str(e)}"
                if msg not in errors:
                    errors.append(msg)
                action_brief = fallback.copy()

    # Programmatic override guarantees deterministic recommendation
    action_brief["recommended_action"] = deterministic_action

    state["action_brief"] = action_brief
    state["errors"] = errors

    return state
