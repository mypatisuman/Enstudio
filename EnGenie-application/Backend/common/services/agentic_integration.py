"""
Agentic Integration Layer

This module provides wrapper functions that integrate the agentic workflows
with the FastAPI endpoints, maintaining backward compatibility with the frontend.

These functions:
1. Accept request data
2. Convert to agentic state format
3. Call the appropriate agentic workflow
4. Convert response back to API format (camelCase)
"""

import logging
from datetime import datetime
from typing import Any

from common.helpers.response_formatter import convert_keys_to_camel_case

logger = logging.getLogger(__name__)


# ============================================================================
# SOLUTION AGENT INTEGRATION
# ============================================================================

def run_project_intent(
    user_input: str,
    current_instruments: list[dict] = None,
    current_accessories: list[dict] = None,
    awaiting_single_item_confirmation: bool = False,
    awaiting_holistic_confirmation: bool = False,
    search_session_id: str = None,
    user_session_id: str = None,
    user_id: int = None,
    context_memory: list[dict] = None,
    stream_id: str = None,
    enable_streaming: bool = False,
    skip_standards: bool = False
) -> dict[str, Any]:
    """
    Run solution agent which handles all solution page processing internally.

    The agent internally:
    - Classifies intent (requirements/modification/clarification)
    - Routes to appropriate tools
    - Identifies/modifies instruments
    - Applies standards
    - Returns complete response

    Also manages conversation history for contextual engineering.
    """
    try:
        from domain.orchestrator.state import AgenticSystemState
        from common.ai.memory import add_conversation_turn, get_latest_instruments_and_accessories
        from domain.solution.workflows.solution_workflow import create_solution_agent

        # Per-user fallback: if the frontend ever omits/loses the session id, an
        # authenticated user gets a fallback scoped to THEM (never the bare
        # "default" literal shared by every caller that hits this branch) so
        # two different logged-in users can never collide on the same gate/
        # conversation memory. Anonymous callers (user_id is None) still share
        # the literal "default" -- there is no user_id to disambiguate them,
        # and unauthenticated collision is an accepted, documented residual gap.
        session_id = search_session_id or (f"default-user-{user_id}" if user_id else "default")

        # Store user message in conversation history
        add_conversation_turn(
            session_id=session_id,
            role="user",
            content=user_input
        )

        # Episodic recall now runs INSIDE the graph as its entry-point node
        # (domain/solution/agents/episodic_recall_agent.py); a saved-project offer
        # surfaces through final_response as the cache_confirmation contract.

        # Auto-load instruments/accessories from memory if not provided
        if not current_instruments and not current_accessories:
            logger.info(f"[AGENTIC_INTEGRATION] No instruments/accessories provided, loading from memory for session {session_id}")
            memory_data = get_latest_instruments_and_accessories(session_id)
            current_instruments = memory_data.get("instruments", [])
            current_accessories = memory_data.get("accessories", [])
            if current_instruments or current_accessories:
                logger.info(f"[AGENTIC_INTEGRATION] ? Loaded {len(current_instruments)} instruments and {len(current_accessories)} accessories from memory")

        # Build initial state
        initial_state: AgenticSystemState = {
            "user_input": user_input,
            "current_page": "solution",
            "session_id": session_id,
            "user_session_id": user_session_id,
            "user_id": user_id,
            "instruments": current_instruments or [],
            "accessories": current_accessories or [],
            "context_memory": context_memory or [],
            "workflow_data": {
                "awaiting_single_item_confirmation": awaiting_single_item_confirmation,
                "awaiting_holistic_confirmation": awaiting_holistic_confirmation,
            },
            "agent_path": [],
            "timestamp": datetime.now(),
            "stream_id": stream_id,
            "enable_streaming": enable_streaming,
            "skip_standards": skip_standards
        }

        # The session's current P&ID. Without this every turn started with no
        # drawing, so a modification regenerated the P&ID from scratch instead
        # of extending it (BrownfieldPIDAgent.update_existing_pid never ran).
        from domain.solution.services.pid_session_service import (
            load_active as load_active_pid, persist_turn_result)
        active_pid = load_active_pid(user_id, session_id)
        if active_pid:
            initial_state["active_pid_graph"] = active_pid
            logger.info(f"[AGENTIC_INTEGRATION] Loaded P&ID revision {active_pid.get('revision')} "
                        f"({len(active_pid.get('nodes') or [])} nodes) for session {session_id}")

        # Create and run agent
        agent = create_solution_agent()
        result = agent.invoke(initial_state)

        # Get final response
        final_response = result.get("final_response", {})

        # Store a drawing this turn produced, and stamp the response with its
        # session_id and revision so the P&ID Studio can confirm or clarify.
        persist_turn_result(user_id, session_id, final_response)

        # Store agent response in conversation history with complete state.
        # Skip cache_confirmation: the episodic_recall node already stored the
        # offer turn (with cache_confirmation metadata) — adding it again here
        # would double-log the offer.
        agent_message = final_response.get("message", "")
        if agent_message and final_response.get("intent") != "cache_confirmation":
            add_conversation_turn(
                session_id=session_id,
                role="assistant",
                content=agent_message,
                metadata={
                    "intent": final_response.get("intent"),
                    "response_type": final_response.get("response_type"),
                    "instruments": final_response.get("instruments", []),  # Store complete list
                    "accessories": final_response.get("accessories", []),  # Store complete list
                    "instruments_count": len(final_response.get("instruments", [])),
                    "accessories_count": len(final_response.get("accessories", [])),
                    # Gate-consolidated requirement (original + chat answers) —
                    # read back at save time to build the episodic input signature.
                    **({"consolidated_requirements": final_response["consolidated_requirements"]}
                       if final_response.get("consolidated_requirements") else {}),
                }
            )

        # Add stream_id to response for frontend streaming
        if stream_id:
            final_response["stream_id"] = stream_id

        # Trigger long term memory preference reflection in the background
        if user_id:
            try:
                import threading
                from common.ai.memory import run_hybrid_memory_reflection
                threading.Thread(
                    target=run_hybrid_memory_reflection,
                    args=(user_id, session_id),
                    daemon=True
                ).start()
                logger.info(f"[AGENTIC_INTEGRATION] Spawning hybrid memory reflection thread for user_id={user_id}")
            except Exception as e:
                logger.warning(f"[AGENTIC_INTEGRATION] Failed to start hybrid memory reflection thread: {e}")

        # Record this exchange as a conversation episode (user-level episodic
        # memory): meaningful requirements turns are embedded so a future
        # re-request phrased like this CONVERSATION can be recognized by
        # episodic recall — complementing the saved-project signatures.
        if user_id:
            try:
                import threading
                from common.ai.memory import record_conversation_episode
                threading.Thread(
                    target=record_conversation_episode,
                    args=(user_id, session_id, user_input, dict(final_response)),
                    daemon=True
                ).start()
            except Exception as e:
                logger.warning(f"[AGENTIC_INTEGRATION] Failed to start episode-recording thread: {e}")

        # Convert to API format
        api_response = convert_keys_to_camel_case(final_response)

        logger.info(f"[AGENTIC_INTEGRATION] Solution agent result: {final_response.get('intent')}, streamId: {stream_id}")
        return api_response

    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Solution agent error: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Solution agent processing failed"
        }


