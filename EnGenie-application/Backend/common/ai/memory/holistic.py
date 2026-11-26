"""
Session context memory for the solution holistic gate.

L1: in-process session-keyed dict (mirrors confirmation.py), cleared by the
conversation store's LRU/idle eviction callbacks.
L2: MongoDB ``holistic_context`` collection (mirrors
search_context_persistence.py) for restart / multi-instance continuity.
Failures degrade gracefully to in-memory only.

Keying: composite (user_id, session_id) when user_id is known, so two
authenticated users can never read/write each other's gate context even if
they collide on the same session_id (e.g. both hitting the "default" session
fallback in agentic_integration.py). Anonymous callers (user_id=None) fall
back to session_id-only keying, matching pre-existing behavior -- there is no
user_id to disambiguate them, so anonymous-vs-anonymous collision remains a
known, accepted residual gap.

Context shape (one dict per (user_id, session_id)):
    {
      "stage": "awaiting_gap_answers" | "awaiting_proceed_confirm" | "proceeded_with_gaps",
      "original_requirement": str,      # turn-1 user input
      "accumulated_inputs": list[str],  # user replies during the gate conversation
      "asked_questions": list[str],     # questions already shown (never repeated)
      "gaps": list[dict],               # last gate verdict's gaps
      "ask_count": int,                 # total prompts issued
      "updated_at": str,                # ISO timestamp
    }
"""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from common.ai.memory.core import register_eviction_callback

logger = logging.getLogger(__name__)

_MONGO_COLLECTION = "holistic_context"
_TTL_HOURS = int(os.environ.get("HOLISTIC_CONTEXT_TTL_HOURS", "72"))

_holistic_store: dict[str, dict[str, Any]] = {}
_holistic_lock = threading.Lock()


def _store_key(user_id, session_id: str) -> str:
    """Composite in-memory key: user-scoped when user_id is known, otherwise
    plain session_id (preserves anonymous-session behavior)."""
    return f"user:{user_id}:{session_id}" if user_id else session_id


def _mongo_filter(user_id, session_id: str) -> dict[str, Any]:
    """Mongo query/update filter. user_id is ALWAYS part of the filter (as
    None for anonymous callers) so a document created by an authenticated
    user can never be matched by an anonymous lookup on the same session_id,
    or vice versa."""
    return {"session_id": session_id, "user_id": str(user_id) if user_id else None}


def _evict_holistic_session(session_id: str):
    """Registered against the conversation-memory eviction callback, which
    only knows the plain session_id -- sweep every in-memory key that belongs
    to this session_id (plain, or any user-scoped composite key ending in
    it), since eviction should drop ALL users' gate context for that session."""
    with _holistic_lock:
        stale = [k for k in _holistic_store if k == session_id or k.endswith(f":{session_id}")]
        for k in stale:
            _holistic_store.pop(k, None)


register_eviction_callback(_evict_holistic_session)


def _collection():
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        conn = get_mongodb_connection()
        cols = conn.get("collections") or {}
        col = cols.get("holistic_context")
        if col is not None:
            return col
        db = conn.get("database") or conn.get("db")
        if db is not None:
            return db[_MONGO_COLLECTION]
        return None
    except Exception as exc:
        logger.debug("[HOLISTIC_MEMORY] MongoDB unavailable: %s", exc)
        return None


def store_holistic_context(session_id: str, context: dict[str, Any], user_id=None) -> None:
    """Store gate context for a (user_id, session_id): L1 write + async L2 upsert."""
    if not session_id:
        return
    context = dict(context)
    context["updated_at"] = datetime.now(timezone.utc).isoformat()

    key = _store_key(user_id, session_id)
    with _holistic_lock:
        _holistic_store[key] = context
    logger.info(
        f"[HOLISTIC_MEMORY] Stored context for user={user_id} session={session_id} "
        f"(stage={context.get('stage')}, ask_count={context.get('ask_count')})"
    )

    snapshot = dict(context)
    mongo_filter = _mongo_filter(user_id, session_id)

    def _persist():
        try:
            col = _collection()
            if col is None:
                return
            now = datetime.now(timezone.utc)
            col.update_one(
                mongo_filter,
                {
                    "$set": {**snapshot, "expires_at": now + timedelta(hours=_TTL_HOURS)},
                    "$setOnInsert": {**mongo_filter, "created_at": now},
                },
                upsert=True,
            )
            logger.info(f"[HOLISTIC_MEMORY] Persisted context for user={user_id} session={session_id}")
        except Exception as exc:
            logger.warning(f"[HOLISTIC_MEMORY] Persist failed user={user_id} session={session_id}: {exc}")

    threading.Thread(target=_persist, daemon=True).start()


def get_holistic_context(session_id: str, user_id=None) -> dict[str, Any]:
    """Load gate context: L1 hit, else L2 lookup (rehydrating L1), else {}."""
    if not session_id:
        return {}
    key = _store_key(user_id, session_id)
    with _holistic_lock:
        ctx = _holistic_store.get(key)
        if ctx:
            return dict(ctx)
    try:
        col = _collection()
        if col is None:
            return {}
        doc = col.find_one(_mongo_filter(user_id, session_id), {"_id": 0, "expires_at": 0, "created_at": 0})
        if not doc or not doc.get("stage"):
            return {}
        with _holistic_lock:
            _holistic_store[key] = dict(doc)
        logger.info(f"[HOLISTIC_MEMORY] Rehydrated context for user={user_id} session={session_id} from MongoDB")
        return dict(doc)
    except Exception as exc:
        logger.warning(f"[HOLISTIC_MEMORY] Load failed user={user_id} session={session_id}: {exc}")
        return {}


def clear_holistic_context(session_id: str, user_id=None) -> None:
    """Clear gate context: L1 delete + async L2 delete."""
    if not session_id:
        return
    key = _store_key(user_id, session_id)
    with _holistic_lock:
        if key in _holistic_store:
            del _holistic_store[key]
            logger.info(f"[HOLISTIC_MEMORY] Cleared context for user={user_id} session={session_id}")

    mongo_filter = _mongo_filter(user_id, session_id)

    def _delete():
        try:
            col = _collection()
            if col is None:
                return
            col.delete_one(mongo_filter)
        except Exception as exc:
            logger.warning(f"[HOLISTIC_MEMORY] Delete failed user={user_id} session={session_id}: {exc}")

    threading.Thread(target=_delete, daemon=True).start()
