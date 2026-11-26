"""
Durable persistence for search session context (production L2 store).

In-memory cache in ``search.py`` is L1; MongoDB is L2 for restart / multi-instance
continuity. Failures degrade gracefully to in-memory only (same as conversation memory).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MONGO_COLLECTION = "search_session_context"
_TTL_HOURS = int(os.environ.get("SEARCH_CONTEXT_TTL_HOURS", "72"))
_MAX_HISTORY = 20
_persist_lock = threading.Lock()
_indexes_ensured = False
_indexes_lock = threading.Lock()


def _collection():
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        conn = get_mongodb_connection()
        cols = conn.get("collections") or {}
        col = cols.get("search_session_context")
        if col is not None:
            return col
        db = conn.get("database") or conn.get("db")
        if db is not None:
            return db[_MONGO_COLLECTION]
        return None
    except Exception as exc:
        logger.debug("[SEARCH_CONTEXT_DB] MongoDB unavailable: %s", exc)
        return None


def ensure_indexes() -> None:
    """Create MongoDB indexes for search session context (idempotent)."""
    global _indexes_ensured
    with _indexes_lock:
        if _indexes_ensured:
            return
        try:
            from common.infra.mongodb_config import ensure_indexes as _ensure_all

            _ensure_all()
            _indexes_ensured = True
            logger.info("[SEARCH_CONTEXT_DB] indexes ensured")
        except Exception as exc:
            logger.warning("[SEARCH_CONTEXT_DB] ensure_indexes failed: %s", exc)


def load_session_history(session_id: str) -> list[dict[str, Any]] | None:
    """Load full snapshot history for a session from MongoDB."""
    if not session_id:
        return None
    ensure_indexes()
    try:
        col = _collection()
        if col is None:
            return None
        doc = col.find_one({"session_id": session_id}, {"_id": 0, "history": 1})
        if not doc:
            return None
        history = doc.get("history") or []
        return list(history) if history else None
    except Exception as exc:
        logger.warning("[SEARCH_CONTEXT_DB] load failed session=%s: %s", session_id, exc)
        return None


def load_session_document(session_id: str) -> dict[str, Any] | None:
    """Load full persisted session document (history + summary + last turn)."""
    if not session_id:
        return None
    ensure_indexes()
    try:
        col = _collection()
        if col is None:
            return None
        return col.find_one({"session_id": session_id}, {"_id": 0})
    except Exception as exc:
        logger.warning("[SEARCH_CONTEXT_DB] load doc failed session=%s: %s", session_id, exc)
        return None


def persist_session(
    session_id: str,
    history: list[dict[str, Any]],
    *,
    context_summary: str = "",
    last_turn: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """Upsert session history and metadata to MongoDB (sync — called from worker thread)."""
    if not session_id:
        return
    ensure_indexes()
    try:
        col = _collection()
        if col is None:
            return

        capped = list(history[-_MAX_HISTORY:]) if history else []
        latest_meta = (capped[-1].get("metadata") or {}) if capped else {}
        version = int(latest_meta.get("context_version") or 0)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=_TTL_HOURS)

        update: dict[str, Any] = {
            "$set": {
                "history": capped,
                "context_summary": context_summary or latest_meta.get("context_summary", ""),
                "context_version": version,
                "updated_at": now,
                "expires_at": expires_at,
            },
            "$setOnInsert": {
                "session_id": session_id,
                "created_at": now,
            },
        }
        if last_turn:
            update["$set"]["last_turn"] = last_turn
        if user_id:
            update["$set"]["user_id"] = user_id

        with _persist_lock:
            col.update_one({"session_id": session_id}, update, upsert=True)

        logger.info(
            "[SEARCH_CONTEXT_DB] persisted session=%s version=%s entries=%s",
            session_id,
            version,
            len(capped),
        )
    except Exception as exc:
        logger.warning("[SEARCH_CONTEXT_DB] persist failed session=%s: %s", session_id, exc)


def persist_session_async(
    session_id: str,
    history: list[dict[str, Any]],
    *,
    context_summary: str = "",
    last_turn: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """Background persist so API/workflow paths are not blocked on Mongo I/O."""

    snapshot_history = [dict(h) for h in (history or [])]

    def _sync():
        persist_session(
            session_id,
            snapshot_history,
            context_summary=context_summary,
            last_turn=last_turn,
            user_id=user_id,
        )

    threading.Thread(target=_sync, daemon=True).start()


def delete_session(session_id: str) -> None:
    """Remove persisted session context."""
    if not session_id:
        return

    def _sync():
        try:
            ensure_indexes()
            col = _collection()
            if col is None:
                return
            col.delete_one({"session_id": session_id})
            logger.info("[SEARCH_CONTEXT_DB] deleted session=%s", session_id)
        except Exception as exc:
            logger.warning("[SEARCH_CONTEXT_DB] delete failed session=%s: %s", session_id, exc)

    threading.Thread(target=_sync, daemon=True).start()