# ============================================================================
# REDUNDANT FUNCTIONS REMOVED
# ============================================================================
# The following functions have been removed as they are redundant:
# - run_identify_instruments()  (REMOVED - use run_project_intent() instead)
# - run_modify_instruments()    (REMOVED - use run_project_intent() instead)
#
# Use run_project_intent() for all solution agent operations.
# It internally handles all intents (requirements, modification, clarification).
# ============================================================================


def run_route_classifier(
    user_input: str,
    current_page: str = "solution",
    search_session_id: str = None,
    user_session_id: str = None,
    user_id: int = None
) -> dict[str, Any]:
    """
    Run the router classifier agent to determine user intent and routing.
    """
    try:
        from domain.orchestrator.state import AgenticSystemState
        from domain.orchestrator.workflows.orchestrator_workflow import create_orchestrator_workflow

        initial_state: AgenticSystemState = {
            "user_input": user_input,
            "current_page": current_page,
            "session_id": search_session_id,
            "user_session_id": user_session_id,
            "user_id": user_id,
            "agent_path": [],
            "timestamp": datetime.now()
        }

        # Create and run agent
        agent = create_orchestrator_workflow()
        result_state = agent.invoke(initial_state)

        response = {
            "category": result_state.get("route_category", "unknown"),
            "targetPage": result_state.get("target_page", current_page),
            "requiresRouting": result_state.get("requires_routing", False),
            "directResponse": result_state.get("direct_response", "") or result_state.get("routing_message", ""),
            "routingUrl": result_state.get("routing_url", ""),
            "reasoning": result_state.get("routing_reasoning", "")
        }

        return response

    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Route classifier error: {e}")
        return {
            "category": "error",
            "targetPage": current_page,
            "requiresRouting": False,
            "directResponse": "I'm having trouble categorizing your request. Please try again.",
            "error": str(e)
        }


