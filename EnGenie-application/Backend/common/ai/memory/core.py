import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_SESSION = 80_000
_CHARS_PER_TOKEN = 4
_MAX_IN_MEMORY_SESSIONS = int(os.environ.get("CONVERSATION_MAX_SESSIONS", "500"))
_MONGO_COLLECTION = "conversation_memory"
_SESSION_IDLE_TTL_SECONDS = int(os.environ.get("CONVERSATION_IDLE_TTL_SECONDS", str(6 * 3600)))

# Compress turns older than this many user/assistant pairs using LangChain summarization
COMPRESSION_THRESHOLD = int(os.environ.get("CONVERSATION_COMPRESSION_TURNS", "5"))

_full_conversation_store: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
_full_conversation_lock = threading.Lock()
_session_last_access: dict[str, float] = {}

# Allow other modules to register cleanup callbacks when a session is evicted or cleared
_eviction_callbacks = []

def register_eviction_callback(callback):
    _eviction_callbacks.append(callback)

def _get_memory_collection():
    try:
        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        # pymongo Collections raise on truthiness testing, so `col or fallback`
        # throws and silently disabled ALL Mongo persistence — always compare
        # against None explicitly.
        col = conn["collections"].get(_MONGO_COLLECTION)
        if col is not None:
            return col
        db = conn.get("database")
        return db[_MONGO_COLLECTION] if db is not None else None
    except Exception as e:
        logger.debug(f"[FULL_MEMORY] MongoDB unavailable for persistence: {e}")
        return None

def _persist_turn_async(session_id: str, entry: dict[str, Any]) -> None:
    def _sync():
        try:
            col = _get_memory_collection()
            if col is None: return
            col.update_one(
                {"session_id": session_id},
                {
                    "$push": {"turns": entry},
                    "$set":  {"last_updated": datetime.now(timezone.utc)},
                    "$setOnInsert": {
                        "session_id": session_id,
                        "created_at": datetime.now(timezone.utc),
                        "is_saved": False,
                        "project_id": None,
                    },
                },
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"[FULL_MEMORY] Background MongoDB sync failed: {e}")
    threading.Thread(target=_sync, daemon=True).start()

def _load_history_from_mongo(session_id: str) -> list[dict[str, Any]]:
    try:
        col = _get_memory_collection()
        if col is None: return []
        doc = col.find_one({"session_id": session_id}, {"turns": 1, "_id": 0})
        if doc and "turns" in doc: return doc["turns"]
    except Exception as e:
        logger.debug(f"[FULL_MEMORY] MongoDB load failed for session {session_id}: {e}")
    return []

def _delete_session_from_mongo(session_id: str) -> None:
    def _sync():
        try:
            col = _get_memory_collection()
            if col is None: return
            col.delete_one({"session_id": session_id})
        except Exception as e:
            logger.debug(f"[FULL_MEMORY] MongoDB delete failed for session {session_id}: {e}")
    threading.Thread(target=_sync, daemon=True).start()

def _persist_full_history_async(session_id: str, turns: list[dict]) -> None:
    """Overwrite the full MongoDB document — used after in-place compression."""
    def _sync():
        try:
            col = _get_memory_collection()
            if col is None:
                return
            col.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "turns": turns,
                        "last_updated": datetime.now(timezone.utc),
                        "compressed": True,
                    },
                    "$setOnInsert": {
                        "session_id": session_id,
                        "created_at": datetime.now(timezone.utc),
                        "is_saved": False,
                        "project_id": None,
                    },
                },
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"[FULL_MEMORY] Background MongoDB full-write failed: {e}")
    threading.Thread(target=_sync, daemon=True).start()


def _get_compression_llm():
    try:
        from common.ai.llm import get_lite_llm
        return get_lite_llm()
    except Exception as e:
        logger.warning(f"[FULL_MEMORY] Could not load compression LLM: {e}")
        return None


