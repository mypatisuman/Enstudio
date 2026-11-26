import logging
import threading
from datetime import datetime
from typing import Any
from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)

_solution_data_store: dict[str, dict[str, Any]] = {}
_solution_data_lock = threading.Lock()

def _evict_solution_session(session_id: str):
    with _solution_data_lock:
        _solution_data_store.pop(session_id, None)

register_eviction_callback(_evict_solution_session)

def store_solution_data(session_id: str, instruments: list[dict[str, Any]], accessories: list[dict[str, Any]], metadata: dict[str, Any] = None) -> None:
    with _solution_data_lock:
        if session_id not in _solution_data_store:
            _solution_data_store[session_id] = {"instruments": [], "accessories": [], "modifications": [], "metadata": {}}
        _solution_data_store[session_id]["instruments"] = instruments
        _solution_data_store[session_id]["accessories"] = accessories
        if metadata: _solution_data_store[session_id]["metadata"].update(metadata)
        _solution_data_store[session_id]["last_updated"] = datetime.now().isoformat()
    logger.info(f"[SOLUTION_MEMORY] Stored {len(instruments)} instruments and {len(accessories)} accessories for session {session_id}")

def add_solution_modification(session_id: str, modification_type: str, description: str, changes: dict[str, Any]) -> None:
    with _solution_data_lock:
        if session_id not in _solution_data_store:
            _solution_data_store[session_id] = {"instruments": [], "accessories": [], "modifications": [], "metadata": {}}
        _solution_data_store[session_id]["modifications"].append({
            "type": modification_type,
            "description": description,
            "changes": changes,
            "timestamp": datetime.now().isoformat()
        })
    logger.info(f"[SOLUTION_MEMORY] Recorded modification for session {session_id}: {description}")

def get_latest_instruments_and_accessories(session_id: str) -> dict[str, Any]:
    with _solution_data_lock:
        solution_data = _solution_data_store.get(session_id, {})
        if solution_data:
            return {"instruments": solution_data.get("instruments", []), "accessories": solution_data.get("accessories", [])}
    from common.ai.memory.core import get_full_conversation_history
    history = get_full_conversation_history(session_id)
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            metadata = turn.get("metadata", {})
            if "instruments" in metadata or "accessories" in metadata:
                return {"instruments": metadata.get("instruments", []), "accessories": metadata.get("accessories", [])}
    return {"instruments": [], "accessories": []}

def get_latest_consolidated_requirement(session_id: str) -> str:
    """Return the most recent gate-consolidated requirement (original request +
    chat-supplied gap answers) for this session, scanned from assistant-turn
    conversation metadata — the same reverse-scan pattern as the
    instruments/accessories fallback above. Empty string when none exists."""
    from common.ai.memory.core import get_full_conversation_history
    history = get_full_conversation_history(session_id)
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            consolidated = (turn.get("metadata") or {}).get("consolidated_requirements")
            if consolidated:
                return str(consolidated)
    return ""


def get_solution_modifications(session_id: str) -> list[dict[str, Any]]:
    with _solution_data_lock:
        return _solution_data_store.get(session_id, {}).get("modifications", [])

def clear_solution_memory(session_id: str) -> None:
    with _solution_data_lock:
        if session_id in _solution_data_store:
            del _solution_data_store[session_id]
            logger.info(f"[SOLUTION_MEMORY] Cleared solution data for session {session_id}")
