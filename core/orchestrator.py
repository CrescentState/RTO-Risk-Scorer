"""
LangGraph StateGraph compilation and execution.
Sequential DAG: Profile → Signal → Risk → Synthesis.
"""

from langgraph.graph import StateGraph, END

from core.state import SystemState, init_state
from agents.profile_agent import profile_agent
from agents.signal_agent import signal_agent
from agents.risk_agent import risk_agent
from agents.synthesis_agent import synthesis_agent


def create_pipeline() -> StateGraph:
    """
    Compile the 4-agent sequential StateGraph.
    Each node depends on the previous; no parallel execution.
    """
    workflow = StateGraph(SystemState)

    # Register nodes
    workflow.add_node("profile_agent", profile_agent)
    workflow.add_node("signal_agent", signal_agent)
    workflow.add_node("risk_agent", risk_agent)
    workflow.add_node("synthesis_agent", synthesis_agent)

    # Sequential edges (each depends on previous agent's output)
    workflow.set_entry_point("profile_agent")
    workflow.add_edge("profile_agent", "signal_agent")
    workflow.add_edge("signal_agent", "risk_agent")
    workflow.add_edge("risk_agent", "synthesis_agent")
    workflow.add_edge("synthesis_agent", END)

    return workflow.compile()


def run_pipeline(
    order_id: str,
    customer_id: str,
    order_value: float,
    category: str,
    payment_method: str,
    delivery_pincode: str,
) -> SystemState:
    """Synchronous entry point. Creates state and invokes the compiled graph."""
    pipeline = create_pipeline()
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
    pipeline = create_pipeline()
    initial_state = init_state(
        order_id=order_id,
        customer_id=customer_id,
        order_value=order_value,
        category=category,
        payment_method=payment_method,
        delivery_pincode=delivery_pincode,
    )
    return await pipeline.ainvoke(initial_state)