def _compress_old_turns(session_id: str) -> None:
    """
    Compress conversation history with LangChain's ConversationSummaryMemory when
    the number of stored user/assistant pairs exceeds COMPRESSION_THRESHOLD.

    Keeps the most recent COMPRESSION_THRESHOLD pairs verbatim; all older messages
    are replaced with a rolling summary entry (role='summary').  Runs in a
    background thread so the main response path is never blocked.
    """
    # ── Step 1: read and decide under lock ────────────────────────────────────
    with _full_conversation_lock:
        raw = _full_conversation_store.get(session_id)
        if not raw:
            return

        if raw[0].get("role") == "summary":
            existing_summary_entry = raw[0]
            regular = raw[1:]
        else:
            existing_summary_entry = None
            regular = list(raw)

        pair_count = sum(1 for t in regular if t.get("role") == "user")
        if pair_count <= COMPRESSION_THRESHOLD:
            return

        keep_count = COMPRESSION_THRESHOLD * 2          # keep last N pairs as messages
        to_compress = regular[:-keep_count] if len(regular) > keep_count else []
        to_keep     = regular[-keep_count:]  if len(regular) > keep_count else regular

    if not to_compress:
        return

    # ── Step 2: call LLM outside lock ─────────────────────────────────────────
    llm = _get_compression_llm()
    if llm is None:
        return

    try:
        from langchain.memory import ConversationSummaryMemory
        from langchain_core.messages import HumanMessage, AIMessage

        memory = ConversationSummaryMemory(llm=llm, return_messages=True)
        existing_summary_text = existing_summary_entry["content"] if existing_summary_entry else ""

        lc_messages = []
        for turn in to_compress:
            role    = turn.get("role", "")
            content = turn.get("content", "")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))

        new_summary_text = memory.predict_new_summary(lc_messages, existing_summary_text)

        new_summary_entry = {
            "role": "summary",
            "content": new_summary_text,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "type": "compression_summary",
                "compressed_turns": len(to_compress),
                "source": "langchain_summary_memory",
            },
        }

        compressed = [new_summary_entry] + to_keep

        # ── Step 3: write back under lock ─────────────────────────────────────
        with _full_conversation_lock:
            if session_id in _full_conversation_store:
                _full_conversation_store[session_id] = compressed

        logger.info(
            f"[FULL_MEMORY] Compressed {len(to_compress)} messages → summary "
            f"for session {session_id} (kept last {len(to_keep)} messages)"
        )
        _persist_full_history_async(session_id, compressed)

    except Exception as e:
        logger.warning(f"[FULL_MEMORY] History compression failed for session {session_id}: {e}")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)

def _session_token_total(session_id: str) -> int:
    history = _full_conversation_store.get(session_id, [])
    return sum(_estimate_tokens(t.get("content", "")) for t in history)

def _prune_conversation_if_needed(session_id: str) -> None:
    history = _full_conversation_store.get(session_id)
    if not history or len(history) <= 2: return
    total = sum(_estimate_tokens(t.get("content", "")) for t in history)
    if total <= MAX_TOKENS_PER_SESSION: return
    
    original_count = len(history)
    while len(history) > 2:
        total -= _estimate_tokens(history[1].get("content", ""))
        history.pop(1)
        if total <= MAX_TOKENS_PER_SESSION: break
    
    logger.warning(f"[FULL_MEMORY] Token budget exceeded for session {session_id}: pruned {original_count - len(history)} old turns")

def _evict_lru_sessions_if_needed() -> None:
    while len(_full_conversation_store) > _MAX_IN_MEMORY_SESSIONS:
        evicted_sid, evicted_turns = _full_conversation_store.popitem(last=False)
        _session_last_access.pop(evicted_sid, None)
        for cb in _eviction_callbacks:
            cb(evicted_sid)
        logger.info(f"[FULL_MEMORY] LRU-evicted session {evicted_sid}")