def run_search_intent(
    user_input: str,
    current_step: str = "initialInput",
    current_intent: str = "productRequirements",
    search_session_id: str = None,
    user_id: int = None,
    current_page: str = "search",
    product_type: str = None
) -> dict[str, Any]:
    """
    Wrapper for search intent classification.
    """
    try:
        from domain.orchestrator.state import AgenticSystemState
        from common.ai.memory import add_conversation_turn
        from domain.search.agents.search_agent import classify_search_intent

        # Per-user fallback: if the frontend ever omits/loses the session id, an
        # authenticated user gets a fallback scoped to THEM (never the bare
        # "default" literal shared by every caller that hits this branch) so
        # two different logged-in users can never collide on the same gate/
        # conversation memory. Anonymous callers (user_id is None) still share
        # the literal "default" -- there is no user_id to disambiguate them,
        # and unauthenticated collision is an accepted, documented residual gap.
        session_id = search_session_id or (f"default-user-{user_id}" if user_id else "default")

        # Log user message
        add_conversation_turn(
            session_id=session_id,
            role="user",
            content=user_input
        )

        initial_state: AgenticSystemState = {
            "user_input": user_input,
            "workflow_step": current_step,
            "current_intent": current_intent,
            "session_id": search_session_id,
            "user_id": user_id,
            "current_page": current_page,
            "agent_path": [],
            "timestamp": datetime.now(),
            "detected_product_type": product_type or "",
            "product_type": product_type or "",
        }

        result_state = classify_search_intent(initial_state)

        intent = result_state.get("search_intent", "productRequirements")
        response_msg = result_state.get("response_message", "")

        # Log assistant response if there is a direct conversational message (e.g. contextual_qna, router, clarification)
        if response_msg:
            add_conversation_turn(
                session_id=session_id,
                role="assistant",
                content=response_msg,
                metadata={"intent": intent}
            )

        return {
            "intent": intent,
            "nextStep": result_state.get("next_workflow_step", "awaitAllSpecs"),
            "resume_workflow": result_state.get("resume_workflow", True),
            "stay_at_step": result_state.get("stay_at_step", False),
            "confidence": result_state.get("intent_confidence", "medium"),
            "reasoning": result_state.get("intent_reasoning", ""),
            "message": response_msg,
            # Router fields (populated when intent is router_needed)
            "router_needed": result_state.get("router_needed", False),
            "router_category": result_state.get("router_category"),
            "router_target_page": result_state.get("router_target_page"),
            "router_requires_routing": result_state.get("router_requires_routing", False),
            "router_url": result_state.get("router_url", ""),
            "router_message": result_state.get("router_message", ""),
            "router_requires_confirmation": result_state.get("router_requires_confirmation", True),
            "router_confirmation_message": result_state.get("router_confirmation_message", ""),
            "router_opening_message": result_state.get("router_opening_message", ""),
            "router_decline_message": result_state.get("router_decline_message", ""),
            "router_popup_blocked_message": result_state.get("router_popup_blocked_message", ""),
        }
    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Search intent error: {e}")
        return {
            "intent": "productRequirements",
            "nextStep": "initialInput",
            "error": str(e)
        }


def run_search_vendors(
    category: str,
    product_name: str,
    strategy: str = None,
    specified_vendors: list[str] = None,
    specified_model_families: list[str] = None,
    applicable_standards: list[str] = None,
    standards_specs: dict = None,
    search_session_id: str = None,
    user_session_id: str = None,
    user_id: int = None
) -> dict[str, Any]:
    """
    Run vendor search via search workflow.
    """
    try:
        from common.ai.memory import add_conversation_turn
        from domain.search.workflows.search_workflow import run_search_workflow

        # Per-user fallback: if the frontend ever omits/loses the session id, an
        # authenticated user gets a fallback scoped to THEM (never the bare
        # "default" literal shared by every caller that hits this branch) so
        # two different logged-in users can never collide on the same gate/
        # conversation memory. Anonymous callers (user_id is None) still share
        # the literal "default" -- there is no user_id to disambiguate them,
        # and unauthenticated collision is an accepted, documented residual gap.
        session_id = search_session_id or (f"default-user-{user_id}" if user_id else "default")
        # Build user input from category and product name
        user_input = f"I need a {category}" if category else f"I need a {product_name}"

        # Log user request
        add_conversation_turn(session_id=session_id, role="user", content=user_input)

        # Run full search workflow
        result = run_search_workflow(
            user_input=user_input,
            user_id=user_id,
            session_id=search_session_id,
            specified_vendors=specified_vendors or [],
            specified_model_families=specified_model_families or [],
            applicable_standards=applicable_standards or [],
            standards_specs=standards_specs or {},
            procurement_strategy=strategy or ""
        )

        total_found = result.get('total_products_found', 0)
        # Log assistant completion
        add_conversation_turn(
            session_id=session_id,
            role="assistant",
            content=f"Search completed. Found {total_found} products.",
            metadata={"type": "search_results", "count": total_found}
        )

        # Convert to API format
        api_response = convert_keys_to_camel_case(result)

        # Add status field for polling compatibility
        api_response["status"] = "completed"

        logger.info(f"[AGENTIC_INTEGRATION] Search complete: {total_found} products")
        return api_response

    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Search vendors error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Search failed"
        }


