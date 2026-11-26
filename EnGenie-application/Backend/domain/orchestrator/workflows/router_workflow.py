"""
Router Classifier Workflow

Entry workflow for ALL user requests. Sets up the LangGraph to classify and route queries.
"""

import logging
from langgraph.graph import END, StateGraph

from domain.orchestrator.state import AgenticSystemState
from domain.orchestrator.agents.router_classifier_agent import (
    router_classifier_node,
    route_to_workflow,
    direct_response_node,
    routing_response_node,
    solution_workflow_placeholder,
    chat_workflow_node,
    search_workflow_placeholder,
    admin_workflow_placeholder
)

logger = logging.getLogger(__name__)


def build_router_classifier_graph():
    """
    Build the Route Classifier LangGraph.

    This is the ENTRY POINT for all user requests.

    Graph Flow:
        router_classifier_node
            → (conditional routing)
                → direct_response_node (greetings, chitchat)
                → solution_workflow (instruments)
                → chat_workflow (RAG queries)
                → search_workflow (product search)
                → admin_workflow (user management)
    """
    graph = StateGraph(AgenticSystemState)

    # Add nodes
    graph.add_node("router_classifier", router_classifier_node)
    graph.add_node("direct_response_node", direct_response_node)
    graph.add_node("routing_response_node", routing_response_node)
    graph.add_node("solution_workflow", solution_workflow_placeholder)
    graph.add_node("chat_workflow", chat_workflow_node)
    graph.add_node("search_workflow", search_workflow_placeholder)
    graph.add_node("admin_workflow", admin_workflow_placeholder)

    # Set entry point
    graph.set_entry_point("router_classifier")

    # Add conditional routing from router_classifier
    graph.add_conditional_edges(
        "router_classifier",
        route_to_workflow,
        {
            "direct_response_node": "direct_response_node",
            "routing_response_node": "routing_response_node",
            "solution_workflow": "solution_workflow",
            "chat_workflow": "chat_workflow",
            "search_workflow": "search_workflow",
            "admin_workflow": "admin_workflow"
        }
    )

    # All paths end after their node
    graph.add_edge("direct_response_node", END)
    graph.add_edge("routing_response_node", END)
    graph.add_edge("solution_workflow", END)
    graph.add_edge("chat_workflow", END)
    graph.add_edge("search_workflow", END)
    graph.add_edge("admin_workflow", END)

    # Compile the graph
    compiled_graph = graph.compile()

    logger.info("[ROUTE_CLASSIFIER] Graph compiled successfully")
    return compiled_graph


# Build and export the compiled graph
router_classifier_agent = build_router_classifier_graph()

__all__ = ["router_classifier_agent", "build_router_classifier_graph"]