def sweep_idle_sessions(idle_seconds: int | None = None) -> int:
    """Actively evict in-memory sessions idle longer than idle_seconds.

    Complements (does not replace) the cap-triggered _evict_lru_sessions_if_needed —
    that only fires reactively when _MAX_IN_MEMORY_SESSIONS is exceeded on insert;
    this runs on a schedule (see maintenance.py) so idle sessions are freed even
    when the process never hits the cap. Safe to call repeatedly/concurrently.
    """
    threshold = idle_seconds if idle_seconds is not None else _SESSION_IDLE_TTL_SECONDS
    now = time.time()
    evicted: list[str] = []
    with _full_conversation_lock:
        stale_ids = [sid for sid, last in _session_last_access.items() if now - last > threshold]
        for sid in stale_ids:
            _full_conversation_store.pop(sid, None)
            _session_last_access.pop(sid, None)
            evicted.append(sid)

    # Fire eviction callbacks outside the lock — they only touch their own
    # module's lock, so holding _full_conversation_lock here isn't needed and
    # would extend the lock hold across a potentially large evicted batch.
    for sid in evicted:
        for cb in _eviction_callbacks:
            cb(sid)
        logger.info(f"[FULL_MEMORY] Idle-swept session {sid} (idle > {threshold}s)")

    return len(evicted)

