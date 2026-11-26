"""
Conversation-episode store — user-level episodic memory of MEANINGFUL solution
exchanges, embedded for semantic recall.

Each recorded episode = one successful requirements turn (user input + response
summary + BOM categories + design objective), embedded with the same model as
project signatures so episodic recall can recognize a re-request phrased like a
past CONVERSATION even when no matching saved-project signature exists.

Episodes are Mongo-only (collection ``conversation_episodes``), TTL-expired
(env CONVERSATION_EPISODES_TTL_DAYS, default 30), and stamped with a
``project_id`` when their session's work is later saved as a project
(link_session_episodes_to_project — called from save_project). Deliberately
NOT part of clear_all_session_data: episodes are user-level cross-session
memory governed by TTL, not session state.

All operations are best-effort: failures are logged and swallowed — episodic
memory must never affect a live turn.
"""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MONGO_COLLECTION = "conversation_episodes"
_TTL_DAYS = int(os.environ.get("CONVERSATION_EPISODES_TTL_DAYS", "30"))
_EPISODE_TEXT_BUDGET = 900  # embedding model truncates ~256 tokens


def _collection():
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        conn = get_mongodb_connection()
        cols = conn.get("collections") or {}
        col = cols.get("conversation_episodes")
        if col is not None:
            return col
        db = conn.get("database")
        return db[_MONGO_COLLECTION] if db is not None else None
    except Exception as exc:
        logger.debug("[EPISODES] MongoDB unavailable: %s", exc)
        return None


def _should_record(final_response: dict[str, Any]) -> bool:
    """Only meaningful exchanges become episodes: a successful requirements turn
    that produced a BOM or a designed solution. Clarifications, resets, recall
    offers, and Q&A are noise and are never recorded."""
    if not final_response or not final_response.get("success"):
        return False
    if final_response.get("intent") != "requirements":
        return False
    return bool(final_response.get("instruments") or final_response.get("designed_solution"))


def _build_episode_text(user_input: str, final_response: dict[str, Any]) -> str:
    """Compact episode digest within the embedding budget: the user's request
    first (highest signal), then response message/summary, BOM categories,
    project name, and the design objective."""
    budget = _EPISODE_TEXT_BUDGET
    parts: list[str] = []

    def _add(text: str, cap: int) -> None:
        nonlocal budget
        text = (text or "").strip()[:cap]
        if text and budget > 0:
            text = text[:budget]
            parts.append(text)
            budget -= len(text) + 1

    _add(user_input, 600)
    _add(final_response.get("message", ""), 200)
    _add(final_response.get("summary", ""), 200)
    categories = [i.get("category", "") for i in (final_response.get("instruments") or []) if i.get("category")]
    if categories:
        _add("Instruments: " + ", ".join(categories), 200)
    _add(final_response.get("project_name", ""), 80)
    designed = final_response.get("designed_solution") or {}
    if isinstance(designed, dict):
        _add(designed.get("project_objective") or designed.get("projectObjective", ""), 200)

    return "\n".join(parts).strip()


def record_conversation_episode(user_id, session_id: str, user_input: str,
                                final_response: dict[str, Any]) -> None:
    """Record one exchange as an embedded episode. Designed to run inside a
    daemon thread — never raises."""
    try:
        if not user_id or not session_id or not _should_record(final_response):
            return
        episode_text = _build_episode_text(user_input, final_response)
        if not episode_text:
            return

        from common.ai.embedding_manager import generate_embedding
        embedding = generate_embedding(episode_text)
        if not embedding:
            return

        col = _collection()
        if col is None:
            return
        now = datetime.now(timezone.utc)
        col.insert_one({
            "user_id": str(user_id),
            "session_id": session_id,
            "episode_text": episode_text,
            "embedding": embedding,
            "project_id": None,  # stamped by link_session_episodes_to_project on save
            "intent": final_response.get("intent"),
            "response_type": final_response.get("response_type"),
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(days=_TTL_DAYS),
        })
        logger.info(f"[EPISODES] Recorded episode for session {session_id} ({len(episode_text)} chars)")
    except Exception as exc:
        logger.warning(f"[EPISODES] Failed to record episode for session {session_id}: {exc}")


