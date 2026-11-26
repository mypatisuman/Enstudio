import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)

_search_history_store: dict[str, list[dict[str, Any]]] = {}
_search_history_lock = threading.Lock()
_hydrated_sessions: set[str] = set()
_search_last_access: dict[str, float] = {}
_SEARCH_IDLE_TTL_SECONDS = int(os.environ.get("SEARCH_MEMORY_IDLE_TTL_SECONDS", str(6 * 3600)))


def _evict_search_session(session_id: str):
    with _search_history_lock:
        _search_history_store.pop(session_id, None)
        _hydrated_sessions.discard(session_id)
        _search_last_access.pop(session_id, None)


register_eviction_callback(_evict_search_session)


def sweep_idle_search_sessions(idle_seconds: int | None = None) -> int:
    """Evict search-history sessions idle longer than idle_seconds.

    Independent of core.py's sweep: core.py's eviction callback already clears
    matching entries here when a conversation session is idle-swept, but a
    search session can go idle without ever calling add_conversation_turn
    (e.g. only save_interim_state/upsert_search_snapshot activity), so this
    catches those too. Safe to call repeatedly/concurrently.
    """
    threshold = idle_seconds if idle_seconds is not None else _SEARCH_IDLE_TTL_SECONDS
    now = time.time()
    with _search_history_lock:
        stale_ids = [sid for sid, last in _search_last_access.items() if now - last > threshold]
        for sid in stale_ids:
            _search_history_store.pop(sid, None)
            _hydrated_sessions.discard(sid)
            _search_last_access.pop(sid, None)
    for sid in stale_ids:
        logger.info("[SEARCH_MEMORY] Idle-swept session=%s (idle > %ss)", sid, threshold)
    return len(stale_ids)


def _persist_current_session(session_id: str) -> None:
    """Flush L1 cache to MongoDB L2 store."""
    from common.ai.memory.search_context_persistence import persist_session_async

    with _search_history_lock:
        history = list(_search_history_store.get(session_id, []))

    if not history:
        return

    latest_meta = (history[-1].get("metadata") or {}) if history else {}
    persist_session_async(
        session_id,
        history,
        context_summary=latest_meta.get("context_summary", ""),
        last_turn=latest_meta.get("last_turn"),
    )


def _hydrate_from_persistence(session_id: str) -> None:
    """Load session history from MongoDB into L1 cache on first access."""
    if not session_id or session_id in _hydrated_sessions:
        return

    from common.ai.memory.search_context_persistence import load_session_document

    doc = load_session_document(session_id)
    with _search_history_lock:
        _hydrated_sessions.add(session_id)
        if session_id in _search_history_store and _search_history_store[session_id]:
            return
        if not doc:
            return
        history = doc.get("history") or []
        if not history:
            return
        _search_history_store[session_id] = list(history)
        logger.info(
            "[SEARCH_MEMORY] hydrated session=%s from DB entries=%s version=%s",
            session_id,
            len(history),
            doc.get("context_version", 0),
        )


def _touch_session(session_id: str) -> None:
    _hydrate_from_persistence(session_id)
    if session_id:
        _search_last_access[session_id] = time.time()


