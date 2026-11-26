import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Literal, Any
from langgraph.graph import END, StateGraph

from common.helpers.notifications import notify_failure as _notify_failure
from common.helpers.node_retry import is_transient_error
from domain.orchestrator.state import AgenticSystemState
from domain.search.agents.search_agent import (
    restore_state_from_memory,
    classify_search_intent,
    extract_requirements,
    detect_product_type,
    validate_and_map_schema,
    load_pdf_content,
    perform_vendor_analysis,
    generate_llm_response,
    handle_error,
    generate_final_response,
    route_after_intent,
    route_after_llm_response
)
from domain.search.agents.update_agent import update_agent
from domain.search.agents.identify_vendors_agent import identify_vendors_agent
from domain.search.agents.vendor_ranking_agent import vendor_ranking_agent

logger = logging.getLogger(__name__)

# Checkpoint-based resume is opt-in (default OFF) so production behavior is
# unchanged until explicitly enabled and integration-tested. When enabled, the
# search graph is compiled with an in-process MemorySaver and, on a transient
# node failure, re-invoked to resume from the last completed node.
SEARCH_ENABLE_CHECKPOINT = os.getenv("SEARCH_ENABLE_CHECKPOINT", "false").lower().strip() in ("1", "true", "yes")
SEARCH_MAX_RESUME_ATTEMPTS = 2


def _build_checkpointer():
    """Return an in-process MemorySaver when checkpoint-resume is enabled, else None.
    MemorySaver holds state in memory (no serialization), so it is safe for the
    workflow's rich state but only resumes within a single process."""
    if not SEARCH_ENABLE_CHECKPOINT:
        return None
    try:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    except Exception as e:
        logger.warning(f"[SEARCH] Checkpointer unavailable; continuing without resume: {e}")
        return None


def create_search_workflow(checkpointer=None) -> StateGraph:
    """
    Create the ORCHESTRATED search workflow graph with workflow step management.

    NEW FLOW (LLM-Orchestrated):
    =============================
    search_intent (classify intent + decide routing)
      ├─> productRequirements → generate_llm_response (validation message)
      │     └─> If skip_full_workflow=False → extract_requirements → full pipeline
      │     └─> If skip_full_workflow=True → END (wait for user)
      │
      ├─> workflow → generate_llm_response → END (step transition message)
      ├─> clarification → generate_llm_response → END (ask question)
      ├─> reset → generate_llm_response → END (reset message)
      └─> router_needed → generate_llm_response → END (router message)

    FULL SEARCH PIPELINE (when triggered):
    ======================================
    extract_requirements → detect_product_type → validate_and_map_schema →
    identify_vendors_agent → load_pdf_content →
    perform_vendor_analysis → vendor_ranking_agent → generate_response → END
    """
    # Create the workflow graph
    workflow = StateGraph(AgenticSystemState)

    # Add all nodes
    workflow.add_node("restore_state", restore_state_from_memory)
    workflow.add_node("search_intent", classify_search_intent)
    workflow.add_node("generate_llm_response", generate_llm_response)
    workflow.add_node("extract_requirements", extract_requirements)
    workflow.add_node("update_agent", update_agent)
    workflow.add_node("detect_product_type", detect_product_type)
    workflow.add_node("validate_and_map_schema", validate_and_map_schema)
    workflow.add_node("identify_vendors_agent", identify_vendors_agent)
    workflow.add_node("load_pdf_content", load_pdf_content)
    workflow.add_node("perform_vendor_analysis", perform_vendor_analysis)
    workflow.add_node("vendor_ranking_agent", vendor_ranking_agent)
    workflow.add_node("generate_response", generate_final_response)
    workflow.add_node("handle_error", handle_error)

    # Entry point: restore persisted state before intent classification
    workflow.set_entry_point("restore_state")
    workflow.add_edge("restore_state", "search_intent")

    # ========================================================================
    # CONDITIONAL ROUTING FROM INTENT CLASSIFICATION (ORCHESTRATOR)
    # ========================================================================
    workflow.add_conditional_edges(
        "search_intent",
        route_after_intent,
        {
            "extract_requirements": "extract_requirements",
            "update_agent": "update_agent",
            "generate_response": "generate_llm_response",
            "handle_error": "handle_error"
        }
    )

    # ========================================================================
    # FULL SEARCH PIPELINE (Linear Flow)
    # ========================================================================
    # From extract_requirements
    workflow.add_edge("extract_requirements", "generate_llm_response")

    # From update_agent
    workflow.add_edge("update_agent", "generate_llm_response")

    # From generate_llm_response - conditional
    workflow.add_conditional_edges(
        "generate_llm_response",
        route_after_llm_response,
        {
            "continue_workflow": "detect_product_type",
            "end": "generate_response"
        }
    )

    # Linear pipeline for full search
    workflow.add_edge("detect_product_type", "validate_and_map_schema")
    workflow.add_edge("validate_and_map_schema", "identify_vendors_agent")
    workflow.add_edge("identify_vendors_agent", "load_pdf_content")
    workflow.add_edge("load_pdf_content", "perform_vendor_analysis")
    workflow.add_edge("perform_vendor_analysis", "vendor_ranking_agent")
    workflow.add_edge("vendor_ranking_agent", "generate_response")

    # Terminal nodes
    workflow.add_edge("generate_response", END)
    workflow.add_edge("handle_error", END)

    # CRITICAL: Set recursion_limit to prevent infinite graph cycling.
    # The search workflow should complete in at most ~15 node traversals.
    # Without this, LangGraph defaults to 25 which still allows harmful loops.
    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# MAIN EXECUTION FUNCTION
