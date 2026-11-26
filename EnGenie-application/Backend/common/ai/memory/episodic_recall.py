"""
Episodic project recall memory.

Detects when a new user request matches a previously saved project (even when the
wording is jumbled or the input is structured differently), holds a pending
"shall I retrieve it?" confirmation per session, and resolves the offer only
via Open / Preview / Ignore UI actions.

Pairs with MongoProjectManager.find_similar_projects (the semantic match) and the
project_service orchestration layer (the retrieval).
"""
import logging
import threading
from datetime import datetime
from typing import Any

from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)

# session_id -> {"query": str, "candidates": list[dict], "timestamp": str}
_pending_recall_store: dict[str, dict[str, Any]] = {}
_pending_recall_lock = threading.Lock()

# session_id -> set of query strings the user declined via Ignore (skip re-offer on re-run)
_declined_recall_queries: dict[str, set[str]] = {}


def _evict_recall_session(session_id: str) -> None:
    with _pending_recall_lock:
        _pending_recall_store.pop(session_id, None)
        _declined_recall_queries.pop(session_id, None)


register_eviction_callback(_evict_recall_session)


def store_pending_recall(session_id: str, query: str, candidates: list[dict[str, Any]]) -> None:
    """Remember that we offered to retrieve matched project(s) for this session."""
    if not session_id or not candidates:
        return
    with _pending_recall_lock:
        _pending_recall_store[session_id] = {
            "query": query,
            "candidates": candidates,
            "timestamp": datetime.now().isoformat(),
        }
    logger.info(f"[EPISODIC_RECALL] Stored {len(candidates)} pending recall candidate(s) for session {session_id}")


def get_pending_recall(session_id: str) -> dict[str, Any]:
    with _pending_recall_lock:
        return dict(_pending_recall_store.get(session_id, {}))


def clear_pending_recall(session_id: str) -> None:
    with _pending_recall_lock:
        if session_id in _pending_recall_store:
            del _pending_recall_store[session_id]
            logger.info(f"[EPISODIC_RECALL] Cleared pending recall for session {session_id}")


def mark_recall_declined(session_id: str, query: str) -> None:
    """Remember that the user chose Ignore for this query (do not re-offer on re-run)."""
    normalized = (query or "").strip()
    if not session_id or not normalized:
        return
    with _pending_recall_lock:
        _declined_recall_queries.setdefault(session_id, set()).add(normalized)
    logger.info(f"[EPISODIC_RECALL] Marked recall declined for session {session_id}")


def is_recall_declined(session_id: str, query: str) -> bool:
    normalized = (query or "").strip()
    if not session_id or not normalized:
        return False
    with _pending_recall_lock:
        return normalized in _declined_recall_queries.get(session_id, set())


def build_recall_prompt(candidates: list[dict[str, Any]]) -> str:
    """Build the natural-language message asking the user whether to retrieve."""
    if not candidates:
        return ""

    top = candidates[0]
    name = top.get("project_name") or "a saved project"
    if len(candidates) == 1:
        return (
            f"This request looks related to your saved project “{name}”, "
            f"which I have stored. Use Open, Preview, or Ignore below."
        )

    names = ", ".join(f"“{c.get('project_name') or 'Untitled'}”" for c in candidates)
    return (
        f"This request looks related to saved projects you already have ({names}). "
        f"The closest match is “{name}”. Use Open, Preview, or Ignore below."
    )
