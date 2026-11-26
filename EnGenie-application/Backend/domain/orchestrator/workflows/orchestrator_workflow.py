import logging
from langgraph.graph import END, StateGraph

from domain.orchestrator.state import AgenticSystemState
from domain.orchestrator.agents.router_classifier_agent import router_classifier_node

logger = logging.getLogger(__name__)

def create_orchestrator_workflow() -> StateGraph:
    """
    Create the Orchestrator workflow graph.
    Currently a single step (routing classification), but prepared for expansion.
    """
    workflow = StateGraph(AgenticSystemState)
    
    # Add router node
    workflow.add_node("router_classifier", router_classifier_node)
    
    # Set entry point
    workflow.set_entry_point("router_classifier")
    
    # Simply end after classification
    workflow.add_edge("router_classifier", END)
    
    return workflow.compile()