def add_conversation_turn(session_id: str, role: str, content: str, metadata: dict[str, Any] = None) -> None:
    entry = {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
    if metadata: entry["metadata"] = metadata

    # On an L1 miss (idle sweep / LRU / restart) rehydrate the persisted history
    # BEFORE appending — otherwise the fresh 1-turn L1 entry permanently shadows
    # the MongoDB history for the rest of the session. Mongo I/O stays outside
    # the lock.
    with _full_conversation_lock:
        missing = session_id not in _full_conversation_store
    prior_turns = _load_history_from_mongo(session_id) if missing else []

    with _full_conversation_lock:
        if session_id not in _full_conversation_store:
            _full_conversation_store[session_id] = list(prior_turns)
        _full_conversation_store[session_id].append(entry)
        _full_conversation_store.move_to_end(session_id)
        _session_last_access[session_id] = time.time()
        _prune_conversation_if_needed(session_id)
        _evict_lru_sessions_if_needed()
        turn_count = len(_full_conversation_store[session_id])
        est_tokens = _session_token_total(session_id)
        
    logger.info(f"[FULL_MEMORY] Added {role} message for session {session_id}, total turns: {turn_count}, est. tokens: ~{est_tokens:,}")
    _persist_turn_async(session_id, entry)

    # After a complete user/assistant pair, compress old turns in the background
    if role == "assistant":
        threading.Thread(target=_compress_old_turns, args=(session_id,), daemon=True).start()

def get_full_conversation_history(session_id: str) -> list[dict[str, Any]]:
    with _full_conversation_lock:
        history = _full_conversation_store.get(session_id)
        if history is not None:
            _full_conversation_store.move_to_end(session_id)
            _session_last_access[session_id] = time.time()
            return list(history)
            
    loaded = _load_history_from_mongo(session_id)
    if loaded:
        with _full_conversation_lock:
            _full_conversation_store[session_id] = loaded
            _full_conversation_store.move_to_end(session_id)
            _session_last_access[session_id] = time.time()
            _evict_lru_sessions_if_needed()
        return loaded
    return []

def get_session_token_estimate(session_id: str) -> int:
    return _session_token_total(session_id)

# Metadata keys whose values embed entire BOMs (full specifications, standards
# fields, taxonomy mappings per item). Assistant turns store these verbatim, and
# replaying them into prompts made a single intent-classification call cost
# ~138K input tokens. Prompts get lightweight counts + names instead; the full
# objects stay in the stored history for state restoration.
_HEAVY_METADATA_KEYS = ("instruments", "accessories")
_METADATA_PROMPT_MAX_CHARS = 2000


def _metadata_for_prompt(metadata: dict) -> str:
    slim = dict(metadata)
    for key in _HEAVY_METADATA_KEYS:
        items = slim.pop(key, None)
        if isinstance(items, list) and items:
            slim[f"{key}_count"] = len(items)
            names = [
                i.get("productName") or i.get("category") or i.get("accessory_name") or "?"
                for i in items if isinstance(i, dict)
            ][:20]
            if names:
                slim[f"{key}_names"] = names
    dumped = json.dumps(slim)
    if len(dumped) > _METADATA_PROMPT_MAX_CHARS:
        dumped = dumped[:_METADATA_PROMPT_MAX_CHARS] + "...(truncated)"
    return dumped


def format_conversation_for_prompt(session_id: str, max_turns: int = None, include_metadata: bool = False) -> str:
    # Read through get_full_conversation_history so an L1-evicted session
    # (idle sweep / LRU / process restart) rehydrates from MongoDB instead of
    # silently formatting as "No previous conversation.".
    history = get_full_conversation_history(session_id)
    if not history:
        return "No previous conversation."

    # Separate the optional leading summary entry from regular messages
    if history and history[0].get("role") == "summary":
        summary_entry = history[0]
        messages = history[1:]
    else:
        summary_entry = None
        messages = history

    if max_turns:
        messages = messages[-max_turns:]

    formatted_lines = []

    if summary_entry:
        formatted_lines.append(f"[CONVERSATION SUMMARY]: {summary_entry['content']}")

    for turn in messages:
        role    = turn["role"].upper()
        content = turn["content"]
        line    = f"{role}: {content}"
        if include_metadata and turn.get("metadata"):
            try:
                line += f"\n[METADATA]: {_metadata_for_prompt(turn['metadata'])}"
            except Exception:
                pass
        formatted_lines.append(line)

    return "\n".join(formatted_lines)

def clear_core_session(session_id: str) -> None:
    with _full_conversation_lock:
        _full_conversation_store.pop(session_id, None)
    _delete_session_from_mongo(session_id)
    logger.info(f"[MEMORY] Cleared core session data for {session_id}")

def mark_session_saved(session_id: str, project_id: str) -> None:
    """Stamp this session's conversation_memory doc as belonging to a saved
    project. Exempts it from the ephemeral-session TTL: the Mongo TTL index on
    conversation_memory only applies where is_saved=False (see
    mongodb_config.ensure_indexes' partialFilterExpression). Called from the
    project save route — a deliberate, infrequent, user-initiated action, so
    this write is synchronous (unlike the fire-and-forget turn persistence
    above) to guarantee the exemption lands before the caller returns.
    """
    if not session_id:
        return
    try:
        col = _get_memory_collection()
        if col is None:
            logger.warning(f"[FULL_MEMORY] mark_session_saved: no Mongo collection, session={session_id}")
            return
        col.update_one(
            {"session_id": session_id},
            {
                "$set": {"is_saved": True, "project_id": project_id},
                "$setOnInsert": {
                    "session_id": session_id,
                    "created_at": datetime.now(timezone.utc),
                    "last_updated": datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )
        logger.info(f"[FULL_MEMORY] Marked session {session_id} as saved (project_id={project_id})")
    except Exception as e:
        logger.warning(f"[FULL_MEMORY] mark_session_saved failed for session {session_id}: {e}")

def unmark_session_saved(session_id: str) -> None:
    """Re-arm the ephemeral TTL for a session after its linked project is
    deleted — flips is_saved back to False rather than hard-deleting the
    conversation doc, so a mis-click on project delete doesn't instantly
    destroy chat history; it just resumes the normal expiry countdown.
    """
    if not session_id:
        return
    try:
        col = _get_memory_collection()
        if col is None:
            return
        col.update_one(
            {"session_id": session_id},
            {"$set": {"is_saved": False, "project_id": None, "last_updated": datetime.now(timezone.utc)}},
        )
        logger.info(f"[FULL_MEMORY] Unmarked session {session_id} as saved (project deleted)")
    except Exception as e:
        logger.warning(f"[FULL_MEMORY] unmark_session_saved failed for session {session_id}: {e}")
