import logging
from typing import Any, Literal
from langgraph.graph import END, StateGraph

from domain.orchestrator.state import AgenticSystemState
from domain.chat.agents.chat_agent import (
    _classify_chat_query_combined,
    _answer_followup_with_context,
    _clear_chat_history
)
from domain.chat.services.chat_memory_service import (
    _add_to_chat_memory,
    _notify_failure,
    _get_full_conversation_context
)
from common.services.agentic_integration import run_route_classifier
from common.ai.rag.chat_rag import query_chat_rag

logger = logging.getLogger(__name__)

# ============================================================================
# LANGGRAPH NODES
# ============================================================================

def classify_intent_node(state: AgenticSystemState) -> AgenticSystemState:
    session_id = state.get("session_id", "default")
    user_query = state.get("user_input", "")
    
    conversation_context = _get_full_conversation_context(session_id)
    logger.info(f"[CHAT_WORKFLOW] Processing query with {len(conversation_context)} chars of context")
    
    classification = _classify_chat_query_combined(user_query, conversation_context)
    logger.info(f"[CHAT_WORKFLOW] Query '{user_query[:50]}...' → {classification}")
    
    state["workflow_step"] = classification
    return state

def answer_followup_node(state: AgenticSystemState) -> AgenticSystemState:
    session_id = state.get("session_id", "default")
    user_query = state.get("user_input", "")
    
    logger.info("[CHAT_WORKFLOW] ⚡ VALID_FOLLOWUP - answering from conversation history only")
    chat_response = _answer_followup_with_context(user_query, session_id)
    
    _add_to_chat_memory(
        session_id=session_id,
        user_query=user_query,
        assistant_response=chat_response.get("answer", ""),
        metadata={}
    )
    
    state["final_response"] = {
        "success": True,
        "answer": chat_response.get("answer", ""),
        "source": chat_response.get("source", "conversation_history_only"),
        "is_chat_related": True,
        "has_user_context": False,
        "is_followup": True
    }
    return state

def query_rag_node(state: AgenticSystemState) -> AgenticSystemState:
    session_id = state.get("session_id", "default")
    user_query = state.get("user_input", "")
    user_id = state.get("user_id")
    
    logger.info("[CHAT_WORKFLOW] VALID_NEW_QUERY - routing to chat RAG with MongoDB context")
    chat_response = query_chat_rag(
        user_query=user_query,
        user_id=user_id,
        session_id=session_id
    )
    
    _add_to_chat_memory(
        session_id=session_id,
        user_query=user_query,
        assistant_response=chat_response.get("answer", ""),
        metadata={}
    )
    
    state["final_response"] = {
        "success": True,
        "answer": chat_response.get("answer", ""),
        "source": chat_response.get("source", "database_with_context"),
        "is_chat_related": True,
        "has_user_context": chat_response.get("has_user_context", False),
        "is_followup": False,
        "keywords_extracted": chat_response.get("keywords_extracted", {})
    }
    return state

def route_to_orchestrator_node(state: AgenticSystemState) -> AgenticSystemState:
    session_id = state.get("session_id", "default")
    user_query = state.get("user_input", "")
    user_id = state.get("user_id")
    
    logger.info("[CHAT_WORKFLOW] INVALID - routing to router classifier")
    router_result = run_route_classifier(
        user_input=user_query,
        current_page="chat",
        search_session_id=session_id,
        user_session_id=session_id,
        user_id=user_id
    )
    
    direct_response = router_result.get("directResponse") or "Let me help you on the appropriate page."
    _add_to_chat_memory(
        session_id=session_id,
        user_query=user_query,
        assistant_response=direct_response,
        metadata={}
    )
    
    state["final_response"] = {
        "success": True,
        "is_chat_related": False,
        "router_result": router_result,
        "answer": router_result.get("directResponse") or "I can help with that type of request. However, to proceed properly, please navigate to the relevant page via the sidebar."
    }
    return state

# ============================================================================
# ROUTING LOGIC
# ============================================================================

