"""
LangGraph StateGraph compilation and execution.
Sequential DAG: Profile → Signal → Risk → Synthesis.
"""

import asyncio

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.profile_agent import run_profile_agent
from agents.risk_agent import run_risk_agent
from agents.signal_agent import run_signal_agent
from agents.synthesis_agent import run_synthesis_agent
from core.state import SystemState, init_state

# Module-level compiled pipeline (singleton)
_pipeline: CompiledStateGraph | None = None


def create_pipeline() -> CompiledStateGraph:
    """
    Compile the 4-agent sequential StateGraph.
    Each node depends on the previous; no parallel execution.
    """
    workflow = StateGraph(SystemState)

    from langgraph.types import RetryPolicy

    # Register nodes with retries disabled to prevent error duplication on LLM failures
    workflow.add_node("profile_agent", run_profile_agent, retry_policy=RetryPolicy(max_attempts=1))  # type: ignore
    workflow.add_node("signal_agent", run_signal_agent, retry_policy=None)  # type: ignore
    workflow.add_node("risk_agent", run_risk_agent, retry_policy=RetryPolicy(max_attempts=1))  # type: ignore
    workflow.add_node("synthesis_agent", run_synthesis_agent, retry_policy=RetryPolicy(max_attempts=1))  # type: ignore

    # Sequential edges (each depends on previous agent's output)
    workflow.set_entry_point("profile_agent")
    workflow.add_edge("profile_agent", "signal_agent")
    workflow.add_edge("signal_agent", "risk_agent")
    workflow.add_edge("risk_agent", "synthesis_agent")
    workflow.add_edge("synthesis_agent", END)

    return workflow.compile()


def get_pipeline() -> CompiledStateGraph:
    """Get or create the compiled pipeline (singleton)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = create_pipeline()
    return _pipeline


def run_pipeline(
    order_id: str,
    customer_id: str,
    order_value: float,
    category: str,
    payment_method: str,
    delivery_pincode: str,
) -> SystemState:
    """Synchronous entry point backed by the async pipeline implementation."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            run_pipeline_async(
                order_id=order_id,
                customer_id=customer_id,
                order_value=order_value,
                category=category,
                payment_method=payment_method,
                delivery_pincode=delivery_pincode,
            )
        )
    raise RuntimeError("run_pipeline() cannot be called from a running event loop; use await run_pipeline_async() instead")


async def run_pipeline_async(
    order_id: str,
    customer_id: str,
    order_value: float,
    category: str,
    payment_method: str,
    delivery_pincode: str,
) -> SystemState:
    """Asynchronous entry point. Used by FastAPI handlers."""
    pipeline = get_pipeline()
    initial_state = init_state(
        order_id=order_id,
        customer_id=customer_id,
        order_value=order_value,
        category=category,
        payment_method=payment_method,
        delivery_pincode=delivery_pincode,
    )
    return await pipeline.ainvoke(initial_state)  # type: ignore[return-value]
