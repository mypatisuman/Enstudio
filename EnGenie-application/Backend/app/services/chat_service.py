"""
Chat service layer — app-level orchestration for the chat agent workflow.

Delegates to domain/chat/agents/chat_agent.py.
Route handlers import from here to stay thin HTTP-only layers.
"""
import logging

from common.infra.repositories.interaction_log_repository import interaction_logger


def process_chat(
    query: str,
    session_id: str,
    user_id=None,
    project_id: str = "",
) -> dict:
    """
    Run the chat agent and log the interaction.

    Returns the agent result dict.
    """
    from domain.chat.workflows.chat_workflow import process_chat_request

    user_id_str = str(user_id) if user_id else "anonymous"

    result = process_chat_request(query, session_id, user_id)

    try:
        interaction_logger.log_interaction(
            user_id=user_id_str,
            session_id=project_id or session_id,
            user_input=query,
            response=result.get("answer", str(result)),
            metadata={
                "agent_type": "chat",
                "session_id": session_id,
                "project_id": project_id,
                "success": result.get("success", True),
            },
            interaction_type="chat",
        )
    except Exception as log_err:
        logging.warning(f"[CHAT_SERVICE] Interaction log failed: {log_err}")

    return result


def clear_chat_session(session_id: str) -> None:
    """Clear pending confirmation state for a chat session."""
    from domain.chat.agents.chat_agent import clear_pending_query
    clear_pending_query(session_id)