def route_after_classification(state: AgenticSystemState) -> Literal["answer_followup", "query_rag", "route_to_orchestrator"]:
    classification = state.get("workflow_step")
    if classification == "VALID_FOLLOWUP":
        return "answer_followup"
    elif classification == "VALID_NEW_QUERY":
        return "query_rag"
    else:
        return "route_to_orchestrator"

# ============================================================================
# GRAPH CREATION
# ============================================================================

def create_chat_workflow() -> StateGraph:
    """Create the Chat workflow graph."""
    workflow = StateGraph(AgenticSystemState)
    
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("answer_followup", answer_followup_node)
    workflow.add_node("query_rag", query_rag_node)
    workflow.add_node("route_to_orchestrator", route_to_orchestrator_node)
    
    workflow.set_entry_point("classify_intent")
    
    workflow.add_conditional_edges(
        "classify_intent",
        route_after_classification,
        {
            "answer_followup": "answer_followup",
            "query_rag": "query_rag",
            "route_to_orchestrator": "route_to_orchestrator"
        }
    )
    
    workflow.add_edge("answer_followup", END)
    workflow.add_edge("query_rag", END)
    workflow.add_edge("route_to_orchestrator", END)
    
    return workflow.compile()

# ============================================================================
# PUBLIC API FUNCTIONS
# ============================================================================

def process_chat_request(user_query: str, session_id: str = "default", user_id: int | None = None) -> dict[str, Any]:
    """
    Process a chat request using the Chat Workflow Graph.
    """
    try:
        from datetime import datetime

        initial_state: AgenticSystemState = {
            "user_input": user_query,
            "session_id": session_id,
            "user_id": user_id,
            "current_page": "chat",
            "agent_path": [],
            "timestamp": datetime.now()
        }
        
        agent = create_chat_workflow()
        result_state = agent.invoke(initial_state)

        final_response = result_state.get("final_response", {})

        # Phase 4: validate workflow output at the graph edge (warn-only, payload unchanged).
        try:
            from common.models.validation import validate_response
            from domain.chat.schemas import ChatResponse
            validate_response(ChatResponse, final_response, context="chat_workflow_exit")
        except Exception:
            pass

        return final_response

    except Exception as e:
        logger.error(f"[CHAT_WORKFLOW] Error processing request: {e}", exc_info=True)
        _notify_failure(
            "Chat Request Processing", 
            f"Error processing chat request: {str(e)}", 
            user_id=user_id, 
            user_query=user_query[:200], 
            session_id=session_id
        )
        return {
            "success": False,
            "error": str(e),
            "answer": "I encountered an error trying to process your request."
        }

def query_chat(user_query: str, session_id: str = "default", user_id: int | None = None) -> dict[str, Any]:
    """
    Direct chat query processing (bypasses intent classification).
    """
    logger.info(f"[CHAT_WORKFLOW] Direct query_chat call: {user_query}")
    return query_chat_rag(user_query, user_id, session_id)

def clear_pending_query(session_id: str = "default"):
    """
    Clear conversation history for a chat session.
    """
    _clear_chat_history(session_id)
    logger.info(f"[CHAT_WORKFLOW] Cleared chat session {session_id}")

def clear_session_memory(session_id: str = "default"):
    """Clear all conversation memory for a session."""
    _clear_chat_history(session_id)

def check_chat_agent_health():
    """Health check for Chat Agent"""
    from common.monitoring.usage import AgentHealthChecker, DependencyStatus
    checker = AgentHealthChecker()
    dependencies = {}
    status = "healthy"
    
    try:
        dependencies["llm_flash"] = checker.check_llm_connectivity("google")
        if dependencies["llm_flash"].status == "unavailable":
            status = "unhealthy"
            
        dependencies["llm_search"] = DependencyStatus("llm_search", "available")
        dependencies["mongodb_vendors"] = checker.check_mongodb_collection("vendors")
        if dependencies["mongodb_vendors"].status == "unavailable":
            status = "unhealthy"
            
        from common.monitoring.usage import AgentHealthStatus
        return AgentHealthStatus("chat_agent", status, dependencies)
    except Exception as e:
        logger.error(f"[CHAT_WORKFLOW] Health check failed: {e}")
        from common.monitoring.usage import AgentHealthStatus
        return AgentHealthStatus("chat_agent", "unhealthy", {}, str(e))