def store_search_data(
    session_id: str,
    search_params: dict[str, Any],
    results: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> None:
    _touch_session(session_id)
    with _search_history_lock:
        if session_id not in _search_history_store:
            _search_history_store[session_id] = []
        _search_history_store[session_id].append({
            "search_params": search_params,
            "results": results,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
        })
        if len(_search_history_store[session_id]) > 20:
            _search_history_store[session_id] = _search_history_store[session_id][-20:]
        logger.info(
            "[SEARCH_MEMORY] Stored search with %s results for session %s, total searches: %s",
            len(results),
            session_id,
            len(_search_history_store[session_id]),
        )
    _persist_current_session(session_id)


def get_latest_search(session_id: str) -> dict[str, Any] | None:
    _touch_session(session_id)
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
        return history[-1] if history else None


def get_search_history(session_id: str, max_searches: int | None = None) -> list[dict[str, Any]]:
    _touch_session(session_id)
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
        return history[-max_searches:] if max_searches else history


def get_search_params_summary(session_id: str, max_searches: int = 3) -> str:
    _touch_session(session_id)
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
    if not history:
        return "No previous searches."
    recent = history[-max_searches:]
    lines = []
    for i, search in enumerate(recent, 1):
        params = search.get("search_params", {})
        product_type = params.get("detected_product_type", "Unknown")
        vendors = params.get("filtered_vendors", [])
        requirements = params.get("mapped_requirements", {})
        vendor_str = f", Vendors: {', '.join(vendors[:3])}" if vendors else ""
        lines.append(f"Search {i}: {product_type} ({len(requirements)} specs{vendor_str})")
    return "\n".join(lines)


def update_search_refinement(session_id: str, refinements: dict[str, Any]) -> None:
    _touch_session(session_id)
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
        if not history:
            return
        latest = history[-1]
        latest["search_params"].update(refinements)
        latest["metadata"]["refined"] = True
        latest["metadata"]["refinement_timestamp"] = datetime.now().isoformat()
    logger.info("[SEARCH_MEMORY] Updated latest search with refinements for session %s", session_id)
    _persist_current_session(session_id)


def save_interim_state(session_id: str, state: dict[str, Any]) -> None:
    """Persist mid-workflow LangGraph state so it survives across API requests."""
    _INTERIM_STATE_KEYS = [
        "detected_product_type", "mapped_requirements", "detected_schema",
        "missing_mandatory_fields", "missing_optional_fields", "missing_fields_friendly",
        "advanced_specs", "specified_vendors", "specified_model_families",
        "applicable_standards", "schema_source", "workflow_step",
        "structured_requirements", "unmapped_specs", "input_range",
    ]
    snapshot = {k: state[k] for k in _INTERIM_STATE_KEYS if k in state}
    _touch_session(session_id)
    with _search_history_lock:
        if session_id not in _search_history_store:
            _search_history_store[session_id] = []
        history = _search_history_store[session_id]
        if history:
            history[-1].setdefault("metadata", {})["interim_state"] = snapshot
            history[-1]["metadata"]["interim_updated"] = datetime.now().isoformat()
        else:
            _search_history_store[session_id].append({
                "search_params": {},
                "results": [],
                "metadata": {
                    "interim_state": snapshot,
                    "interim_updated": datetime.now().isoformat(),
                },
                "timestamp": datetime.now().isoformat(),
            })
    logger.debug("[SEARCH_MEMORY] Saved interim state for session %s: %s", session_id, list(snapshot.keys()))
    _persist_current_session(session_id)


def load_interim_state(session_id: str) -> dict[str, Any]:
    """Recover mid-workflow state from a prior request in the same session."""
    _touch_session(session_id)
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
        if history:
            return history[-1].get("metadata", {}).get("interim_state", {})
    return {}


def clear_search_memory(session_id: str) -> None:
    with _search_history_lock:
        if session_id in _search_history_store:
            del _search_history_store[session_id]
        _hydrated_sessions.discard(session_id)
        logger.info("[SEARCH_MEMORY] Cleared search history for session %s", session_id)
    from common.ai.memory.search_context_persistence import delete_session

    delete_session(session_id)


def get_search_snapshot(session_id: str) -> dict[str, Any] | None:
    """Return the latest unified search snapshot for a session."""
    return get_latest_search(session_id)


def upsert_search_snapshot(
    session_id: str,
    snapshot: dict[str, Any],
    *,
    event: str = "modification",
    vendor_results: list[dict[str, Any]] | None = None,
) -> None:
    """
    Persist search context.

    schema_ready: append new history entry (new baseline).
    modification / proceed / vendor_results: update latest entry in place.
    """
    _touch_session(session_id)
    with _search_history_lock:
        if session_id not in _search_history_store:
            _search_history_store[session_id] = []

        history = _search_history_store[session_id]
        meta = snapshot.get("metadata") or {}
        meta["last_context_event"] = event
        meta["context_updated_at"] = datetime.now().isoformat()
        snapshot["metadata"] = meta

        if vendor_results is not None:
            snapshot["results"] = vendor_results

        append_events = {"schema_ready", "reset"}
        if not history or event in append_events:
            snapshot.setdefault("timestamp", datetime.now().isoformat())
            history.append(snapshot)
        else:
            latest = history[-1]
            latest["search_params"] = snapshot.get("search_params", latest.get("search_params", {}))
            latest["metadata"] = {**latest.get("metadata", {}), **meta}
            if vendor_results is not None:
                latest["results"] = vendor_results
            latest["timestamp"] = datetime.now().isoformat()

        if len(history) > 20:
            _search_history_store[session_id] = history[-20:]

        entry_count = len(_search_history_store.get(session_id, []))

    logger.info(
        "[SEARCH_MEMORY] upsert session=%s event=%s entries=%s",
        session_id,
        event,
        entry_count,
    )
    _persist_current_session(session_id)


def record_context_turn(
    session_id: str,
    *,
    user_input: str = "",
    assistant_message: str = "",
    context_summary: str = "",
) -> None:
    """Record latest (user + assistant) turn pair on the active snapshot."""
    if not session_id:
        return
    _touch_session(session_id)
    turn = {
        "user_input": (user_input or "")[:2000],
        "assistant_message": (assistant_message or "")[:4000],
        "timestamp": datetime.now().isoformat(),
    }
    with _search_history_lock:
        history = _search_history_store.get(session_id, [])
        if not history:
            return
        meta = history[-1].setdefault("metadata", {})
        meta["last_turn"] = turn
        if context_summary:
            meta["context_summary"] = context_summary[:4000]
    _persist_current_session(session_id)
