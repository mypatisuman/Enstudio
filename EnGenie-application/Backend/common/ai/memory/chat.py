import logging
import threading
from datetime import datetime
from typing import Any
from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)
_chat_memory_store: dict[str, list[dict[str, Any]]] = {}
_chat_memory_lock = threading.Lock()

def _evict_chat_session(session_id: str):
    with _chat_memory_lock:
        _chat_memory_store.pop(session_id, None)

register_eviction_callback(_evict_chat_session)

def load_chat_memory(session_id: str) -> list[dict[str, Any]]:
    with _chat_memory_lock:
        history = _chat_memory_store.get(session_id, [])
    logger.debug(f"[CHAT_MEMORY] Loaded {len(history)} entries for session {session_id}")
    return history

def store_chat_memory(session_id: str, query: str, classified_keywords: dict[str, list[str]], intent: str, resolved_query: str = None) -> None:
    with _chat_memory_lock:
        if session_id not in _chat_memory_store:
            _chat_memory_store[session_id] = []
        _chat_memory_store[session_id].append({
            "query": query,
            "resolved_query": resolved_query or query,
            "classified_keywords": classified_keywords,
            "intent": intent,
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"[CHAT_MEMORY] Stored entry for session {session_id}, total entries: {len(_chat_memory_store[session_id])}")

def clear_chat_memory(session_id: str) -> None:
    with _chat_memory_lock:
        if session_id in _chat_memory_store:
            del _chat_memory_store[session_id]
            logger.info(f"[CHAT_MEMORY] Cleared chat memory for session {session_id}")
