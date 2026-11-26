"""
Router Classifier Agent

Entry point for ALL user requests. Classifies input and routes to appropriate workflow.

This agent:
1. Initializes session if needed
2. Classifies user input (inline LLM classification)
3. Routes to: solution_workflow | search_workflow | chat_workflow | admin_workflow | direct_response
4. Handles greetings and non-routing responses directly
"""

import ast
import json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import os

# Import state and prompts
import sys
import uuid
from datetime import datetime
from typing import Literal

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate


sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from domain.chat.workflows.chat_workflow import process_chat_request
from domain.orchestrator.state import AgenticSystemState
from common.ai.llm import get_flash_llm

# ============================================================================
# LOAD PROMPTS FROM .md FILES
# ============================================================================

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

with open(os.path.join(_PROMPTS_DIR, "router_classification_prompt.md"), encoding="utf-8") as _f:
    CLASSIFICATION_PROMPT = _f.read()

# ============================================================================
# PAGE METADATA
# ============================================================================

PAGE_DESCRIPTIONS = {
    "solution": "Solution page to identify instruments and accessories",
    "chat": "Chat page to query our vendor database",
    "search": "Search page to find matching products"
}

PAGE_NAMES = {
    "solution": "Solution",
    "chat": "Chat",
    "search": "Search"
}

