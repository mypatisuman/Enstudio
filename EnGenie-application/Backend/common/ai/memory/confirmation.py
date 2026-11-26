import logging
import threading
from datetime import datetime
from typing import Any
from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)

_pending_confirmation_store: dict[str, dict[str, Any]] = {}
_pending_confirmation_lock = threading.Lock()

def _evict_confirmation_session(session_id: str):
    with _pending_confirmation_lock:
        _pending_confirmation_store.pop(session_id, None)

register_eviction_callback(_evict_confirmation_session)

def store_pending_confirmation(session_id: str, query: str, context_type: str = "general") -> None:
    with _pending_confirmation_lock:
        _pending_confirmation_store[session_id] = {
            "query": query,
            "context_type": context_type,
            "timestamp": datetime.now().isoformat()
        }
    logger.info(f"[MEMORY] Stored pending confirmation ({context_type}) for session {session_id}")

def get_pending_confirmation(session_id: str) -> dict[str, Any]:
    with _pending_confirmation_lock:
        return _pending_confirmation_store.get(session_id, {})

def clear_pending_confirmation(session_id: str) -> None:
    with _pending_confirmation_lock:
        if session_id in _pending_confirmation_store:
            del _pending_confirmation_store[session_id]
            logger.info(f"[MEMORY] Cleared pending confirmation for session {session_id}")