# ============================================================================

def run_search_workflow(user_input: str, **kwargs) -> dict[str, Any]:
    """
    Run the complete search workflow.

    Args:
        user_input: User's natural language product requirements
        **kwargs: Additional parameters (standards, PDFs, etc.)

    Returns:
        Dict with complete analysis results
    """
    session_id = kwargs.get("session_id", "unknown")
    stream_id = kwargs.get("stream_id", "unknown")
    logger.info(
        f"[SEARCH_WORKFLOW] run_search_workflow ENTER — "
        f"session_id={session_id!r} "
        f"stream_id={stream_id!r} "
        f"thread={threading.current_thread().name} "
        f"active_threads={threading.active_count()} "
        f"user_input_len={len(user_input)} "
        f"kwargs_keys={list(kwargs.keys())}"
    )
    try:
        # Initialize state
        initial_state = AgenticSystemState(
            user_input=user_input,
            current_agent="search_workflow",
            agent_status="running",
            agent_path=[],
            **kwargs
        )

        # Create the workflow (optionally with a checkpointer for resume).
        checkpointer = _build_checkpointer()
        workflow = create_search_workflow(checkpointer=checkpointer)

        # CRITICAL: recursion_limit prevents infinite graph cycling (cap 20).
        config = {"recursion_limit": 20}
        if checkpointer is not None:
            # Stable thread_id so a resumed invoke continues the same run.
            thread_id = (
                kwargs.get("stream_id")
                or kwargs.get("search_session_id")
                or kwargs.get("session_id")
                or uuid.uuid4().hex
            )
            config["configurable"] = {"thread_id": thread_id}

        # When a checkpointer is active, a TRANSIENT node failure triggers a
        # resume from the last completed node (re-running only the failed node +
        # downstream). Without a checkpointer this runs exactly once (unchanged).
        attempts = SEARCH_MAX_RESUME_ATTEMPTS if checkpointer is not None else 1
        for attempt in range(1, attempts + 1):
            try:
                graph_input = initial_state if attempt == 1 else None
                logger.info(
                    f"[SEARCH_WORKFLOW] Invoking graph — attempt={attempt}/{attempts} "
                    f"session_id={session_id!r} "
                    f"thread={threading.current_thread().name}"
                )
                result = workflow.invoke(graph_input, config=config)
                logger.info(
                    f"[SEARCH_WORKFLOW] Graph completed — "
                    f"session_id={session_id!r} "
                    f"attempt={attempt} "
                    f"result_keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__} "
                    f"has_agent_response={'agent_response' in result if isinstance(result, dict) else False}"
                )
                return result.get('agent_response', {})
            except Exception as inner_exc:
                if attempt < attempts and is_transient_error(inner_exc):
                    logger.warning(
                        f"[SEARCH_AGENT] Transient failure; resuming from last checkpoint "
                        f"(attempt {attempt}/{attempts}): {inner_exc}"
                    )
                    continue
                raise

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Workflow execution failed: {e}")

        # Notify admin of the workflow execution failure
        _notify_failure(
            "Search Workflow Execution",
            f"Search Workflow execution failed: {str(e)}",
            initial_state,
            user_input=user_input
        )

        return {
            "error": f"Workflow execution failed: {str(e)}",
            "success": False,
            "timestamp": datetime.now().isoformat()
        }


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_search_agent_health():
    """
    Health check for Search Agent
    Tests: Graph compilation, LLM, MongoDB, agents, prompts, conversation memory

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
            create_search_workflow()
            dependencies["graph_compilation"] = DependencyStatus("graph", "available")
        except Exception as e:
            dependencies["graph_compilation"] = DependencyStatus("graph", "unavailable", str(e))
            status = "unhealthy"

        # 2. Test LLM connectivity (checks API key only, no actual call)
        dependencies["llm"] = checker.check_llm_connectivity("deepinfra")
        if dependencies["llm"].status == "unavailable":
            status = "unhealthy"

        # 3. Test MongoDB collections
        dependencies["mongodb_vendors"] = checker.check_mongodb_collection("vendors")
        if dependencies["mongodb_vendors"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_specs"] = checker.check_mongodb_collection("specs")
        if dependencies["mongodb_specs"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_advanced_specs"] = checker.check_mongodb_collection("advanced_specifications")
        if dependencies["mongodb_advanced_specs"].status == "unavailable":
            status = "unhealthy"

        # 4. Test agent imports
        dependencies["validation_agent"] = checker.check_agent_importable(
            "search.agents.validation_agent", "run_validation_agent"
        )
        if dependencies["validation_agent"].status == "unavailable":
            status = "unhealthy"

        dependencies["vendor_analysis_agent"] = checker.check_agent_importable(
            "search.agents.vendor_analysis_agent", "run_vendor_analysis"
        )
        if dependencies["vendor_analysis_agent"].status == "unavailable":
            status = "unhealthy"

        dependencies["advanced_specs_agent"] = checker.check_agent_importable(
            "search.agents.advanced_specs_agent", "run_advanced_specs_discovery"
        )
        if dependencies["advanced_specs_agent"].status == "unavailable":
            status = "unhealthy"

        dependencies["summary_agent"] = checker.check_agent_importable(
            "search.agents.summary_agent", "generate_summary"
        )
        if dependencies["summary_agent"].status == "unavailable":
            status = "unhealthy"

        # 5. Test prompt files
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

        dependencies["prompt_search_agent"] = checker.check_prompt_file(
            os.path.join(prompt_dir, "search_agent.md")
        )
        if dependencies["prompt_search_agent"].status == "unavailable":
            status = "unhealthy"

        dependencies["prompt_deep_analysis"] = checker.check_prompt_file(
            os.path.join(prompt_dir, "vendor_analysis_agent.md")
        )
        if dependencies["prompt_deep_analysis"].status == "unavailable":
            status = "unhealthy"

        # 6. Test conversation memory (non-critical)
        try:
            dependencies["conversation_memory"] = DependencyStatus("conversation_memory", "available")
        except Exception as e:
            dependencies["conversation_memory"] = DependencyStatus("conversation_memory", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"  # Non-critical

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[AGENT_HEALTH] Search agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="search",
        status=status,
        dependencies=dependencies,
        metrics=agent_metrics_tracker.get_metrics("search"),
        last_check=datetime.now(),
        error_message=error_msg
    )



