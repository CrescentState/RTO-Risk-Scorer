"""
LangGraph StateGraph compilation and execution.
Sequential DAG: Profile → Signal → Risk → Synthesis.
"""

from langgraph.graph import StateGraph, END

from core.state import SystemState, init_state
from agents.profile_agent import run_profile_agent
from agents.signal_agent import run_signal_agent


# Module-level compiled pipeline (singleton)
_pipeline: StateGraph | None = None


def create_pipeline() -> StateGraph:
    """
    Compile the 4-agent sequential StateGraph.
    Each node depends on the previous; no parallel execution.
    """
    workflow = StateGraph(SystemState)

    # Register nodes
    workflow.add_node("profile_agent", run_profile_agent)
    workflow.add_node("signal_agent", run_signal_agent)

    # Sequential edges (each depends on previous agent's output)
    workflow.set_entry_point("profile_agent")
    workflow.add_edge("profile_agent", "signal_agent")
    workflow.add_edge("signal_agent", END)

    return workflow.compile()


def get_pipeline() -> StateGraph:
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
    """Synchronous entry point. Creates state and invokes the compiled graph."""
    pipeline = get_pipeline()
    initial_state = init_state(
        order_id=order_id,
        customer_id=customer_id,
        order_value=order_value,
        category=category,
        payment_method=payment_method,
        delivery_pincode=delivery_pincode,
    )
    return pipeline.invoke(initial_state)


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
    return await pipeline.ainvoke(initial_state)