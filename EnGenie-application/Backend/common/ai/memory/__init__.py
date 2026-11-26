from common.ai.memory.core import (
    add_conversation_turn,
    get_full_conversation_history,
    format_conversation_for_prompt,
    get_session_token_estimate,
    clear_core_session
)
from common.ai.memory.solution import (
    store_solution_data,
    add_solution_modification,
    get_latest_instruments_and_accessories,
    get_latest_consolidated_requirement,
    get_solution_modifications,
    clear_solution_memory
)
from common.ai.memory.episodes import (
    record_conversation_episode,
    find_similar_episodes,
    get_session_project_ids,
    link_session_episodes_to_project,
)
from common.ai.memory.search import (
    store_search_data,
    get_latest_search,
    get_search_history,
    get_search_params_summary,
    update_search_refinement,
    clear_search_memory,
    save_interim_state,
    load_interim_state,
    get_search_snapshot,
    upsert_search_snapshot,
    record_context_turn,
)
from common.ai.memory.chat import (
    load_chat_memory,
    store_chat_memory,
    clear_chat_memory
)
from common.ai.memory.confirmation import (
    store_pending_confirmation,
    get_pending_confirmation,
    clear_pending_confirmation
)
from common.ai.memory.holistic import (
    store_holistic_context,
    get_holistic_context,
    clear_holistic_context
)
from common.ai.memory.episodic_recall import (
    store_pending_recall,
    get_pending_recall,
    clear_pending_recall,
    build_recall_prompt,
    mark_recall_declined,
    is_recall_declined,
)
from common.ai.memory.hybrid_memory_manager import (
    load_hybrid_memory,
    clear_all_user_memories,
    update_hybrid_profile,
    format_profile_for_injection,
)
from common.ai.memory.hybrid_memory_agent import run_hybrid_memory_reflection

def clear_all_session_data(session_id: str) -> None:
    clear_core_session(session_id)
    clear_solution_memory(session_id)
    clear_search_memory(session_id)
    clear_chat_memory(session_id)
    clear_pending_confirmation(session_id)
    clear_pending_recall(session_id)
    clear_holistic_context(session_id)

__all__ = [
    "add_conversation_turn",
    "get_full_conversation_history",
    "format_conversation_for_prompt",
    "get_session_token_estimate",
    "clear_all_session_data",
    "store_solution_data",
    "add_solution_modification",
    "get_latest_instruments_and_accessories",
    "get_latest_consolidated_requirement",
    "get_solution_modifications",
    "record_conversation_episode",
    "find_similar_episodes",
    "get_session_project_ids",
    "link_session_episodes_to_project",
    "store_search_data",
    "get_latest_search",
    "get_search_history",
    "get_search_params_summary",
    "update_search_refinement",
    "save_interim_state",
    "load_interim_state",
    "get_search_snapshot",
    "upsert_search_snapshot",
    "record_context_turn",
    "load_chat_memory",
    "store_chat_memory",
    "store_pending_confirmation",
    "get_pending_confirmation",
    "clear_pending_confirmation",
    "store_holistic_context",
    "get_holistic_context",
    "clear_holistic_context",
    "store_pending_recall",
    "get_pending_recall",
    "clear_pending_recall",
    "build_recall_prompt",
    "mark_recall_declined",
    "is_recall_declined",
    "load_hybrid_memory",
    "clear_all_user_memories",
    "update_hybrid_profile",
    "format_profile_for_injection",
    "run_hybrid_memory_reflection"
]