NON_ROUTING_CATEGORIES = [
    "out_of_scope",
    "general_interaction",
    "project_recall"
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def escape_newlines_in_json(s: str) -> str:
    """Escapes literal newlines, carriage returns, and tabs inside JSON string values."""
    result = []
    in_string = False
    escaped = False
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
            result.append(char)
        elif char == '\\' and in_string:
            escaped = not escaped
            result.append(char)
        else:
            if escaped:
                escaped = False
            if in_string and char in ('\n', '\r', '\t'):
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
            else:
                result.append(char)
    return "".join(result)



def _handle_episodic_recall(state: AgenticSystemState, user_id: str, session_id: str, user_input: str) -> bool:
    """
    Episodic project recall pre-step.

    Check whether the input semantically matches a saved project and, if so,
    offer to retrieve it via Open / Preview / Ignore buttons.

    Returns True if a recall response was produced and the router should
    short-circuit (skip normal LLM classification).
    """
    from app.services.project_service import match_saved_projects
    from common.ai.memory import clear_pending_recall, get_pending_recall

    pending = get_pending_recall(session_id)
    if pending:
        clear_pending_recall(session_id)
        logging.info("[ROUTE_CLASSIFIER] Cleared pending recall — use Open/Preview/Ignore buttons")

    match = match_saved_projects(user_id, session_id, user_input)
    if match.get("matched"):
        state["route_category"] = "project_recall"
        state["target_page"] = state.get("current_page", "solution")
        state["requires_routing"] = False
        state["requires_confirmation"] = True
        state["direct_response"] = match.get("message", "")
        state["recall_response"] = match
        logging.info(
            f"[ROUTE_CLASSIFIER] Episodic recall offer made: "
            f"{len(match.get('candidates', []))} candidate(s)"
        )
        return True

    return False



# ============================================================================
# ROUTE CLASSIFIER NODE
# ============================================================================

def router_classifier_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Entry point agent - classifies user input and determines routing.

    Args:
        state: Current agentic system state

    Returns:
        Updated state with routing decision
    """
    logging.info(f"[ROUTE_CLASSIFIER] Processing input: {state.get('user_input', '')[:100]}...")

    # Initialize warnings list
    if not state.get("warnings"):
        state["warnings"] = []

    # Initialize feature flags
    if not state.get("feature_flags"):
        state["feature_flags"] = {}

    # ========================================================================
    # VALIDATE & HANDLE user_id
    # ========================================================================
    user_id = state.get("user_id")

    if not user_id:
        warning_msg = "⚠️  No user_id provided - User-specific features disabled (strategies, standards, saved projects)"
        logging.warning(f"[ROUTE_CLASSIFIER] {warning_msg}")
        state["warnings"].append(warning_msg)
        state["feature_flags"]["user_data_enabled"] = False
        state["feature_flags"]["can_save_projects"] = False
        state["feature_flags"]["can_load_strategies"] = False
        state["feature_flags"]["can_load_standards"] = False
    else:
        logging.info(f"[ROUTE_CLASSIFIER] User ID: {user_id}")
        state["feature_flags"]["user_data_enabled"] = True
        state["feature_flags"]["can_save_projects"] = True
        state["feature_flags"]["can_load_strategies"] = True
        state["feature_flags"]["can_load_standards"] = True

    # ========================================================================
    # VALIDATE & HANDLE session_id
    # ========================================================================
    session_id = state.get("session_id")
    user_session_id = state.get("user_session_id")

    if not session_id:
        # Create new session
        state["session_id"] = str(uuid.uuid4())
        warning_msg = f"⚠️  No session_id provided - Created new session: {state['session_id']} (Chat history will not persist)"
        logging.warning(f"[ROUTE_CLASSIFIER] {warning_msg}")
        state["warnings"].append(warning_msg)
        state["session_created"] = True
        state["feature_flags"]["chat_history_enabled"] = False
        state["feature_flags"]["can_handle_followups"] = False
        state["feature_flags"]["can_handle_confirmations"] = False
    else:
        # Existing session - can track history
        logging.info(f"[ROUTE_CLASSIFIER] Conversation Session: {session_id} | User/Browser Session: {user_session_id}")
        state["session_created"] = False
        state["feature_flags"]["chat_history_enabled"] = True
        state["feature_flags"]["can_handle_followups"] = True
        state["feature_flags"]["can_handle_confirmations"] = True

    # ========================================================================
    # VALIDATE current_page
    # ========================================================================
    current_page = state.get("current_page")

    if not current_page or current_page not in ["solution", "chat", "search"]:
        warning_msg = f"⚠️  Invalid current_page: '{current_page}' - Defaulting to 'solution'"
        logging.warning(f"[ROUTE_CLASSIFIER] {warning_msg}")
        state["warnings"].append(warning_msg)
        state["current_page"] = "solution"
        current_page = "solution"

    # ========================================================================
    # VALIDATE user_input
    # ========================================================================
    user_input = state.get("user_input", "").strip()

    if not user_input:
        error_msg = "❌ user_input is required and cannot be empty"
        logging.error(f"[ROUTE_CLASSIFIER] {error_msg}")
        state["error"] = error_msg
        state["route_category"] = "error"
        state["target_page"] = current_page
        state["requires_routing"] = False
        state["direct_response"] = "Please provide a valid input."
        return state

    # Set timestamp
    if not state.get("timestamp"):
        state["timestamp"] = datetime.now()

    # Initialize agent path tracking
    if not state.get("agent_path"):
        state["agent_path"] = []
    state["agent_path"].append("router_classifier")

    # ========================================================================
    # LOG FEATURE STATUS
    # ========================================================================
    logging.info(
        f"[ROUTE_CLASSIFIER] Feature Status: "
        f"user_data={state['feature_flags']['user_data_enabled']}, "
        f"chat_history={state['feature_flags']['chat_history_enabled']}, "
        f"confirmations={state['feature_flags']['can_handle_confirmations']}"
    )

    # ========================================================================
    # EPISODIC PROJECT RECALL (pre-classification short-circuit)
    # ========================================================================
    # Only meaningful when we can identify the user and persist the offer across turns.
    if user_id and session_id:
        try:
            if _handle_episodic_recall(state, user_id, session_id, user_input):
                state["agent_path"].append("episodic_recall")
                return state
        except Exception as e:
            logging.warning(f"[ROUTE_CLASSIFIER] Episodic recall check failed (continuing to classify): {e}")

    # ========================================================================
    # CLASSIFY INPUT (Inline LLM Classification)
    # ========================================================================
    try:
        # Initialize LLM
        llm = get_flash_llm(temperature=0.1)

        # Build classification chain
        classification_chain = (
            ChatPromptTemplate.from_template(CLASSIFICATION_PROMPT)
            | llm
            | StrOutputParser()
        )

        # Get classification
        classification_response = classification_chain.invoke({
            "current_page": current_page,
            "user_input": state["user_input"]
        })

        # Clean and parse JSON response
        cleaned_response = classification_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Preprocess JSON to handle literal control characters inside string values
        cleaned_response = escape_newlines_in_json(cleaned_response)

        try:
            classification_result = json.loads(cleaned_response)
        except json.JSONDecodeError:
            logging.warning(f"[ROUTE_CLASSIFIER] JSON parse error, trying ast.literal_eval. Response: {cleaned_response[:100]}")
            classification_result = ast.literal_eval(cleaned_response)
            if not isinstance(classification_result, dict):
                 raise ValueError("Parsed content is not a dictionary")

        # Extract classification fields
        category = (classification_result.get("category") or "").lower().strip()
        target_page = (classification_result.get("target_page") or current_page).lower().strip()
        requires_routing = classification_result.get("requires_routing", False)
        direct_response = classification_result.get("direct_response", "")
        reasoning = classification_result.get("reasoning", "")

        # Validate target_page
        if target_page not in ["solution", "chat", "search"]:
            target_page = current_page

        # Check if routing to different page
        routing_urls = {
            "solution": "/solution",
            "chat": "/chat",
            "search": "/search"
        }
        if requires_routing and target_page != current_page:
            routing_url = routing_urls.get(target_page, f"/{target_page}")
        else:
            routing_url = ""

        # Update state with classification result
        state["route_category"] = category
        state["target_page"] = target_page
        state["requires_routing"] = requires_routing and target_page != current_page
        state["requires_confirmation"] = False
        state["routing_url"] = routing_url
        state["direct_response"] = direct_response
        state["routing_reasoning"] = reasoning

        logging.info(
            f"[ROUTE_CLASSIFIER] Classification: {state['route_category']} | "
            f"Target: {state['target_page']} | "
            f"Requires Routing: {state['requires_routing']}"
        )

        return state

    except Exception as e:
        logging.exception(f"[ROUTE_CLASSIFIER] Classification failed: {e}")

        # P0.12 FIX: Always set error state so downstream consumers can detect the failure
        state["error"] = str(e)

        # Notify admin of classification failure
        _notify_failure("Router Classification",
            f"Router classification failed: {str(e)}",
            state=state,
            page=current_page or 'unknown',
            user_input=user_input[:200], current_page=current_page)

        # Fallback Logic:
        # If classification fails (API error, safety filter, etc.), default to staying on the current page.
        # This assumes the user likely wants to continue their current task.
        if current_page in ["solution", "chat", "search"]:
            logging.info(f"[ROUTE_CLASSIFIER] Fallback: Defaulting to current page '{current_page}' workflow")
            state["route_category"] = f"route_{current_page}"
            state["target_page"] = current_page
            state["requires_routing"] = False
            state["requires_confirmation"] = False
            state["routing_url"] = ""
        else:
            # Only return error if we have no valid context to fall back to
            state["route_category"] = "error"
            state["target_page"] = current_page
            state["requires_routing"] = False
            state["requires_confirmation"] = False
            state["routing_url"] = ""
            state["direct_response"] = "I'm having trouble processing your request but I've notified the system. Please try again."

        return state


# ============================================================================
# CONDITIONAL ROUTING FUNCTION
# ============================================================================

def route_to_workflow(state: AgenticSystemState) -> Literal["direct_response_node", "routing_response_node", "solution_workflow", "search_workflow", "chat_workflow", "admin_workflow"]:
    """
    Conditional edge function - determines which node/workflow to execute next.

    Args:
        state: Current state with routing classification

    Returns:
        Name of the next node to execute
    """
    category = state.get("route_category", "unknown")
    requires_routing = state.get("requires_routing", False)
    target_page = state.get("target_page", "solution")
    current_page = state.get("current_page", "solution")

    # Non-routing categories - return direct response
    if category in NON_ROUTING_CATEGORIES or category == "error":
        logging.info(f"[ROUTE_CLASSIFIER] Routing to direct_response_node (category: {category})")
        return "direct_response_node"

    # Check if routing to different page
    if requires_routing and target_page != current_page:
        logging.info(f"[ROUTE_CLASSIFIER] Routing to routing_response_node (target: {target_page}, current: {current_page})")
        return "routing_response_node"

    # Same page routing - route to appropriate workflow
    if category == "route_solution" or target_page == "solution":
        logging.info("[ROUTE_CLASSIFIER] Routing to solution_workflow")
        return "solution_workflow"
    elif category == "route_chat" or target_page == "chat":
        logging.info("[ROUTE_CLASSIFIER] Routing to chat_workflow")
        return "chat_workflow"
    elif category == "route_search" or target_page == "search":
        logging.info("[ROUTE_CLASSIFIER] Routing to search_workflow")
        return "search_workflow"
    else:
        # Default fallback
        logging.warning(f"[ROUTE_CLASSIFIER] Unknown category: {category}, defaulting to direct_response_node")
        return "direct_response_node"


# ============================================================================
# DIRECT RESPONSE NODE (for non-routing categories)
# ============================================================================

def direct_response_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Handle non-routing responses (greetings, chitchat, questions).
    Returns direct response without navigating to a different workflow.

    Args:
        state: Current state with direct_response populated

    Returns:
        State with final_response set
    """
    state["agent_path"].append("direct_response")

    logging.info(f"[DIRECT_RESPONSE] Returning direct response for category: {state.get('route_category')}")

    final_response = {
        "type": "direct",
        "category": state.get("route_category", "unknown"),
        "message": state.get("direct_response", ""),
        "current_page": state.get("current_page", "solution"),
        "requires_routing": False,
        "requires_confirmation": state.get("requires_confirmation", False),
        "reasoning": state.get("routing_reasoning", "")
    }

    # Surface episodic recall data (candidates / retrieved project / modifications)
    recall_response = state.get("recall_response")
    if recall_response:
        final_response["recall"] = recall_response

    state["final_response"] = final_response

    return state


def routing_response_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Handle routing to different page with session-based query storage.
    Returns routing information for frontend to display clickable link.

    Args:
        state: Current state with routing information populated

    Returns:
        State with final_response containing routing data
    """
    state["agent_path"].append("routing_response")

    logging.info(
        f"[ROUTING_RESPONSE] Returning routing info - "
        f"target: {state.get('target_page')}, "
        f"url: {state.get('routing_url')}"
    )

    state["final_response"] = {
        "type": "routing",
        "category": state.get("route_category", "unknown"),
        "message": state.get("direct_response", ""),
        "routing_url": state.get("routing_url", ""),
        "target_page": state.get("target_page", ""),
        "current_page": state.get("current_page", "solution"),
        "original_query": state.get("user_input", ""),
        "requires_routing": True,
        "requires_confirmation": False,
        "reasoning": state.get("routing_reasoning", "")
    }

    return state


# ============================================================================
# PLACEHOLDER WORKFLOW NODES (to be implemented)
# ============================================================================

def solution_workflow_placeholder(state: AgenticSystemState) -> AgenticSystemState:
    """Placeholder for Solution Workflow Agent (to be implemented)."""
    state["agent_path"].append("solution_workflow")
    state["final_response"] = {
        "type": "workflow",
        "workflow": "solution",
        "message": "[PLACEHOLDER] Solution workflow not yet implemented. This will handle instrument identification and vendor search.",
        "next_step": "identify_instruments"
    }
    return state

def chat_workflow_node(state: AgenticSystemState) -> AgenticSystemState:
    """Execute Chat RAG query for product information."""
    state["agent_path"].append("chat_workflow")

    user_input = state.get("user_input", "")
    session_id = state.get("session_id", "default")
    user_id = state.get("user_id")

    logging.info(f"[CHAT_WORKFLOW] Processing RAG query: {user_input[:100]}...")

    try:
        # Execute the RAG query
        result = process_chat_request(user_input, session_id, user_id)

        # Build the final response
        state["final_response"] = {
            "type": "direct",
            "category": "route_chat",
            "message": result.get("answer", ""),
            "source": result.get("source", "llm"),
            "found_in_database": result.get("found_in_database", False),
            "sources_used": result.get("sources_used", []),
            "user_context_used": result.get("user_context_used", False),
            "results_count": result.get("results_count", 0)
        }

        logging.info("[CHAT_WORKFLOW] RAG query completed successfully")

    except Exception as e:
        logging.exception(f"[CHAT_WORKFLOW] Error processing query: {e}")

        # Notify admin
        _notify_failure("Router Chat Workflow",
            f"Chat workflow processing error: {str(e)}",
            state=state,
            page='chat', user_query=state.get("user_input", "")[:200])

        state["final_response"] = {
            "type": "direct",
            "category": "error",
            "message": "I'm sorry, I encountered an error while searching the vendor database. Please try again or rephrase your question."
        }

    return state

def search_workflow_placeholder(state: AgenticSystemState) -> AgenticSystemState:
    """Placeholder for Search Workflow Agent (to be implemented)."""
    state["agent_path"].append("search_workflow")
    state["final_response"] = {
        "type": "workflow",
        "workflow": "search",
        "message": "[PLACEHOLDER] Search workflow not yet implemented. This will handle product search and validation.",
        "next_step": "validation"
    }
    return state

def admin_workflow_placeholder(state: AgenticSystemState) -> AgenticSystemState:
    """Placeholder for Admin Workflow Agent (to be implemented)."""
    state["agent_path"].append("admin_workflow")
    state["final_response"] = {
        "type": "workflow",
        "workflow": "admin",
        "message": "[PLACEHOLDER] Admin workflow not yet implemented. This will handle user/project management.",
        "next_step": "auth"
    }
    return state


# ============================================================================
# BUILD THE ROUTE CLASSIFIER GRAPH (delegated to workflows layer)
# ============================================================================

def build_router_classifier_graph():
    """Build the Route Classifier graph. Delegates to workflows layer."""
    from domain.orchestrator.workflows.router_workflow import build_router_classifier_graph as _build
    return _build()


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_router_classifier_health():
    """
    Health check for Router Classifier Agent
    Tests: Graph compilation, LLM, prompt file, notification manager

    Returns:
        AgentHealthStatus with detailed dependency status
    """
    from common.monitoring.usage import (
        AgentHealthChecker,
        AgentHealthStatus,
        DependencyStatus,
        agent_metrics_tracker,
    )

    checker = AgentHealthChecker()
    dependencies = {}
    status = "healthy"
    error_msg = None

    try:
        # 1. Test graph compilation
        try:
            from domain.orchestrator.workflows.router_workflow import build_router_classifier_graph
            graph = build_router_classifier_graph()
            dependencies["graph_compilation"] = DependencyStatus("graph", "available")
        except Exception as e:
            dependencies["graph_compilation"] = DependencyStatus("graph", "unavailable", str(e))
            status = "unhealthy"

        # 2. Test LLM connectivity
        dependencies["llm"] = checker.check_llm_connectivity("google")
        if dependencies["llm"].status == "unavailable":
            status = "unhealthy"

        # 3. Test prompt file
        prompt_path = os.path.join(_PROMPTS_DIR, 'router_classification_prompt.md')
        dependencies["prompt_file"] = checker.check_prompt_file(prompt_path)
        if dependencies["prompt_file"].status == "unavailable":
            status = "unhealthy"

        # 4. Test notification manager import (non-critical)
        try:
            dependencies["notification_manager"] = DependencyStatus("notification_manager", "available")
        except Exception as e:
            dependencies["notification_manager"] = DependencyStatus("notification_manager", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"  # Non-critical dependency

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logging.error(f"[AGENT_HEALTH] Router classifier health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="router_classifier",
        status=status,
        dependencies=dependencies,
        metrics=agent_metrics_tracker.get_metrics("router_classifier"),
        last_check=datetime.now(),
        error_message=error_msg
    )


# ============================================================================
# EXPORT
# ============================================================================

# Build and export handled by workflow now. We expose it for backward compat.
from domain.orchestrator.workflows.router_workflow import router_classifier_agent

__all__ = ["router_classifier_agent", "build_router_classifier_graph", "check_router_classifier_health"]