def run_analyze(
    user_input: str,
    search_session_id: str = None,
    user_session_id: str = None,
    user_id: int = None,
    **kwargs
) -> dict[str, Any]:
    """
    Run full analysis via search workflow.
    """
    try:
        from common.ai.memory import add_conversation_turn
        from domain.search.workflows.search_workflow import run_search_workflow

        # Per-user fallback: if the frontend ever omits/loses the session id, an
        # authenticated user gets a fallback scoped to THEM (never the bare
        # "default" literal shared by every caller that hits this branch) so
        # two different logged-in users can never collide on the same gate/
        # conversation memory. Anonymous callers (user_id is None) still share
        # the literal "default" -- there is no user_id to disambiguate them,
        # and unauthenticated collision is an accepted, documented residual gap.
        session_id = search_session_id or (f"default-user-{user_id}" if user_id else "default")

        # Log user request
        add_conversation_turn(session_id=session_id, role="user", content=user_input)

        # Run full search workflow
        result = run_search_workflow(
            user_input=user_input,
            user_id=user_id,
            session_id=search_session_id,
            **kwargs
        )

        total_found = result.get('total_products_found', 0)
        detected_type = result.get('detected_product_type', 'unknown')

        # Log assistant completion
        add_conversation_turn(
            session_id=session_id,
            role="assistant",
            content=f"Analysis completed for {detected_type}. Found {total_found} products.",
            metadata={
                "type": "analyze_results",
                "product_type": detected_type,
                "count": total_found
            }
        )

        # Convert to API format
        api_response = convert_keys_to_camel_case(result)

        logger.info("[AGENTIC_INTEGRATION] Analysis complete")
        return api_response

    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Analyze error: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Analysis failed"
        }


# ============================================================================
# CHAT RAG INTEGRATION (SIMPLE RAG - NO AGENTS)
# ============================================================================

def run_chat_query(
    user_query: str,
    search_session_id: str = None,
    user_id: int = None
) -> dict[str, Any]:
    """
    Run chat query via chat agent (not complex agents).

    Uses chat_agent.py directly for fast response (~2-3 LLM calls).
    The agentic chat_workflow_agent.py is NOT used (too slow, ~6+ LLM calls).

    Replaces: /api/chat/query endpoint

    Args:
        user_query: User's question
        search_session_id: Session ID
        user_id: User ID

    Returns:
        Dict matching old API response format (camelCase keys)
    """
    try:
        # Use chat agent directly (NOT the complex agent workflow)
        from domain.chat.agents.chat_agent import query_chat

        # Run chat query
        result = query_chat(
            user_query=user_query,
            session_id=search_session_id or "default",
            user_id=user_id
        )

        # Convert to API format matching old response
        api_response = {
            "answer": result.get("answer", ""),
            "source": result.get("source", "database"),
            "query": result.get("original_query", user_query),
            "resolvedQuery": result.get("resolved_query", user_query),
            "isFollowup": result.get("resolved_query") is not None and result.get("resolved_query") != user_query,
            "collectionsSearched": result.get("collections_searched", []),
            "resultsCount": result.get("results_count", 0),
            "pdfDocumentsCount": result.get("pdf_documents_used", 0),
            "queryIntent": result.get("query_intent", "general_info"),
            "foundInDatabase": result.get("found_in_database", False),
            "awaitingConfirmation": result.get("awaiting_confirmation", False),
            "userContextUsed": result.get("user_context_used", False),
            "success": True
        }

        logger.info(f"[AGENTIC_INTEGRATION] Chat RAG complete: source={api_response['source']}, found={api_response['foundInDatabase']}")
        return api_response

    except Exception as e:
        logger.exception(f"[AGENTIC_INTEGRATION] Chat query error: {e}")
        return {
            "answer": "I'm having trouble processing your query. Please try again.",
            "source": "error",
            "success": False,
            "error": str(e)
        }


# ============================================================================
# FEATURE FLAG: USE AGENTIC
# ============================================================================

# Set this to True to use agentic backend, False to use old logic
USE_AGENTIC_BACKEND = True

def should_use_agentic() -> bool:
    """Check if agentic backend should be used."""
    return USE_AGENTIC_BACKEND

