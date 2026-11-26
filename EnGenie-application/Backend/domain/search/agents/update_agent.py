"""
Node 3 — Update Agent (Lite with Reasoning)

Updates equipment specifications with new details provided by user.
Stays on awaitAllSpecs for the edit loop — does not trigger vendor search.
"""

import logging

from domain.orchestrator.state import AgenticSystemState
from common.helpers.progress_tracker import progress_tracker

logger = logging.getLogger(__name__)


def update_agent(state: AgenticSystemState) -> AgenticSystemState:
    """
    Apply CRUD edits via shared search_modification service.
    Keeps workflow on awaitAllSpecs — vendor analysis runs only after user proceeds.
    """
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "update_agent",
            "message": "Updating",
            "progress": 50,
        })

    logger.info("[UPDATE_AGENT] Applying modification via shared service")
    state.setdefault("agent_path", []).append("update_agent")

    try:
        from common.ai.memory import format_conversation_for_prompt
        from domain.search.services.search_modification import apply_search_modification
        from domain.search.services.search_session_context import load_search_context

        session_id = state.get("session_id", "default")
        user_input = state.get("user_input", "")
        conversation = format_conversation_for_prompt(session_id)

        ctx = load_search_context(session_id, langgraph_state=state)
        logger.info(
            "[UPDATE_AGENT] Loaded context session=%s step=%s version=%s changes=%s",
            session_id,
            ctx.workflow_step,
            ctx.version,
            len(ctx.change_log),
        )

        current_state = ctx.to_langgraph_state()

        result = apply_search_modification(
            session_id=session_id,
            user_input=user_input,
            current_state=current_state,
            conversation_context=conversation,
            skip_standard_rag=state.get("skip_standards", False),
            user_id=state.get("user_id"),
            stream_id=stream_id,
        )

        if not result.success and result.needs_clarification:
            state["needs_clarification"] = True
            state["llm_generated_response"] = result.summary
            state["skip_full_workflow"] = True
            state["workflow_step"] = "awaitAllSpecs"
            return state

        if result.error:
            state["error_message"] = result.error
            return state

        result.apply_to_langgraph_state(state)
        reloaded = load_search_context(session_id)
        state["change_log"] = reloaded.change_log
        state["context_version"] = reloaded.version
        state["search_intent"] = state.get("search_intent", "modification")
        logger.info(
            "[UPDATE_AGENT] Modification complete — staying on awaitAllSpecs "
            "(mandatory_missing=%s, optional_missing=%s, advanced_missing=%s)",
            len(state.get("missing_mandatory_fields", [])),
            len(state.get("missing_optional_fields", [])),
            len(state.get("missing_advanced_fields", [])),
        )

    except Exception as e:
        logger.exception(f"[UPDATE_AGENT] Error in modification: {e}")
        state["error_message"] = f"Update error: {str(e)}"

    return state
