import logging
import os
from common.helpers.notifications import notify_failure as _notify_failure
from typing import Any

from common.ai.memory import (
    add_conversation_turn,
    format_conversation_for_prompt,
    get_full_conversation_history,
    clear_all_session_data
)

logger = logging.getLogger(__name__)



# Initialize environment
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

def _get_full_conversation_context(session_id: str) -> str:
    """
    Get COMPLETE conversation history for a session (unlimited).

    Returns formatted conversation ready for LLM prompt.
    Includes full message history with timestamps and metadata.
    """
    history = get_full_conversation_history(session_id)

    if not history:
        return "No previous conversation history."

    # Format complete conversation with role, content, and metadata
    formatted = format_conversation_for_prompt(
        session_id,
        include_metadata=True,
        max_turns=None  # No limit - include entire history
    )

    logger.info(f"[CHAT_MEMORY] Retrieved {len(history)} conversation turns for session {session_id}")
    return formatted


def _add_to_chat_memory(session_id: str, user_query: str, assistant_response: str, metadata: dict[str, Any] = None):
    """
    Add conversation turn to UNLIMITED central memory system.

    Args:
        session_id: Chat session ID
        user_query: User's message
        assistant_response: Assistant's response
        metadata: Optional - context data (intent, source, classification, etc.)
    """
    try:
        # Add user message to central memory
        add_conversation_turn(
            session_id=session_id,
            role="user",
            content=user_query,
            metadata={
                "source": "chat",
                "query": user_query,
                "type": "user_input"
            }
        )

        # Add assistant response to central memory
        meta = metadata or {}
        meta["source"] = "chat"
        meta["response_type"] = "assistant_response"

        add_conversation_turn(
            session_id=session_id,
            role="assistant",
            content=assistant_response,
            metadata=meta
        )

        logger.info(f"[CHAT_MEMORY] Stored conversation turn in unlimited memory for session {session_id}")

    except Exception as e:
        logger.error(f"[CHAT_MEMORY] Failed to add to memory: {e}")

        # Send notification for memory storage failure
        _notify_failure("Chat Memory Storage",
            f"Failed to store chat conversation in memory: {str(e)}",
            session_id=session_id, error=str(e))


def _clear_chat_history(session_id: str):
    """Clear conversation history for a session."""
    from common.ai.memory import clear_all_session_data
    clear_all_session_data(session_id)
    logger.info(f"[CHAT_AGENT] Cleared all history for session {session_id}")