def find_similar_episodes(user_id, query_text: str, threshold: float = 0.75,
                          top_k: int = 5) -> list[dict[str, Any]]:
    # Threshold note: episode_text mixes request + response content, which
    # depresses cosine vs clean project signatures (live-measured: a heavy
    # same-intent rewording scored 0.77; unrelated content sits < 0.70 per the
    # embedding calibration notes). Linked-episode offers still pass LLM
    # verification downstream, so 0.75 favours recall over precision here.
    """Semantic search over the user's recorded episodes. Returns
    [{episode_text, session_id, project_id, similarity, created_at}] sorted by
    similarity desc. Best-effort — empty list on any failure."""
    try:
        if not user_id or not query_text or not query_text.strip():
            return []
        col = _collection()
        if col is None:
            return []

        from common.ai.embedding_manager import find_most_similar, generate_embedding
        query_embedding = generate_embedding(query_text)
        if not query_embedding:
            return []

        docs = list(col.find(
            {"user_id": str(user_id), "embedding": {"$exists": True, "$ne": None}},
            {"embedding": 1, "episode_text": 1, "session_id": 1, "project_id": 1, "created_at": 1},
        ))
        if not docs:
            return []

        ranked = find_most_similar(query_embedding, [d["embedding"] for d in docs], threshold=threshold)
        if not ranked:
            # Log the best under-threshold score so the threshold can be tuned
            # from real traffic instead of guesswork.
            best = find_most_similar(query_embedding, [d["embedding"] for d in docs], threshold=0.0)
            if best:
                logger.info(f"[EPISODES] No episode ≥ {threshold} for user {user_id}; "
                            f"best score was {round(float(best[0][1]), 4)}")
        results = []
        for index, score in ranked[:top_k]:
            doc = docs[index]
            created_at = doc.get("created_at")
            results.append({
                "episode_text": (doc.get("episode_text") or "")[:400],
                "session_id": doc.get("session_id"),
                "project_id": doc.get("project_id"),
                "similarity": round(float(score), 4),
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            })
        return results
    except Exception as exc:
        logger.warning(f"[EPISODES] Episode search failed for user {user_id}: {exc}")
        return []


def get_session_project_ids(session_id: str) -> set[str]:
    """Project ids this session's episodes were linked to — i.e. projects that
    were BORN from this conversation (link_session_episodes_to_project stamps
    them on save). Used by episodic recall to avoid offering a conversation its
    own project back. Best-effort — empty set on any failure."""
    try:
        if not session_id:
            return set()
        col = _collection()
        if col is None:
            return set()
        return {
            str(doc["project_id"])
            for doc in col.find(
                {"session_id": session_id, "project_id": {"$nin": [None, ""]}},
                {"project_id": 1},
            )
        }
    except Exception as exc:
        logger.warning(f"[EPISODES] Session-project lookup failed for {session_id}: {exc}")
        return set()


def link_session_episodes_to_project(session_id: str, project_id: str) -> None:
    """Stamp all of a session's episodes with the project they became — enabling
    episode matches to surface that saved project in episodic recall. Async."""
    if not session_id or not project_id:
        return

    def _sync():
        try:
            col = _collection()
            if col is None:
                return
            result = col.update_many(
                {"session_id": session_id},
                {"$set": {"project_id": str(project_id), "updated_at": datetime.now(timezone.utc)}},
            )
            if result.modified_count:
                logger.info(f"[EPISODES] Linked {result.modified_count} episode(s) of session "
                            f"{session_id} to project {project_id}")
        except Exception as exc:
            logger.warning(f"[EPISODES] Episode linking failed session={session_id}: {exc}")

    threading.Thread(target=_sync, daemon=True).start()
