"""
Agent executors for the benchmark runner.

Each executor runs one test case against the *real* production workflow graph
(chat / search / solution), invoking the compiled LangGraph directly so we can
capture both the final response and the ``agent_path`` (the ordered list of
nodes that executed). All LLM calls inside these executors are attributed to the
active benchmark test via the thread-local benchmark context.

Returns a normalised output dict consumed by the runner's validation + reporting:
    {
        "response": str, "intent": str, "success": bool,
        "agent_path": [str, ...], "response_length": int,
        ... agent-specific count fields ...
    }
"""
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def run_chat(test_input: dict[str, Any]) -> dict[str, Any]:
    """Execute one chat-agent test case against the chat workflow graph."""
    from domain.chat.workflows.chat_workflow import create_chat_workflow
    from common.ai.memory import add_conversation_turn, clear_chat_memory

    user_query = test_input["user_query"]
    session_id = test_input.get("session_id", "benchmark_session")
    user_id = test_input.get("user_id")

    # Isolate the session, then seed any provided multi-turn history.
    clear_chat_memory(session_id)
    for turn in test_input.get("conversation_history", []) or []:
        add_conversation_turn(session_id=session_id, role=turn.get("role", "user"), content=turn.get("content", ""))

    state = {
        "user_input": user_query,
        "session_id": session_id,
        "user_id": user_id,
        "current_page": "chat",
        "agent_path": [],
        "timestamp": datetime.now(),
    }
    result_state = create_chat_workflow().invoke(state)
    result = result_state.get("final_response", {}) or {}
    agent_path = result_state.get("agent_path", []) or []

    response_text = result.get("answer", "") or result.get("response", "") or result.get("message", "")
    if not result.get("is_chat_related", True):
        classification = "INVALID"
    elif result.get("is_followup", False):
        classification = "VALID_FOLLOWUP"
    else:
        classification = "VALID_NEW_QUERY"

    return {
        "response": response_text,
        "intent": classification,
        "success": bool(result.get("success", bool(response_text))),
        "agent_path": agent_path,
        "response_length": len(response_text),
        "classification": classification,
        "source": result.get("source", ""),
    }


def run_search(test_input: dict[str, Any]) -> dict[str, Any]:
    """Execute one search-agent test case against the search workflow graph."""
    from domain.orchestrator.state import AgenticSystemState
    from domain.search.workflows.search_workflow import create_search_workflow

    user_query = test_input["user_query"]
    session_id = test_input.get("session_id", "benchmark_session")

    state = AgenticSystemState(
        user_input=user_query,
        current_agent="search_workflow",
        agent_status="running",
        agent_path=[],
        session_id=session_id,
        search_session_id=session_id,
        user_id=test_input.get("user_id"),
        stream_id=None,
        enable_streaming=False,
        workflow_step=test_input.get("workflow_step", "initialInput"),
        current_intent=test_input.get("current_intent"),
        skip_standards=test_input.get("skip_standards", True),
    )
    # recursion_limit mirrors run_search_workflow's safety cap.
    result_state = create_search_workflow().invoke(state, config={"recursion_limit": 20})

    agent_path = result_state.get("agent_path", []) or []
    agent_response = result_state.get("agent_response", {}) or {}
    products = (
        agent_response.get("vendor_matches")
        or agent_response.get("overall_ranking", {}).get("ranked_products")
        or result_state.get("ranked_products")
        or []
    )
    response_text = (
        agent_response.get("message")
        or result_state.get("message")
        or ""
    )

    return {
        "response": response_text,
        "intent": result_state.get("search_intent") or result_state.get("current_intent") or "productRequirements",
        "success": bool(result_state.get("success", bool(response_text or products))),
        "agent_path": agent_path,
        "response_length": len(response_text),
        "results_count": len(products),
        "detected_product_type": result_state.get("detected_product_type", ""),
        "has_missing_fields": result_state.get("has_missing_fields", False),
        "total_products_found": result_state.get("total_found", 0),
    }


def run_solution(test_input: dict[str, Any]) -> dict[str, Any]:
    """Execute one solution-agent test case against the solution workflow graph."""
    from domain.orchestrator.state import AgenticSystemState
    from domain.solution.workflows.solution_workflow import create_solution_agent

    user_query = test_input["user_query"]
    session_id = test_input.get("session_id", "benchmark_session")
    skip_standards = test_input.get("skip_standards", True)

    state: AgenticSystemState = {
        "user_input": user_query,
        "current_page": "solution",
        "session_id": session_id,
        "user_session_id": session_id,
        "user_id": test_input.get("user_id"),
        "instruments": test_input.get("current_instruments", []),
        "accessories": test_input.get("current_accessories", []),
        "context_memory": [],
        "workflow_data": {},
        "agent_path": [],
        "timestamp": datetime.now(),
        "stream_id": None,
        "enable_streaming": False,
        "skip_standards": skip_standards,
    }
    result_state = create_solution_agent().invoke(state)
    result = result_state.get("final_response", {}) or {}
    agent_path = result_state.get("agent_path", []) or []

    instruments = result.get("instruments") or []
    accessories = result.get("accessories") or []
    response_text = result.get("message", "") or ""

    return {
        "response": response_text,
        "intent": result.get("intent", "unknown"),
        "success": bool(result.get("success", bool(instruments or response_text))),
        "agent_path": agent_path,
        "response_length": len(response_text),
        "solutions_count": len(instruments),
        "instruments_count": len(instruments),
        "accessories_count": len(accessories),
        "standards_applied": result.get("standards_applied", False),
        "skip_standards": skip_standards,
        "clarification_needed": result.get("clarification_needed", False),
    }


# Dispatch table keyed by suite ``agent_type``.
EXECUTORS = {
    "chat": run_chat,
    "search": run_search,
    "solution": run_solution,
}


def execute(agent_type: str, test_input: dict[str, Any]) -> dict[str, Any]:
    """Run a single test case for the given agent type. Errors are captured, not raised."""
    executor = EXECUTORS.get(agent_type)
    if executor is None:
        return {"error": f"Unknown agent type: {agent_type}", "agent_path": [], "success": False}
    try:
        return executor(test_input)
    except Exception as e:  # noqa: BLE001 — a failing test must not abort the suite
        logger.error("[BENCHMARK] %s agent execution failed: %s", agent_type, e, exc_info=True)
        return {"error": str(e), "agent_path": [], "success": False, "response": "", "response_length": 0}
